from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Track7OptionContractSelection:
    expiry: str
    put_strike: Decimal
    call_strike: Decimal
    put: Any
    call: Any
    contract_multiplier: Decimal
    source: str = "OptionMaster.find_contract_identity"


class Track7OptionContractSource:
    """Resolve the weekly insurance pair through the authoritative Option Master."""

    STRIKE_OFFSET = Decimal("12.5")

    def __init__(self, option_master: Any) -> None:
        self.option_master = option_master

    def select(self, *, expiry: str, reference_price: Decimal) -> Track7OptionContractSelection:
        if self.option_master is None:
            raise ValueError("TRACK7_OPTION_MASTER_REQUIRED")
        if not expiry:
            raise ValueError("TRACK7_OPTION_EXPIRY_REQUIRED")
        reference_price = Decimal(str(reference_price))
        if reference_price <= 0:
            raise ValueError("TRACK7_REFERENCE_PRICE_REQUIRED")

        put_strike = reference_price - self.STRIKE_OFFSET
        call_strike = reference_price + self.STRIKE_OFFSET
        if put_strike <= 0:
            raise ValueError("TRACK7_PUT_STRIKE_REQUIRED")

        identities = tuple(self.option_master.list_contract_identities())
        candidates = tuple(x for x in identities if str(getattr(x, "expiry", "")).replace("-", "")[:8] == str(expiry).replace("-", "")[:8])
        put_target = put_strike
        call_target = call_strike
        put = min((x for x in candidates if str(getattr(x, "option_type", "")).upper() == "PUT"), key=lambda x: abs(Decimal(str(x.strike)) - put_target), default=None)
        call = min((x for x in candidates if str(getattr(x, "option_type", "")).upper() == "CALL"), key=lambda x: abs(Decimal(str(x.strike)) - call_target), default=None)
        if put is not None:
            put_strike = Decimal(str(put.strike))
        if call is not None:
            call_strike = Decimal(str(call.strike))
        if put is None or not getattr(put, "shrn_iscd", ""):
            raise ValueError("TRACK7_PUT_CONTRACT_NOT_FOUND")
        if call is None or not getattr(call, "shrn_iscd", ""):
            raise ValueError("TRACK7_CALL_CONTRACT_NOT_FOUND")

        put_multiplier = getattr(put, "contract_multiplier", None)
        call_multiplier = getattr(call, "contract_multiplier", None)
        if put_multiplier is None or call_multiplier is None:
            raise ValueError("TRACK7_CONTRACT_MULTIPLIER_REQUIRED")
        put_multiplier = Decimal(str(put_multiplier))
        call_multiplier = Decimal(str(call_multiplier))
        if put_multiplier <= 0 or call_multiplier <= 0 or put_multiplier != call_multiplier:
            raise ValueError("TRACK7_CONTRACT_MULTIPLIER_MISMATCH")

        return Track7OptionContractSelection(
            expiry=str(expiry),
            put_strike=put_strike,
            call_strike=call_strike,
            put=put,
            call=call,
            contract_multiplier=put_multiplier,
        )
