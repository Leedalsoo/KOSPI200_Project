from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
from typing import Any

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
    source: str = "OptionMaster+OptionOrderBook"

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "expiry", require_exact_option_expiry(self.expiry))
        except CanonicalOptionExpiryError as exc:
            raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc


class Track5OptionContractSource:
    """Select the exact ATM contract required by the pinned S5 specification.

    Selection is fail-closed when the authoritative contract identity,
    multiplier, or a valid two-sided order book is unavailable. Liquidity
    scoring is retained as diagnostic metadata; it does not substitute for
    the still-unapproved spread, freshness, or risk limits.
    """

    def __init__(self, option_master: Any, orderbook_source: Any | None = None) -> None:
        self.option_master = option_master
        self.orderbook_source = orderbook_source

    @staticmethod
    def _liquidity_score(book: Any) -> Decimal:
        if book is None:
            return Decimal("0")
        bids = getattr(book, "bid_levels", ()) or ()
        asks = getattr(book, "ask_levels", ()) or ()
        bid_qty = sum((Decimal(str(getattr(level, "quantity", 0) or 0)) for level in bids[:3]), Decimal("0"))
        ask_qty = sum((Decimal(str(getattr(level, "quantity", 0) or 0)) for level in asks[:3]), Decimal("0"))
        return bid_qty + ask_qty

    def select(self, *, expiry: str, current_price: Decimal, option_type: str) -> Track5OptionContractSelection:
        if self.option_master is None:
            raise ValueError("TRACK5_OPTION_MASTER_REQUIRED")
        if not expiry:
            raise ValueError("TRACK5_OPTION_EXPIRY_REQUIRED")
        option_type = str(option_type).upper()
        if option_type not in {"CALL", "PUT"}:
            raise ValueError("TRACK5_OPTION_TYPE_REQUIRED")
        current_price = Decimal(str(current_price))
        if current_price <= 0:
            raise ValueError("TRACK5_CURRENT_PRICE_REQUIRED")

        identities = tuple(self.option_master.list_contract_identities(expiry))
        by_strike = {}
        for identity in identities:
            if str(getattr(identity, "option_type", "")).upper() != option_type:
                continue
            strike = getattr(identity, "strike", None)
            multiplier = getattr(identity, "contract_multiplier", None)
            if strike is None or multiplier is None:
                continue
            strike = Decimal(str(strike))
            if strike <= 0 or Decimal(str(multiplier)) != KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER:
                continue
            if not getattr(identity, "shrn_iscd", ""):
                continue
            by_strike[strike] = identity

        strikes = sorted(by_strike)
        if not strikes:
            raise ValueError("TRACK5_LISTED_OPTION_NOT_FOUND")
        atm = min(strikes, key=lambda strike: (abs(strike - current_price), strike))
        identity = by_strike[atm]
        if self.orderbook_source is None:
            raise ValueError("TRACK5_ATM_ORDERBOOK_SOURCE_REQUIRED")
        book = self.orderbook_source.get_order_book(str(identity.shrn_iscd))
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
        score = self._liquidity_score(book)
        return Track5OptionContractSelection(
            expiry=str(expiry),
            atm_strike=atm,
            selected_strike=atm,
            option_type=option_type,
            contract=identity,
            strike_rank=0,
            liquidity_score=score,
        )
