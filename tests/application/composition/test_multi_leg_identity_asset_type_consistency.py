from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.types import OptionInstrumentIdentity


def _bridge():
    return object.__new__(VirtualMultiLegExecutionBridge)


def _option_identity():
    return OptionInstrumentIdentity(
        instrument_id="SYNTHETIC_CONTRACT:S2:CALL:20261112:500",
        symbol="SYNTHETIC_CONTRACT:S2:CALL:20261112:500",
        expiry="20261112", option_type="CALL", strike=Decimal("500"),
        contract_multiplier=Decimal("250000"),
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )


def _futures_identity():
    return FuturesInstrumentIdentity(
        instrument_id="KIS-FUTURES-2001", symbol="KIS-FUTURES-2001",
        product_type=FuturesProductType.MINI, contract_multiplier=Decimal("50000"),
        identity_source="KIS_FUTURES_MASTER",
    )


def test_option_leg_accepts_matching_stored_option_identity():
    identity = _option_identity()
    leg = SimpleNamespace(
        instrument_identity=identity, option_type="CALL", strike=Decimal("500")
    )
    plan = SimpleNamespace(strategy_id="synthetic_validation_strategy")

    assert _bridge().identity_for_leg(plan, leg) is identity


@pytest.mark.parametrize(
    "option_type,strike",
    [("PUT", Decimal("500")), ("CALL", Decimal("505")), (None, Decimal("500"))],
)
def test_option_leg_rejects_stored_identity_role_or_strike_mismatch(option_type, strike):
    leg = SimpleNamespace(
        instrument_identity=_option_identity(), option_type=option_type, strike=strike
    )
    plan = SimpleNamespace(strategy_id="synthetic_validation_strategy")

    with pytest.raises(ValueError, match="MULTI_LEG_STORED_OPTION_IDENTITY_LEG_MISMATCH"):
        _bridge().identity_for_leg(plan, leg)


def test_futures_leg_accepts_matching_stored_futures_identity():
    identity = _futures_identity()
    leg = SimpleNamespace(
        instrument_identity=identity, option_type=None, strike=None
    )
    plan = SimpleNamespace(strategy_id="futures_strategy")

    assert _bridge().identity_for_leg(plan, leg) is identity


def test_option_shaped_leg_rejects_stored_futures_identity():
    leg = SimpleNamespace(
        instrument_identity=_futures_identity(), option_type="CALL", strike=Decimal("500")
    )
    plan = SimpleNamespace(strategy_id="synthetic_validation_strategy")

    with pytest.raises(ValueError, match="MULTI_LEG_STORED_FUTURES_IDENTITY_LEG_MISMATCH"):
        _bridge().identity_for_leg(plan, leg)
