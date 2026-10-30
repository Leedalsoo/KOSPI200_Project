from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Protocol

from contracts.kis_index_option_market_ws_adapter import (
    KISIndexOptionMarketWebSocketAdapter,
    KisIndexOptionMarketObservation,
)
from contracts.track4_kis_greeks_ws_adapter import KISIndexOptionGreeksWebSocketAdapter
from contracts.types import (
    MarketAnalytics,
    MarketDataProvenance,
    MarketObservation,
    MarketOrderBook,
    MarketQuote,
    OptionInstrumentIdentity,
    OrderBookLevel,
    RawMarketDataReference,
)


class OptionIdentityLookup(Protocol):
    def get_contract_identity(self, symbol: str) -> OptionInstrumentIdentity | None: ...


@dataclass(frozen=True)
class WebSocketUnderlyingContext:
    price: Decimal
    symbol: str
    observed_hour: str
    source: str


class KISWebSocketMarketObservationNormalizer:
    """Normalize authoritative KIS H0IOCNT0 trades and H0IOASP0 five-level quotes."""

    SOURCE = "kis_vts_websocket"
    PROVIDER = "KISOptionWebSocketAdapter"
    ENDPOINT = "ws://ops.koreainvestment.com:31000"

    def __init__(self, identity_lookup: OptionIdentityLookup) -> None:
        self._identity_lookup = identity_lookup
        self._market_adapter = KISIndexOptionMarketWebSocketAdapter()
        self._greeks_adapter = KISIndexOptionGreeksWebSocketAdapter()

    def normalize_frame(
        self,
        frame: str,
        *,
        received_at: datetime,
        run_id: str,
        raw_id: str,
        raw_content_hash: str | None = None,
        underlying: WebSocketUnderlyingContext | None = None,
    ) -> tuple[MarketObservation, ...]:
        if received_at.tzinfo is None:
            raise ValueError("KIS_WS_RECEIVED_AT_MUST_BE_TIMEZONE_AWARE")
        parts = frame.split("|", 3)
        if len(parts) != 4:
            raise ValueError("KIS_WS_FRAME_ENVELOPE_INVALID")
        tr_id = parts[1]
        if tr_id == "H0IOCNT0":
            market_records = self._market_adapter.adapt_many(frame, source="KIS:H0IOCNT0")
            greek_records = self._greeks_adapter.adapt_many(
                frame,
                observed_at=received_at.isoformat(),
                source="KIS:H0IOCNT0",
            )
            if len(market_records) != len(greek_records):
                raise ValueError("KIS_WS_MARKET_GREEKS_RECORD_COUNT_MISMATCH")
            values = parts[3].split("^")
            observed_hours = [
                values[index * 58 + 1] for index in range(len(market_records))
            ]
            timestamp_semantics = "KIS_BSOP_HOUR"
        elif tr_id == "H0IOASP0":
            market_records = self._market_adapter.adapt_many(frame, source="KIS:H0IOASP0")
            greek_records = (None,) * len(market_records)
            observed_hours = [market.observed_hour for market in market_records]
            # The raw HHMMSS-shaped field is retained, but not promoted to an
            # authoritative source timestamp until KIS field semantics are verified.
            timestamp_semantics = "KIS_H0IOASP0_HHMMSS_CANDIDATE_UNVERIFIED"
        else:
            raise ValueError(f"KIS_WS_OPTION_TR_UNSUPPORTED:{tr_id}")

        observations: list[MarketObservation] = []
        for market, greeks, observed_hour in zip(market_records, greek_records, observed_hours):
            observations.append(
                self._normalize_one(
                    market,
                    greeks,
                    observed_hour=observed_hour,
                    timestamp_semantics=timestamp_semantics,
                    received_at=received_at,
                    run_id=run_id,
                    raw_id=raw_id,
                    raw_content_hash=raw_content_hash,
                    underlying=underlying,
                )
            )
        return tuple(observations)

    def _normalize_one(
        self,
        market: KisIndexOptionMarketObservation,
        greeks,
        *,
        observed_hour: str,
        timestamp_semantics: str,
        received_at: datetime,
        run_id: str,
        raw_id: str,
        raw_content_hash: str | None,
        underlying: WebSocketUnderlyingContext | None,
    ) -> MarketObservation:
        identity = self._identity_lookup.get_contract_identity(market.shrn_iscd)
        if identity is None:
            raise ValueError(f"AUTHORITATIVE_OPTION_IDENTITY_REQUIRED:{market.shrn_iscd}")

        observation_seed = (
            f"{run_id}|{raw_id}|{market.source}|{market.shrn_iscd}|"
            f"{observed_hour}|{received_at.isoformat()}"
        )
        observation_id = sha256(observation_seed.encode("utf-8")).hexdigest()[:24]

        if market.order_book is None:
            order_book = MarketOrderBook(
                bids=(OrderBookLevel(level=1, price=market.bid_price, quantity=None),),
                asks=(OrderBookLevel(level=1, price=market.ask_price, quantity=None),),
                total_bid_quantity=None,
                total_ask_quantity=None,
            )
        else:
            def convert_levels(levels, side: str) -> tuple[OrderBookLevel, ...]:
                converted: list[OrderBookLevel] = []
                for index, level in enumerate(levels, start=1):
                    if level.price < 0 or level.quantity < 0:
                        raise ValueError(f"KIS_H0IOASP0_NEGATIVE_{side.upper()}_VALUE")
                    if level.price == 0 and level.quantity > 0:
                        raise ValueError(f"KIS_H0IOASP0_QUANTITY_WITHOUT_{side.upper()}_PRICE")
                    price = level.price if level.price > 0 else None
                    converted.append(
                        OrderBookLevel(level=index, price=price, quantity=level.quantity)
                    )
                return tuple(converted)

            bids = convert_levels(market.order_book.bid_levels, "bid")
            asks = convert_levels(market.order_book.ask_levels, "ask")
            order_book = MarketOrderBook(
                bids=bids,
                asks=asks,
                total_bid_quantity=sum((level.quantity or Decimal("0") for level in bids), Decimal("0")),
                total_ask_quantity=sum((level.quantity or Decimal("0") for level in asks), Decimal("0")),
            )

        analytics = (
            MarketAnalytics()
            if greeks is None
            else MarketAnalytics(
                implied_volatility=greeks.active_vol(),
                delta=greeks.current_delta(),
                gamma=greeks.current_gamma(),
                theta=greeks.current_theta(),
                vega=None,
            )
        )

        identity_metadata = ()
        metadata_provider = getattr(self._identity_lookup, "provenance_metadata", None)
        if callable(metadata_provider):
            identity_metadata = tuple(metadata_provider(market.shrn_iscd))

        tr_id = market.source.split(":")[-1]
        metadata = (
            ("transport", "websocket"),
            ("source_timestamp_semantics", timestamp_semantics),
            ("order_book_depth", "5" if market.order_book is not None else "1"),
        ) + identity_metadata

        return MarketObservation(
            observation_id=observation_id,
            observed_at=received_at,
            collected_at=received_at,
            source=self.SOURCE,
            provider=self.PROVIDER,
            schema_version="canonical-market-observation-v1",
            run_id=run_id,
            contract=identity,
            quote=MarketQuote(
                last=market.last_price,
                bid=market.bid_price if market.bid_price is not None and market.bid_price > 0 else None,
                ask=market.ask_price if market.ask_price is not None and market.ask_price > 0 else None,
                volume=market.volume,
            ),
            order_book=order_book,
            analytics=analytics,
            provenance=MarketDataProvenance(
                endpoints=(self.ENDPOINT,),
                tr_ids=(tr_id,),
                source_timestamps=(observed_hour,),
                metadata=metadata,
            ),
            raw_reference=RawMarketDataReference(
                raw_id=raw_id,
                content_hash=raw_content_hash,
            ),
            underlying_price=underlying.price if underlying is not None else None,
            underlying_symbol=underlying.symbol if underlying is not None else "",
            underlying_observed_hour=underlying.observed_hour if underlying is not None else "",
            underlying_source=underlying.source if underlying is not None else "",
        )
