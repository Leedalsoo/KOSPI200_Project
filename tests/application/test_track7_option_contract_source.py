from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.track7_option_contract_source import Track7OptionContractSource


def _contract(symbol, option_type, strike, product_series, *, family="STANDARD"):
    return SimpleNamespace(
        shrn_iscd=symbol,
        expiry="20261112",
        option_type=option_type,
        strike=Decimal(str(strike)),
        contract_multiplier=Decimal("250000"),
        product_series=product_series,
        instrument_family=family,
    )


class _OptionMaster:
    def __init__(self, identities):
        self.identities = tuple(identities)

    def list_contract_identities(self):
        return self.identities


def test_track7_selection_requires_weekly_series_and_standard_product():
    master = _OptionMaster(
        (
            # Same-expiry monthly rows are closer to the reference price but must not win.
            _contract("MONTHLY_PUT", "PUT", "887.5", "MONTHLY"),
            _contract("MONTHLY_CALL", "CALL", "892.5", "MONTHLY"),
            # A closer weekly mini row must also be excluded.
            _contract("MINI_WEEKLY_PUT", "PUT", "877.5", "THURSDAY_WEEKLY", family="MINI"),
            _contract("MINI_WEEKLY_CALL", "CALL", "902.5", "THURSDAY_WEEKLY", family="MINI"),
            _contract("WEEKLY_PUT", "PUT", "875.0", "THURSDAY_WEEKLY"),
            _contract("WEEKLY_CALL", "CALL", "905.0", "THURSDAY_WEEKLY"),
        )
    )

    selection = Track7OptionContractSource(master).select(
        expiry="20261112", reference_price=Decimal("890")
    )

    assert selection.put.shrn_iscd == "WEEKLY_PUT"
    assert selection.call.shrn_iscd == "WEEKLY_CALL"
    assert selection.put.product_series == "THURSDAY_WEEKLY"
    assert selection.call.product_series == "THURSDAY_WEEKLY"
    assert selection.put.instrument_family == "STANDARD"
    assert selection.call.instrument_family == "STANDARD"


def test_track7_selection_fails_closed_when_only_monthly_contracts_exist():
    master = _OptionMaster(
        (
            _contract("MONTHLY_PUT", "PUT", "877.5", "MONTHLY"),
            _contract("MONTHLY_CALL", "CALL", "902.5", "MONTHLY"),
        )
    )

    with pytest.raises(ValueError, match="TRACK7_PUT_CONTRACT_NOT_FOUND"):
        Track7OptionContractSource(master).select(
            expiry="20261112", reference_price=Decimal("890")
        )
