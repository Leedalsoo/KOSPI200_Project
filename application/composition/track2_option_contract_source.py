from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Track2OptionContractSelection:
    expiry: str
    atm_strike: Decimal
    put: Any
    call: Any
    source: str = "OptionMaster.list_contract_identities"


class Track2OptionContractSource:
    """Resolve Track2 ATM strike from authoritative listed Option Master identities."""

    def __init__(self, option_master: Any) -> None:
        self.option_master = option_master

    def nearest_expiry(self, *, as_of: date) -> str:
        if self.option_master is None:
            raise ValueError("TRACK2_OPTION_MASTER_REQUIRED")
        expiries = sorted({
            str(identity.expiry).replace("-", "")[:6]
            for identity in self.option_master.list_contract_identities()
            if getattr(identity, "expiry", None) and getattr(identity, "shrn_iscd", "")
        })
        if not expiries:
            raise ValueError("TRACK2_OPTION_EXPIRY_NOT_FOUND")
        candidates = [value for value in expiries if value >= as_of.strftime("%Y%m")]
        if not candidates:
            raise ValueError("TRACK2_OPTION_EXPIRY_NOT_FOUND")
        return candidates[0]

    def select(self, *, expiry: str, current_price: Decimal) -> Track2OptionContractSelection:
        if self.option_master is None:
            raise ValueError("TRACK2_OPTION_MASTER_REQUIRED")
        if not expiry:
            raise ValueError("TRACK2_OPTION_EXPIRY_REQUIRED")
        if current_price is None or Decimal(str(current_price)) <= 0:
            raise ValueError("TRACK2_UNDERLYING_PRICE_REQUIRED")

        identities = tuple(self.option_master.list_contract_identities(expiry))
        calls: dict[Decimal, Any] = {}
        puts: dict[Decimal, Any] = {}
        for identity in identities:
            option_type = str(getattr(identity, "option_type", "")).upper()
            strike = getattr(identity, "strike", None)
            if option_type not in {"CALL", "PUT"} or strike is None:
                continue
            strike = Decimal(str(strike))
            if strike <= 0 or not getattr(identity, "shrn_iscd", ""):
                continue
            (calls if option_type == "CALL" else puts)[strike] = identity

        listed_strikes = sorted(set(calls) & set(puts))
        if not listed_strikes:
            raise ValueError("TRACK2_LISTED_STRIKE_NOT_FOUND")
        underlying = Decimal(str(current_price))
        atm = min(listed_strikes, key=lambda strike: (abs(strike - underlying), strike))
        put = puts[atm]
        call = calls[atm]
        put_multiplier = getattr(put, "contract_multiplier", None)
        call_multiplier = getattr(call, "contract_multiplier", None)
        if put_multiplier is None or call_multiplier is None:
            raise ValueError("TRACK2_CONTRACT_MULTIPLIER_REQUIRED")
        put_multiplier = Decimal(str(put_multiplier))
        call_multiplier = Decimal(str(call_multiplier))
        if put_multiplier <= 0 or call_multiplier <= 0:
            raise ValueError("TRACK2_CONTRACT_MULTIPLIER_REQUIRED")
        if put_multiplier != call_multiplier:
            raise ValueError("TRACK2_CONTRACT_MULTIPLIER_MISMATCH")
        return Track2OptionContractSelection(str(expiry), atm, put, call)


__all__ = ("Track2OptionContractSelection", "Track2OptionContractSource")
