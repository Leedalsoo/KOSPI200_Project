from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
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


class Track5OptionContractSource:
    """Select Strategy5's liquid second/third strike around ATM.

    For a rising open the strategy buys a CALL above ATM; for a falling open
    it buys a PUT below ATM. Only the 2nd and 3rd OTM strikes are eligible.
    The higher available top-of-book quantity score wins; a missing liquidity
    observation is not treated as liquid.
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

        if option_type == "CALL":
            candidates = [strike for strike in strikes if strike > atm]
        else:
            candidates = [strike for strike in reversed(strikes) if strike < atm]
        candidates = candidates[:3]
        if len(candidates) < 2:
            raise ValueError("TRACK5_SECOND_OR_THIRD_STRIKE_REQUIRED")

        scored = []
        for rank, strike in enumerate(candidates, start=1):
            if rank not in {2, 3}:
                continue
            identity = by_strike[strike]
            book = None
            if self.orderbook_source is not None:
                book = self.orderbook_source.get_order_book(str(identity.shrn_iscd))
            score = self._liquidity_score(book)
            if score > 0:
                scored.append((score, rank, strike, identity))
        if not scored:
            raise ValueError("TRACK5_LIQUID_SECOND_OR_THIRD_STRIKE_REQUIRED")

        score, rank, strike, identity = max(scored, key=lambda item: (item[0], -item[1]))
        return Track5OptionContractSelection(
            expiry=str(expiry),
            atm_strike=atm,
            selected_strike=strike,
            option_type=option_type,
            contract=identity,
            strike_rank=rank,
            liquidity_score=score,
        )
