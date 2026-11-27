from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.position_provenance import PositionLotProvenance, PositionRole
from contracts.types import ExecutionLeg, MultiLegExecutionPlan
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore


SOURCE = "SYNTHETIC:DERIVED_SCENARIO"
INSTRUMENT = "SYNTHETIC:MINI:F21"
GROUP = "SYNTHETIC:S4:F21:GROUP"
STRATEGY = "track4_gamma_scalping"
RUN = "SYNTHETIC:S4:F21:RUN"
IDENTITY = FuturesInstrumentIdentity(
    instrument_id=INSTRUMENT,
    symbol=INSTRUMENT,
    product_type=FuturesProductType.MINI,
    contract_multiplier=Decimal("50000"),
    identity_source=SOURCE,
)


def _bridge() -> VirtualMultiLegExecutionBridge:
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = RUN
    bridge.position_lot_store = VirtualPositionLotStore()
    bridge.pending_legs = {}
    bridge.groups = {}
    bridge.position_groups = SimpleNamespace(all=lambda: {})
    bridge.bundle = SimpleNamespace(
        execution=SimpleNamespace(
            _authoritative_execute=SimpleNamespace(
                __self__=SimpleNamespace(vssf_runtime=SimpleNamespace(account=SimpleNamespace(positions={})))
            )
        )
    )
    return bridge


def _lot(bridge: VirtualMultiLegExecutionBridge, *, qty: int = 4) -> None:
    bridge.position_lot_store.apply_execution(PositionLotProvenance(
        run_id=RUN,
        instrument_id=INSTRUMENT,
        strategy_id=STRATEGY,
        group_id=GROUP,
        leg_id="entry-mini",
        client_order_id="entry-order",
        execution_id="entry-execution",
        side="BUY",
        opened_quantity=5,
        remaining_quantity=qty,
        execution_timestamp=datetime(2026, 11, 27, 1, 0, tzinfo=timezone.utc),
        instrument_identity=IDENTITY,
        contract_multiplier=Decimal("50000"),
        identity_source=SOURCE,
        position_role=PositionRole.NONE,
    ))


def _close_plan() -> MultiLegExecutionPlan:
    return MultiLegExecutionPlan(
        group_id=GROUP,
        strategy_id=STRATEGY,
        purpose="S4_TERMINAL_CLOSE",
        legs=(ExecutionLeg(
            leg_id="close-mini",
            side="SELL",
            quantity=4,
            instrument_identity=IDENTITY,
            position_role=PositionRole.NONE,
        ),),
    )


def _pending_close(*, status: str = "PARTIALLY_FILLED", remaining: int = 2):
    leg = ExecutionLeg(
        leg_id="close-mini-pending",
        side="SELL",
        quantity=3,
        instrument_identity=IDENTITY,
        position_role=PositionRole.NONE,
    )
    plan = MultiLegExecutionPlan(
        group_id=GROUP,
        strategy_id=STRATEGY,
        purpose="S4_TERMINAL_CLOSE",
        legs=(leg,),
    )
    command = SimpleNamespace(instrument_id=INSTRUMENT, side="SELL", quantity=3)
    report = SimpleNamespace(
        client_order_id="pending-close-order",
        status=status,
        filled_quantity=1,
        remaining_quantity=remaining,
        group_id=GROUP,
        leg_id=leg.leg_id,
    )
    return plan, leg, command, report


def test_close_plan_uses_actual_open_lots_minus_remaining_pending_close_quantity():
    bridge = _bridge()
    _lot(bridge, qty=4)  # one unit of the original five has already filled closed
    plan, leg, command, report = _pending_close(remaining=2)
    bridge.pending_legs[report.client_order_id] = (plan, leg, command)
    bridge.groups[GROUP] = [report]

    close_plan = bridge.build_close_plan_from_open_lots(
        strategy_id=STRATEGY, purpose="S4_TERMINAL_CLOSE", asset_type="FUTURES",
    )

    assert len(close_plan.legs) == 1
    assert close_plan.legs[0].side == "SELL"
    assert close_plan.legs[0].quantity == 2


def test_close_plan_blocks_when_pending_order_status_is_unknown():
    bridge = _bridge()
    _lot(bridge, qty=4)
    plan, leg, command, report = _pending_close(status="UNKNOWN", remaining=2)
    bridge.pending_legs[report.client_order_id] = (plan, leg, command)
    bridge.groups[GROUP] = [report]

    with pytest.raises(ValueError, match="PENDING_CLOSE_ORDER_RECONCILIATION_REQUIRED"):
        bridge.build_close_plan_from_open_lots(
            strategy_id=STRATEGY, purpose="S4_TERMINAL_CLOSE", asset_type="FUTURES",
        )


def test_flat_confirmation_is_denied_while_same_group_close_order_is_pending():
    bridge = _bridge()
    plan, leg, command, report = _pending_close(remaining=2)
    bridge.pending_legs[report.client_order_id] = (plan, leg, command)

    assert bridge._position_flat_for_plan(_close_plan()) is False


def test_flat_confirmation_ignores_pending_order_from_another_group():
    bridge = _bridge()
    other_leg = ExecutionLeg(
        leg_id="other-close",
        side="SELL",
        quantity=1,
        instrument_identity=IDENTITY,
        position_role=PositionRole.NONE,
    )
    other_plan = MultiLegExecutionPlan(
        group_id="OTHER-GROUP",
        strategy_id=STRATEGY,
        purpose="S4_TERMINAL_CLOSE",
        legs=(other_leg,),
    )
    bridge.pending_legs["other-order"] = (
        other_plan, other_leg,
        SimpleNamespace(instrument_id=INSTRUMENT, side="SELL", quantity=1),
    )

    assert bridge._position_flat_for_plan(_close_plan()) is True

@pytest.mark.parametrize("remaining", [4, 5])
def test_close_plan_rejects_pending_quantity_that_covers_or_exceeds_open_lots(remaining):
    bridge = _bridge()
    _lot(bridge, qty=4)
    plan, leg, command, report = _pending_close(remaining=remaining)
    bridge.pending_legs[report.client_order_id] = (plan, leg, command)
    bridge.groups[GROUP] = [report]

    expected = (
        "PENDING_CLOSE_COVERS_ALL_OPEN_LOTS"
        if remaining == 4
        else "PENDING_CLOSE_ORDER_EXCEEDS_OPEN_LOT_QUANTITY"
    )
    with pytest.raises(ValueError, match=expected):
        bridge.build_close_plan_from_open_lots(
            strategy_id=STRATEGY, purpose="S4_TERMINAL_CLOSE", asset_type="FUTURES",
        )


def test_flat_confirmation_requires_pending_order_to_be_terminal_and_removed():
    bridge = _bridge()
    plan, leg, command, report = _pending_close(remaining=2)
    bridge.pending_legs[report.client_order_id] = (plan, leg, command)

    assert bridge._position_flat_for_result(_close_plan()) is False
    bridge.pending_legs.pop(report.client_order_id)
    assert bridge._position_flat_for_result(_close_plan()) is True

def test_close_plan_blocks_when_pending_close_has_no_matching_group_report():
    bridge = _bridge()
    _lot(bridge, qty=4)
    plan, leg, command, report = _pending_close(remaining=2)
    bridge.pending_legs[report.client_order_id] = (plan, leg, command)
    bridge.groups[GROUP] = []

    with pytest.raises(ValueError, match="PENDING_CLOSE_ORDER_RECONCILIATION_REQUIRED"):
        bridge.build_close_plan_from_open_lots(
            strategy_id=STRATEGY, purpose="S4_TERMINAL_CLOSE", asset_type="FUTURES",
        )


def test_multiple_pending_close_orders_cannot_reserve_more_than_open_lots():
    bridge = _bridge()
    _lot(bridge, qty=4)
    first_plan, first_leg, first_command, first_report = _pending_close(remaining=4)
    second_plan, second_leg, second_command, second_report = _pending_close(remaining=1)
    second_leg = ExecutionLeg(
        leg_id="close-mini-pending-second",
        side="SELL",
        quantity=1,
        instrument_identity=IDENTITY,
        position_role=PositionRole.NONE,
    )
    second_plan = MultiLegExecutionPlan(
        group_id=GROUP, strategy_id=STRATEGY, purpose="S4_TERMINAL_CLOSE", legs=(second_leg,),
    )
    second_report.client_order_id = "pending-close-order-second"
    second_report.leg_id = second_leg.leg_id
    bridge.pending_legs[first_report.client_order_id] = (first_plan, first_leg, first_command)
    bridge.pending_legs[second_report.client_order_id] = (second_plan, second_leg, second_command)
    bridge.groups[GROUP] = [first_report, second_report]

    with pytest.raises(ValueError, match="PENDING_CLOSE_ORDER_EXCEEDS_OPEN_LOT_QUANTITY"):
        bridge.build_close_plan_from_open_lots(
            strategy_id=STRATEGY, purpose="S4_TERMINAL_CLOSE", asset_type="FUTURES",
        )
