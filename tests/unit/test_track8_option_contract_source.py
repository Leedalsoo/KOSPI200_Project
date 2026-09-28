from decimal import Decimal

import pytest

from application.composition.track8_option_contract_source import Track8OptionContractSource
from core.option.option_master import KisOptionContractIdentity


def identity(option_type, strike, symbol):
    return KisOptionContractIdentity(
        shrn_iscd=symbol,
        stnd_iscd="",
        expiry="2026-10-08",
        option_type=option_type,
        strike=Decimal(str(strike)),
        contract_multiplier=Decimal("250000"),
    )


class Master:
    def __init__(self, identities):
        self.identities = tuple(identities)

    def list_contract_identities(self, expiry=None):
        return tuple(i for i in self.identities if i.expiry == expiry)


def test_selects_monthly_atm_plus_minus_15_from_authoritative_master():
    identities = [
        identity(t, s, f"{t}{s}")
        for s in (1075, 1080, 1085, 1090, 1095, 1100, 1105)
        for t in ("PUT", "CALL")
    ]
    selection = Track8OptionContractSource(Master(identities)).select(
        expiry="2026-10-08", current_price=Decimal("1091")
    )
    assert selection.atm_strike == Decimal("1090")
    assert selection.put.strike == Decimal("1075")
    assert selection.call.strike == Decimal("1105")
def test_fails_closed_when_offset_contract_is_missing():
    identities = [
        identity(t, s, f"{t}{s}")
        for s in (1090, 1105)
        for t in ("PUT", "CALL")
    ]
    with pytest.raises(ValueError, match="TRACK8_LISTED_STRIKE_NOT_FOUND"):
        Track8OptionContractSource(Master(identities)).select(
            expiry="2026-10-08", current_price=Decimal("1090")
        )


def test_fails_closed_on_multiplier_mismatch():
    identities = [
        identity("PUT", 1075, "P1075"),
        identity("CALL", 1105, "C1105"),
        identity("PUT", 1090, "P1090"),
        identity("CALL", 1090, "C1090"),
    ]
    identities[1] = KisOptionContractIdentity(
        shrn_iscd="C1105",
        stnd_iscd="",
        expiry="2026-10-08",
        option_type="CALL",
        strike=Decimal("1105"),
        contract_multiplier=Decimal("50000"),
    )
    with pytest.raises(ValueError, match="TRACK8_CONTRACT_MULTIPLIER_MISMATCH"):
        Track8OptionContractSource(Master(identities)).select(
            expiry="2026-10-08", current_price=Decimal("1090")
        )
