from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Track7OptionContractSelection:
    """Authoritative CALL/PUT contract pair for one observed expiry/strike."""

    expiry: str
    strike: Decimal
    put: Any
    call: Any
    contract_multiplier: Decimal
    source: str = "OptionMaster.find_contract_identity"


class Track7OptionContractSource:
    """Resolve Track7's two-leg option pair only through the Option Master."""

    def __init__(self, option_master: Any) -> None:
        self.option_master = option_master

    def select(self, *, expiry: str, strike: Decimal) -> Track7OptionContractSelection:
        if self.option_master is None:
            raise ValueError("TRACK7_OPTION_MASTER_REQUIRED")
        if not expiry:
            raise ValueError("TRACK7_OPTION_EXPIRY_REQUIRED")
        if strike is None or Decimal(str(strike)) <= 0:
            raise ValueError("TRACK7_OPTION_STRIKE_REQUIRED")

        strike = Decimal(str(strike))
        put = self.option_master.find_contract_identity(expiry, "PUT", strike)
        call = self.option_master.find_contract_identity(expiry, "CALL", strike)
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
        if put_multiplier <= 0 or call_multiplier <= 0:
            raise ValueError("TRACK7_CONTRACT_MULTIPLIER_REQUIRED")
        if put_multiplier != call_multiplier:
            raise ValueError("TRACK7_CONTRACT_MULTIPLIER_MISMATCH")

        return Track7OptionContractSelection(
            expiry=str(expiry),
            strike=strike,
            put=put,
            call=call,
            contract_multiplier=put_multiplier,
        )
