from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
from core.option.option_master import KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER


@dataclass(frozen=True)
class Track5OptionContractSelection:
    expiry: str
    atm_strike: Decimal
    selected_strike: Decimal
    option_type: str
    contract: Any
    strike_rank: int
    liquidity_score: Decimal
    bid_price: Decimal
    ask_price: Decimal
    observed_at: datetime
    contract_multiplier: Decimal | None
    provenance: str
    validation_only: bool
    source: str = "KISOptionMaster+OptionOrderBook"

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "expiry", require_exact_option_expiry(self.expiry))
        except CanonicalOptionExpiryError as exc:
            raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc


class Track5OptionContractSource:
    """KIS-master-bound contract selection with source-timestamped quote validation.

    Validation-only S15b scenarios may fill quote/depth fields around a preserved
    KIS identity anchor. They never supply an authoritative contract multiplier.
    """

    def __init__(self, option_master: Any, orderbook_source: Any | None = None) -> None:
        self.option_master = option_master
        self.orderbook_source = orderbook_source
        manifest = getattr(orderbook_source, "manifest", None)
        self.validation_only = bool(isinstance(manifest, dict) and manifest.get("validation_only") is True)

    @property
    def validation_only_max_quote_age_seconds(self) -> int | None:
        if not self.validation_only:
            return None
        manifest = getattr(self.orderbook_source, "manifest", None)
        value = manifest.get("freshness_max_age_seconds") if isinstance(manifest, dict) else None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _liquidity_score(book: Any) -> Decimal:
        bids = getattr(book, "bid_levels", ()) or ()
        asks = getattr(book, "ask_levels", ()) or ()
        bid_qty = sum((Decimal(str(getattr(level, "quantity", 0) or 0)) for level in bids[:3]), Decimal("0"))
        ask_qty = sum((Decimal(str(getattr(level, "quantity", 0) or 0)) for level in asks[:3]), Decimal("0"))
        return bid_qty + ask_qty

    @staticmethod
    def _symbol(identity: Any) -> str:
        return str(
            getattr(identity, "shrn_iscd", None)
            or getattr(identity, "symbol", None)
            or getattr(identity, "instrument_id", None)
            or ""
        ).strip()

    def _standard_identity(self, identity: Any) -> bool:
        family = str(getattr(identity, "instrument_family", "") or "").upper()
        info_type = str(getattr(identity, "info_type", "") or "").upper()
        if family:
            return family == "STANDARD"
        if info_type:
            return info_type in {"5", "6"}
        if not self.validation_only:
            return False
        source = str(getattr(identity, "identity_source", "") or "")
        manifest = getattr(self.orderbook_source, "manifest", {})
        master_hash = str(manifest.get("target_kis_master_sha256", "")) if isinstance(manifest, dict) else ""
        symbol = self._symbol(identity)
        return (
            bool(master_hash)
            and source.endswith(master_hash)
            and symbol.startswith(("B016", "C016"))
        )

    def _validate_sources(self, *, as_of: datetime | None, max_quote_age_seconds: int | None) -> None:
        if self.option_master is None or not callable(getattr(self.option_master, "list_contract_identities", None)):
            raise ValueError("TRACK5_OPTION_MASTER_REQUIRED")
        if self.orderbook_source is None or not callable(getattr(self.orderbook_source, "get_order_book", None)):
            raise ValueError("TRACK5_ATM_ORDERBOOK_SOURCE_REQUIRED")
        if as_of is None or as_of.tzinfo is None:
            raise ValueError("TRACK5_QUOTE_AS_OF_REQUIRED")
        if max_quote_age_seconds is None or max_quote_age_seconds <= 0:
            raise ValueError("TRACK5_QUOTE_FRESHNESS_POLICY_UNSET")

    def _materialize(
        self, *, identity: Any, expiry: str, strike: Decimal,
        option_type: str, as_of: datetime, max_quote_age_seconds: int,
        strike_rank: int,
    ) -> Track5OptionContractSelection:
        if not self._standard_identity(identity):
            raise ValueError("TRACK5_STANDARD_KIS_OPTION_IDENTITY_UNVERIFIED")
        symbol = self._symbol(identity)
        if not symbol:
            raise ValueError("TRACK5_AUTHORITATIVE_KIS_OPTION_SYMBOL_REQUIRED")
        multiplier_raw = getattr(identity, "contract_multiplier", None)
        multiplier = Decimal(str(multiplier_raw)) if multiplier_raw is not None else None
        if multiplier is not None and multiplier != KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER:
            raise ValueError("TRACK5_OPTION_MULTIPLIER_MISMATCH")
        book = self.orderbook_source.get_order_book(symbol)
        bids = tuple(getattr(book, "bid_levels", ()) or ()) if book is not None else ()
        asks = tuple(getattr(book, "ask_levels", ()) or ()) if book is not None else ()
        if not bids or not asks:
            raise ValueError("TRACK5_ATM_TWO_SIDED_ORDERBOOK_REQUIRED")
        bid_price = Decimal(str(getattr(bids[0], "price", 0) or 0))
        ask_price = Decimal(str(getattr(asks[0], "price", 0) or 0))
        bid_quantity = Decimal(str(getattr(bids[0], "quantity", 0) or 0))
        ask_quantity = Decimal(str(getattr(asks[0], "quantity", 0) or 0))
        if bid_price <= 0 or ask_price <= 0 or ask_price < bid_price:
            raise ValueError("TRACK5_ATM_TWO_SIDED_QUOTE_INVALID")
        if bid_quantity <= 0 or ask_quantity <= 0:
            raise ValueError("TRACK5_ATM_TOP_OF_BOOK_DEPTH_UNAVAILABLE")
        observed_at = getattr(book, "observed_at", None)
        if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
            raise ValueError("TRACK5_ORDERBOOK_SOURCE_TIMESTAMP_UNAVAILABLE")
        if observed_at > as_of:
            raise ValueError("TRACK5_ORDERBOOK_SOURCE_TIMESTAMP_IN_FUTURE")
        age = (as_of - observed_at).total_seconds()
        if age < 0 or age > max_quote_age_seconds:
            raise ValueError("TRACK5_ORDERBOOK_SOURCE_STALE")
        provenance = str(getattr(book, "source", "") or "")
        synthetic = provenance.startswith("SYNTHETIC:DERIVED_SCENARIO")
        if synthetic and not self.validation_only:
            raise ValueError("TRACK5_SYNTHETIC_ORDERBOOK_NOT_VALIDATION_ONLY")
        return Track5OptionContractSelection(
            expiry=expiry,
            atm_strike=strike,
            selected_strike=strike,
            option_type=option_type,
            contract=identity,
            strike_rank=strike_rank,
            liquidity_score=self._liquidity_score(book),
            bid_price=bid_price,
            ask_price=ask_price,
            observed_at=observed_at,
            contract_multiplier=multiplier,
            provenance=provenance or "UNAVAILABLE",
            validation_only=self.validation_only,
        )

    def select(
        self, *, expiry: str, current_price: Decimal, option_type: str,
        as_of: datetime | None = None, max_quote_age_seconds: int | None = None,
    ) -> Track5OptionContractSelection:
        self._validate_sources(as_of=as_of, max_quote_age_seconds=max_quote_age_seconds)
        try:
            exact_expiry = require_exact_option_expiry(expiry)
        except CanonicalOptionExpiryError as exc:
            raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc
        option_type = str(option_type).upper()
        if option_type not in {"CALL", "PUT"}:
            raise ValueError("TRACK5_OPTION_TYPE_REQUIRED")
        current_price = Decimal(str(current_price))
        if current_price <= 0:
            raise ValueError("TRACK5_CURRENT_PRICE_REQUIRED")
        identities = tuple(self.option_master.list_contract_identities(exact_expiry))
        by_strike = {}
        for identity in identities:
            try:
                identity_expiry = require_exact_option_expiry(str(getattr(identity, "expiry", "") or ""))
            except CanonicalOptionExpiryError:
                continue
            if identity_expiry != exact_expiry or str(getattr(identity, "option_type", "")).upper() != option_type:
                continue
            strike = getattr(identity, "strike", None)
            if strike is None or not self._standard_identity(identity):
                continue
            strike = Decimal(str(strike))
            if strike > 0:
                by_strike[strike] = identity
        if not by_strike:
            raise ValueError("TRACK5_LISTED_STANDARD_OPTION_NOT_FOUND")
        distances = {strike: abs(strike - current_price) for strike in by_strike}
        min_distance = min(distances.values())
        nearest = [strike for strike, distance in distances.items() if distance == min_distance]
        if len(nearest) != 1:
            raise ValueError("TRACK5_ATM_TIE_BREAK_UNAPPROVED")
        strike = nearest[0]
        return self._materialize(
            identity=by_strike[strike], expiry=exact_expiry, strike=strike,
            option_type=option_type, as_of=as_of,
            max_quote_age_seconds=max_quote_age_seconds, strike_rank=0,
        )

    @staticmethod
    def _identity_expiry_matches(identity: Any, exact_expiry: str) -> bool:
        try:
            return require_exact_option_expiry(str(getattr(identity, "expiry", "") or "")) == exact_expiry
        except CanonicalOptionExpiryError:
            return False

    def select_exact(
        self, *, expiry: str, strike: Decimal, option_type: str,
        as_of: datetime | None = None, max_quote_age_seconds: int | None = None,
    ) -> Track5OptionContractSelection:
        self._validate_sources(as_of=as_of, max_quote_age_seconds=max_quote_age_seconds)
        try:
            exact_expiry = require_exact_option_expiry(expiry)
        except CanonicalOptionExpiryError as exc:
            raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc
        option_type = str(option_type).upper()
        exact_strike = Decimal(str(strike))
        if option_type not in {"CALL", "PUT"} or exact_strike <= 0:
            raise ValueError("TRACK5_EXACT_OPTION_IDENTITY_REQUIRED")
        identity = next((
            item for item in self.option_master.list_contract_identities(exact_expiry)
            if self._identity_expiry_matches(item, exact_expiry)
            and str(getattr(item, "option_type", "")).upper() == option_type
            and getattr(item, "strike", None) is not None
            and Decimal(str(item.strike)) == exact_strike
        ), None)
        if identity is None:
            raise ValueError("TRACK5_ACTIVE_OPTION_CONTRACT_NOT_FOUND")
        return self._materialize(
            identity=identity, expiry=exact_expiry, strike=exact_strike,
            option_type=option_type, as_of=as_of,
            max_quote_age_seconds=max_quote_age_seconds, strike_rank=-1,
        )


__all__ = ("Track5OptionContractSource", "Track5OptionContractSelection")
