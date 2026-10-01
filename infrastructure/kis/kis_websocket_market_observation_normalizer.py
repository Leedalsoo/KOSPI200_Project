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
    """Normalize authoritative KIS H0IOCNT0 records into canonical observations."""

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
        market_records = self._market_adapter.adapt_many(frame, source="KIS:H0IOCNT0")
        greek_records = self._greeks_adapter.adapt_many(
            frame,
            observed_at=received_at.isoformat(),
            source="KIS:H0IOCNT0",
        )
        if len(market_records) != len(greek_records):
            raise ValueError("KIS_WS_MARKET_GREEKS_RECORD_COUNT_MISMATCH")

        parts = frame.split("|")
        observed_hours = [parts[3].split("^")[i * 58 + 1] for i in range(len(market_records))]
        observations: list[MarketObservation] = []
        for market, greeks, observed_hour in zip(market_records, greek_records, observed_hours):
            observations.append(
                self._normalize_one(
                    market,
                    greeks,
                    observed_hour=observed_hour,
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
        received_at: datetime,
        run_id: str,
        raw_id: str,
        raw_content_hash: str | None,
        underlying: WebSocketUnderlyingContext | None,
    ) -> MarketObservation:
        identity = self._identity_lookup.get_contract_identity(market.shrn_iscd)
        if identity is None:
            raise ValueError(f"AUTHORITATIVE_OPTION_IDENTITY_REQUIRED:{market.shrn_iscd}")

        observation_seed = f"{run_id}|{raw_id}|{market.shrn_iscd}|{observed_hour}|{received_at.isoformat()}"
        observation_id = sha256(observation_seed.encode("utf-8")).hexdigest()[:24]

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
                bid=market.bid_price,
                ask=market.ask_price,
                volume=market.volume,
            ),
            order_book=MarketOrderBook(
                bids=(OrderBookLevel(level=1, price=market.bid_price, quantity=None),),
                asks=(OrderBookLevel(level=1, price=market.ask_price, quantity=None),),
                total_bid_quantity=None,
                total_ask_quantity=None,
            ),
            analytics=MarketAnalytics(
                implied_volatility=greeks.active_vol(),
                delta=greeks.current_delta(),
                gamma=greeks.current_gamma(),
                theta=greeks.current_theta(),
                vega=None,
            ),
            provenance=MarketDataProvenance(
                endpoints=(self.ENDPOINT,),
                tr_ids=("H0IOCNT0",),
                source_timestamps=(observed_hour,),
                metadata=(("transport", "websocket"),),
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
