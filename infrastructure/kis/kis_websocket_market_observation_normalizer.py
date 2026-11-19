from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Protocol
from zoneinfo import ZoneInfo

from contracts.kis_index_option_market_ws_adapter import (
    KisIndexOptionMarketObservation,
    KISIndexOptionMarketWebSocketAdapter,
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
        frame_record_index: int = 0,
        session_date: date | None = None,
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
            if session_date is None:
                raise ValueError("KIS_H0IOCNT0_SESSION_DATE_REQUIRED")
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
        for record_index, (market, greeks, observed_hour) in enumerate(zip(market_records, greek_records, observed_hours)):
            observed_at = received_at
            if tr_id == "H0IOCNT0":
                if len(observed_hour) != 6 or not observed_hour.isdigit():
                    raise ValueError(f"KIS_H0IOCNT0_BSOP_HOUR_INVALID:{observed_hour}")
                try:
                    observed_at = datetime.strptime(
                        f"{session_date:%Y%m%d}{observed_hour}", "%Y%m%d%H%M%S"
                    ).replace(tzinfo=ZoneInfo("Asia/Seoul"))
                except ValueError as exc:
                    raise ValueError(f"KIS_H0IOCNT0_BSOP_HOUR_INVALID:{observed_hour}") from exc
            observations.append(
                self._normalize_one(
                    market,
                    greeks,
                    observed_hour=observed_hour,
                    observed_at=observed_at,
                    timestamp_semantics=timestamp_semantics,
                    received_at=received_at,
                    run_id=run_id,
                    raw_id=raw_id,
                    raw_content_hash=raw_content_hash,
                    record_index=frame_record_index + record_index,
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
        observed_at: datetime,
        timestamp_semantics: str,
        received_at: datetime,
        run_id: str,
        raw_id: str,
        raw_content_hash: str | None,
        record_index: int,
        underlying: WebSocketUnderlyingContext | None,
    ) -> MarketObservation:
        identity = self._identity_lookup.get_contract_identity(market.shrn_iscd)
        if identity is None:
            raise ValueError(f"AUTHORITATIVE_OPTION_IDENTITY_REQUIRED:{market.shrn_iscd}")

        observation_seed = (
            f"{run_id}|{raw_id}|{record_index}|{market.source}|{market.shrn_iscd}|"
            f"{observed_hour}|{observed_at.isoformat()}|{received_at.isoformat()}"
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
        is_exchange_event_time = timestamp_semantics == "KIS_BSOP_HOUR"
        source_timestamp_timezone = "Asia/Seoul" if is_exchange_event_time else "UNVERIFIED"
        source_timestamp_date_resolution = "TRADING_DATE" if is_exchange_event_time else "UNRESOLVED"
        source_to_receipt_lag_ms = ""
        if is_exchange_event_time:
            lag_ms = (
                received_at.astimezone(UTC) - observed_at.astimezone(UTC)
            ).total_seconds() * 1000
            source_to_receipt_lag_ms = f"{lag_ms:.3f}"
        metadata = (
            ("transport", "websocket"),
            ("source_timestamp_semantics", timestamp_semantics),
            ("source_timestamp_field", "BSOP_HOUR" if is_exchange_event_time else "H0IOASP0.HHMMSS"),
            ("source_timestamp_raw", market.observed_hour),
            ("source_timestamp_format", "HHMMSS"),
            ("source_timestamp_timezone", source_timestamp_timezone),
            ("source_timestamp_date_resolution", source_timestamp_date_resolution),
            ("source_timestamp_absolute", str(is_exchange_event_time).lower()),
            ("observed_at_semantics", "EXCHANGE_EVENT_TIME" if is_exchange_event_time else "RECEIPT_TIME_FALLBACK_SOURCE_TIME_UNVERIFIED"),
            ("source_to_receipt_lag_ms", source_to_receipt_lag_ms),
            ("frame_record_index", str(record_index)),
            ("received_at", received_at.isoformat()),
            ("receipt_timestamp", received_at.isoformat()),
            ("receipt_timezone", str(received_at.tzinfo)),
            ("order_book_depth", "5" if market.order_book is not None else "1"),
        ) + identity_metadata

        return MarketObservation(
            observation_id=observation_id,
            observed_at=observed_at,
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
