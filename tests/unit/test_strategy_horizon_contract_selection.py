from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.track6_option_contract_source import Track6OptionContractSource
from application.composition.track8_option_contract_source import Track8OptionContractSource


class OptionMaster:
    def __init__(self, strikes):
        self.identities = tuple(
            SimpleNamespace(
                shrn_iscd=f"{option_type}-{strike}",
                stnd_iscd=f"{option_type}-{strike}",
                expiry="2026-10-08",
                option_type=option_type,
                strike=Decimal(str(strike)),
                contract_multiplier=Decimal("250000"),
            )
            for strike in strikes
            for option_type in ("CALL", "PUT")
        )

    def list_contract_identities(self, expiry=None):
        return self.identities


def test_track6_selects_nearest_center_with_complete_daily_pair():
    master = OptionMaster([747.5, 752.5, 760, 772.5, 785])
    selection = Track6OptionContractSource(master).select(
        expiry="2026-10-08", current_price=Decimal("752.5")
    )
    assert selection.atm_strike == Decimal("760")
    assert selection.put.strike == Decimal("747.5")
    assert selection.call.strike == Decimal("772.5")


def test_track8_selects_nearest_center_with_complete_monthly_pair():
    master = OptionMaster([745, 750, 752.5, 765, 780])
    selection = Track8OptionContractSource(master).select(
        expiry="2026-10-08", current_price=Decimal("752.5")
    )
    assert selection.atm_strike == Decimal("765")
    assert selection.put.strike == Decimal("750")
    assert selection.call.strike == Decimal("780")


def test_track6_uses_nearest_listed_otm_pair_when_exact_offset_is_missing():
    master = OptionMaster([745, 750, 752.5, 765])
    selection = Track6OptionContractSource(master).select(
        expiry="2026-10-08", current_price=Decimal("752.5")
    )
    assert selection.put.strike == Decimal("745")
    assert selection.call.strike == Decimal("765")
