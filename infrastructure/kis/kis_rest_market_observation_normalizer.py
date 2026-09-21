from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Protocol

from contracts.types import (
    MarketAnalytics,
    MarketDataProvenance,
    MarketObservation,
    MarketOrderBook,
    MarketQuote,
    OptionInstrumentIdentity,
    OrderBookLevel,
)


class OptionIdentityLookup(Protocol):
    def get_contract_identity(self, symbol: str) -> OptionInstrumentIdentity | None: ...


class KISRestMarketObservationNormalizer:
    PRICE_TR_ID = "FHMIF10000000"
    ASKING_PRICE_TR_ID = "FHMIF10010000"

    def __init__(self, identity_lookup: OptionIdentityLookup) -> None:
        self._identity_lookup = identity_lookup

    @staticmethod
    def _output(response: dict[str, Any], section: str = "output1") -> dict[str, Any]:
        value = response.get(section)
        if isinstance(value, dict):
            return value
        if section == "output1":
            value = response.get("output")
            if isinstance(value, dict):
                return value
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value[0]
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
        return {}

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return None

    @classmethod
    def _first(cls, row: dict[str, Any], *keys: str) -> Decimal | None:
        for key in keys:
            value = cls._decimal(row.get(key))
            if value is not None:
                return value
        return None

    @classmethod
    def _levels(cls, row: dict[str, Any], side: str) -> tuple[OrderBookLevel, ...]:
        levels: list[OrderBookLevel] = []
        for level in range(1, 6):
            price = cls._decimal(row.get(f"futs_{side}p{level}") or row.get(f"{side}p{level}"))
            quantity = cls._decimal(row.get(f"{side}p_rsqn{level}"))
            if price is None and quantity is None:
                continue
            levels.append(OrderBookLevel(level=level, price=price, quantity=quantity))
        return tuple(levels)

    def normalize(
        self,
        *,
        price_response: dict[str, Any],
        asking_price_response: dict[str, Any],
        collected_at: datetime,
        run_id: str,
    ) -> MarketObservation:
        if str(price_response.get("rt_cd", "0")) != "0" or str(asking_price_response.get("rt_cd", "0")) != "0":
            raise ValueError("KIS_REST_RESPONSE_NOT_SUCCESS")
        price_row = self._output(price_response, "output1")
        asking_identity_row = self._output(asking_price_response, "output1")
        asking_row = self._output(asking_price_response, "output2")
        symbol = str(price_row.get("futs_shrn_iscd") or asking_identity_row.get("futs_shrn_iscd") or "").strip()
        identity = self._identity_lookup.get_contract_identity(symbol)
        if identity is None or not identity.instrument_id or not identity.symbol:
            raise ValueError("AUTHORITATIVE_OPTION_IDENTITY_REQUIRED")

        price_timestamp = str(price_row.get("aspr_acpt_hour") or "").strip()
        asking_timestamp = str(asking_row.get("aspr_acpt_hour") or "").strip()
        if price_timestamp and asking_timestamp and price_timestamp != asking_timestamp:
            raise ValueError("KIS_REST_SOURCE_TIMESTAMP_MISMATCH")
        source_timestamp = price_timestamp or asking_timestamp
        tr_ids = (self.PRICE_TR_ID, self.ASKING_PRICE_TR_ID)
        seed = f"kis_vts_rest|{run_id}|{symbol}|{collected_at.isoformat()}|{tr_ids}"
        observation_id = sha256(seed.encode("utf-8")).hexdigest()[:24]
        return MarketObservation(
            observation_id=observation_id,
            observed_at=None,
            collected_at=collected_at,
            source="kis_vts_rest",
            provider="KISOptionRestAdapter",
            schema_version="canonical-market-observation-v1",
            run_id=run_id,
            contract=identity,
            quote=MarketQuote(
                last=self._first(price_row, "futs_prpr", "optn_prpr", "stck_prpr"),
                bid=self._first(asking_row, "futs_bidp1", "optn_bidp", "stck_bidp"),
                ask=self._first(asking_row, "futs_askp1", "optn_askp", "stck_askp"),
                volume=self._first(price_row, "acml_vol"),
            ),
            order_book=MarketOrderBook(
                bids=self._levels(asking_row, "bid"),
                asks=self._levels(asking_row, "ask"),
                total_bid_quantity=self._first(asking_row, "total_bidp_rsqn"),
                total_ask_quantity=self._first(asking_row, "total_askp_rsqn"),
            ),
            analytics=MarketAnalytics(
                implied_volatility=self._first(price_row, "hts_ints_vltl"),
                delta=self._first(price_row, "delta_val"),
                gamma=self._first(price_row, "gamma_val"),
                theta=self._first(price_row, "theta_val"),
                vega=self._first(price_row, "vega_val"),
            ),
            provenance=MarketDataProvenance(
                endpoints=(
                    "/uapi/domestic-futureoption/v1/quotations/inquire-price",
                    "/uapi/domestic-futureoption/v1/quotations/inquire-asking-price",
                ),
                tr_ids=tr_ids,
                source_timestamps=(source_timestamp,) if source_timestamp else (),
            ),
            raw_reference=None,
        )
