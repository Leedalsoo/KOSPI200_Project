from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.types import OptionInstrumentIdentity


def _lot(*, instrument_id, option_type, strike, expiry, side="BUY"):
    identity = OptionInstrumentIdentity(
        instrument_id=instrument_id,
        symbol=instrument_id,
        expiry=expiry,
        option_type=option_type,
        strike=Decimal(str(strike)),
        contract_multiplier=Decimal("250000"),
        identity_source="TEST_FIXTURE",
    )
    return SimpleNamespace(
        run_id="run-1",
        strategy_id="track7_volatility_skew_weekly_insurance",
        remaining_quantity=1,
        instrument_identity=identity,
        instrument_id=instrument_id,
        position_role="NONE",
        side=side,
        group_id="group-1",
    )


def _bridge(lots):
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = "run-1"
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: tuple(lots))
    return bridge


def test_close_plan_filters_authoritative_option_type_strike_and_expiry() -> None:
    bridge = _bridge([
        _lot(instrument_id="PUT-4875", option_type="PUT", strike="487.5", expiry="20261022"),
        _lot(instrument_id="CALL-5125", option_type="CALL", strike="512.5", expiry="20261022"),
        _lot(instrument_id="CALL-5150", option_type="CALL", strike="515.0", expiry="20261022"),
    ])

    plan = bridge.build_close_plan_from_open_lots(
        strategy_id="track7_volatility_skew_weekly_insurance",
        purpose="WEEKLY_INSURANCE_CLOSE_CALL",
        asset_type="OPTION",
        option_type="CALL",
        strike=Decimal("512.5"),
        expiry="20261022",
    )

    assert len(plan.legs) == 1
    assert plan.legs[0].option_type == "CALL"
    assert plan.legs[0].strike == Decimal("512.5")
    assert plan.legs[0].side == "SELL"
    assert plan.legs[0].instrument_identity.instrument_id == "CALL-5125"


def test_close_plan_blocks_when_exact_option_identity_filter_matches_no_lot() -> None:
    bridge = _bridge([
        _lot(instrument_id="CALL-5125", option_type="CALL", strike="512.5", expiry="20261022"),
    ])

    with pytest.raises(ValueError, match="AUTHORITATIVE_OPEN_LOTS_REQUIRED"):
        bridge.build_close_plan_from_open_lots(
            strategy_id="track7_volatility_skew_weekly_insurance",
            purpose="WEEKLY_INSURANCE_CLOSE_PUT",
            asset_type="OPTION",
            option_type="PUT",
            strike=Decimal("487.5"),
            expiry="20261022",
        )
