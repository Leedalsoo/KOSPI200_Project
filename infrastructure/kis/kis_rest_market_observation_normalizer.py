from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from time import strptime
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

    @staticmethod
    def _source_time_candidate(value: Any) -> str | None:
        raw = "" if value is None else str(value).strip()
        if not re.fullmatch(r"\d{6}", raw) or raw == "000000":
            return None
        try:
            strptime(raw, "%H%M%S")
        except ValueError:
            return None
        return raw

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
        if collected_at.tzinfo is None or collected_at.utcoffset() is None:
            raise ValueError("KIS_REST_COLLECTED_AT_MUST_BE_TIMEZONE_AWARE")
        if str(price_response.get("rt_cd", "0")) != "0" or str(asking_price_response.get("rt_cd", "0")) != "0":
            raise ValueError("KIS_REST_RESPONSE_NOT_SUCCESS")
        price_row = self._output(price_response, "output1")
        asking_identity_row = self._output(asking_price_response, "output1")
        asking_row = self._output(asking_price_response, "output2")
        symbol = str(price_row.get("futs_shrn_iscd") or asking_identity_row.get("futs_shrn_iscd") or "").strip()
        identity = self._identity_lookup.get_contract_identity(symbol)
        if identity is None or not identity.instrument_id or not identity.symbol:
            raise ValueError("AUTHORITATIVE_OPTION_IDENTITY_REQUIRED")

        raw_price_timestamp = str(price_row.get("aspr_acpt_hour") or "").strip()
        raw_asking_timestamp = str(asking_row.get("aspr_acpt_hour") or "").strip()
        price_timestamp = self._source_time_candidate(raw_price_timestamp)
        asking_timestamp = self._source_time_candidate(raw_asking_timestamp)
        if price_timestamp and asking_timestamp and price_timestamp != asking_timestamp:
            raise ValueError("KIS_REST_SOURCE_TIMESTAMP_MISMATCH")
        source_timestamp = price_timestamp or asking_timestamp
        underlying_row = self._output(price_response, "output3")
        underlying_code = str(underlying_row.get("bstp_cls_code") or "").strip()
        underlying_symbol = str(underlying_row.get("hts_kor_isnm") or "").strip()
        underlying_price = self._decimal(underlying_row.get("bstp_nmix_prpr"))
        if underlying_code != "2001" or underlying_symbol != "KOSPI200" or underlying_price is None:
            raise ValueError("AUTHORITATIVE_KOSPI200_UNDERLYING_REQUIRED")
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
                gamma=self._first(price_row, "gama", "gamma_val"),
                theta=self._first(price_row, "theta", "theta_val"),
                vega=self._first(price_row, "vega", "vega_val"),
            ),
            provenance=MarketDataProvenance(
                endpoints=(
                    "/uapi/domestic-futureoption/v1/quotations/inquire-price",
                    "/uapi/domestic-futureoption/v1/quotations/inquire-asking-price",
                ),
                tr_ids=tr_ids,
                source_timestamps=(source_timestamp,) if source_timestamp else (),
                metadata=(
                    ("source_timestamp_field", "aspr_acpt_hour"),
                    ("source_timestamp_format", "HHMMSS"),
                    ("source_timestamp_semantics", "QUOTE_ACCEPTANCE_TIME_OF_DAY"),
                    ("source_timestamp_timezone", "UNVERIFIED"),
                    ("source_timestamp_date_resolution", "UNRESOLVED_TIME_ONLY"),
                    ("source_timestamp_absolute", "false"),
                    ("source_timestamp_status", "TIME_OF_DAY_ONLY" if source_timestamp else "UNKNOWN"),
                    ("source_capability_status", "UNVERIFIED"),
                    ("source_environment", "UNKNOWN"),
                    ("source_environment_status", "UNVERIFIED"),
                    ("source_time_semantics_verified", "false"),
                    ("source_timestamp_raw_price", raw_price_timestamp),
                    ("source_timestamp_raw_order_book", raw_asking_timestamp),
                    ("source_timestamp_zero_or_malformed_not_promoted", str(
                        bool((raw_price_timestamp and not price_timestamp)
                             or (raw_asking_timestamp and not asking_timestamp))
                    ).lower()),
                    ("receipt_timestamp", collected_at.isoformat()),
                    ("receipt_timezone", str(collected_at.tzinfo)),
                    ("observed_at_semantics", "RECEIPT_TIME_ONLY_SOURCE_INSTANT_UNRESOLVED"),
                ),
            ),
            raw_reference=None,
            underlying_price=underlying_price,
            underlying_symbol=underlying_symbol,
            underlying_observed_hour=source_timestamp,
            underlying_source='kis_vts_rest:price.output3',
        )
