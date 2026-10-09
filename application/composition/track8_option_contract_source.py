from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Track8OptionContractSelection:
    expiry: str
    atm_strike: Decimal
    put: Any
    call: Any
    source: str = "OptionMaster.list_contract_identities"


class Track8OptionContractSource:
    """Resolve Track8 monthly strangle contracts from the authoritative Option Master."""

    OFFSET = Decimal("15")

    def __init__(self, option_master: Any) -> None:
        self.option_master = option_master

    def select(self, *, expiry: str, current_price: Decimal) -> Track8OptionContractSelection:
        if self.option_master is None:
            raise ValueError("TRACK8_OPTION_MASTER_REQUIRED")
        if not expiry:
            raise ValueError("TRACK8_OPTION_EXPIRY_REQUIRED")
        if current_price is None or Decimal(str(current_price)) <= 0:
            raise ValueError("TRACK8_UNDERLYING_PRICE_REQUIRED")

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
            raise ValueError("TRACK8_LISTED_STRIKE_NOT_FOUND")

        underlying = Decimal(str(current_price))
        valid_centers = [strike for strike in listed_strikes if strike-self.OFFSET in puts and strike+self.OFFSET in calls]
        if not valid_centers:
            raise ValueError("TRACK8_LISTED_STRIKE_NOT_FOUND")
        # Resolve a center only when the authoritative monthly PUT/CALL pair
        # exists at the configured offset; nearest strike alone is insufficient.
        atm = min(valid_centers, key=lambda strike: (abs(strike - underlying), strike))
        put_strike = atm - self.OFFSET
        call_strike = atm + self.OFFSET
        put = puts.get(put_strike)
        call = calls.get(call_strike)
        if put is None or call is None:
            raise ValueError("TRACK8_LISTED_STRIKE_NOT_FOUND")

        put_multiplier = getattr(put, "contract_multiplier", None)
        call_multiplier = getattr(call, "contract_multiplier", None)
        if put_multiplier is None or call_multiplier is None:
            raise ValueError("TRACK8_CONTRACT_MULTIPLIER_REQUIRED")
        put_multiplier = Decimal(str(put_multiplier))
        call_multiplier = Decimal(str(call_multiplier))
        if put_multiplier <= 0 or call_multiplier <= 0:
            raise ValueError("TRACK8_CONTRACT_MULTIPLIER_REQUIRED")
        if put_multiplier != call_multiplier:
            raise ValueError("TRACK8_CONTRACT_MULTIPLIER_MISMATCH")

        return Track8OptionContractSelection(
            expiry=str(expiry),
            atm_strike=atm,
            put=put,
            call=call,
        )


__all__ = ("Track8OptionContractSelection", "Track8OptionContractSource")
