from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.track6_option_contract_source import Track6OptionContractSource


class ListedOptionMaster:
    def __init__(self, strikes):
        self.identities = tuple(
            SimpleNamespace(
                shrn_iscd=f"{option_type}-{strike}",
                stnd_iscd=f"{option_type}-{strike}",
                expiry="2027-01-14",
                option_type=option_type,
                strike=Decimal(str(strike)),
                contract_multiplier=Decimal("250000"),
            )
            for strike in strikes
            for option_type in ("CALL", "PUT")
        )

    def list_contract_identities(self, expiry=None):
        return self.identities


def test_track6_fallback_uses_nearest_listed_otm_put_and_call_without_inventing_strikes():
    strikes = [1060, 1065, 1070, 1075, 1080, 1085, 1090, 1095, 1100]
    selection = Track6OptionContractSource(ListedOptionMaster(strikes)).select(
        expiry="2027-01-14", current_price=Decimal("1081")
    )

    assert selection.put.strike == Decimal("1070")
    assert selection.call.strike == Decimal("1095")
    assert selection.put.strike in {Decimal(strike) for strike in strikes}
    assert selection.call.strike in {Decimal(strike) for strike in strikes}


def test_track6_fallback_fails_closed_when_listed_strikes_do_not_bracket_spot():
    master = ListedOptionMaster([1060, 1065, 1070])

    with pytest.raises(ValueError, match="TRACK6_LISTED_STRIKE_NOT_FOUND"):
        Track6OptionContractSource(master).select(
            expiry="2027-01-14", current_price=Decimal("1081")
        )
