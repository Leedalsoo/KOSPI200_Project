from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.types import OptionInstrumentIdentity
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.futures_contract_spec import FuturesProductType


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


def _track5_lot(*, instrument_id, asset_type, side, remaining_quantity, group_id="s5-existing-group"):
    if asset_type == "FUTURES":
        identity = FuturesInstrumentIdentity(
            instrument_id=instrument_id,
            symbol=instrument_id,
            product_type=FuturesProductType.MINI,
            contract_multiplier=Decimal("50000"),
            identity_source="KIS_MASTER",
        )
    else:
        identity = OptionInstrumentIdentity(
            instrument_id=instrument_id,
            symbol=instrument_id,
            expiry="20261112",
            option_type="CALL",
            strike=Decimal("887.5"),
            contract_multiplier=Decimal("250000"),
            identity_source="KIS_MASTER",
        )
    return SimpleNamespace(
        run_id="run-1",
        strategy_id="track5_gap_divergence",
        remaining_quantity=remaining_quantity,
        instrument_identity=identity,
        instrument_id=instrument_id,
        position_role="NONE",
        side=side,
        group_id=group_id,
    )


def test_s5_terminal_close_uses_all_authoritative_remaining_futures_and_option_lots():
    futures_identity_id = "MINI-FUT-202611"
    option_identity_id = "CALL-8875-20261112"
    bridge = _bridge([
        _track5_lot(instrument_id=futures_identity_id, asset_type="FUTURES", side="SELL", remaining_quantity=2),
        _track5_lot(instrument_id=futures_identity_id, asset_type="FUTURES", side="SELL", remaining_quantity=1),
        _track5_lot(instrument_id=option_identity_id, asset_type="OPTION", side="BUY", remaining_quantity=1),
        _track5_lot(instrument_id=option_identity_id, asset_type="OPTION", side="BUY", remaining_quantity=3),
    ])

    plan = bridge.build_close_plan_from_open_lots(
        strategy_id="track5_gap_divergence",
        purpose="TRACK5_GAP_HEDGE_TERMINAL_EXIT",
    )

    assert plan.group_id == "s5-existing-group"
    assert len(plan.legs) == 2
    by_instrument = {leg.instrument_identity.instrument_id: leg for leg in plan.legs}
    assert set(by_instrument) == {futures_identity_id, option_identity_id}
    assert by_instrument[futures_identity_id].side == "BUY"
    assert by_instrument[futures_identity_id].quantity == 3
    assert by_instrument[futures_identity_id].instrument_identity.product_type is FuturesProductType.MINI
    assert by_instrument[option_identity_id].side == "SELL"
    assert by_instrument[option_identity_id].quantity == 4


def test_s5_gap_fill_close_plan_remains_futures_only_with_actual_remaining_quantity():
    futures_identity_id = "MINI-FUT-202611"
    option_identity_id = "CALL-8875-20261112"
    bridge = _bridge([
        _track5_lot(instrument_id=futures_identity_id, asset_type="FUTURES", side="SELL", remaining_quantity=3),
        _track5_lot(instrument_id=option_identity_id, asset_type="OPTION", side="BUY", remaining_quantity=4),
    ])

    plan = bridge.build_close_plan_from_open_lots(
        strategy_id="track5_gap_divergence",
        purpose="TRACK5_GAP_HEDGE_FUTURES_EXIT",
        asset_type="FUTURES",
        leg_id_prefix="MINI_FUTURES_EXIT",
    )

    assert len(plan.legs) == 1
    assert plan.legs[0].instrument_identity.instrument_id == futures_identity_id
    assert plan.legs[0].side == "BUY"
    assert plan.legs[0].quantity == 3
