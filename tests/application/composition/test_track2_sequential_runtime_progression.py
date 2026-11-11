import ast
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from contracts.types import ExecutionReport
from core.oms.multi_leg_plan import build_trap_plan
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge


def _plan():
    return build_trap_plan(
        group_id="s2-sequence-runtime",
        strategy_id="track2_asymmetric_trap",
        purpose="ASYMMETRIC_TRAP_WIDE",
        short_put=Decimal("490"),
        short_call=Decimal("510"),
        long_put=Decimal("495"),
        long_call=Decimal("505"),
        quantity=1,
    )


def _report(leg_id, status, filled=1, remaining=0):
    return ExecutionReport(
        client_order_id=f"client-{leg_id}",
        broker_order_id=f"broker-{leg_id}",
        execution_id=f"exec-{leg_id}" if filled else None,
        status=status,
        filled_quantity=filled,
        remaining_quantity=remaining,
        execution_price=Decimal("1") if filled else None,
        execution_timestamp=None,
        group_id="s2-sequence-runtime",
        leg_id=leg_id,
    )


def _bridge(monkeypatch, reports=(), pending=()):
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    plan = _plan()
    bridge._group_plans = {plan.group_id: plan}
    bridge.groups = {plan.group_id: list(reports)}
    bridge.pending_legs = {
        f"pending-{i}": (plan, plan.legs[0], object())
        for i, _ in enumerate(pending)
    }
    bridge._track2_zero_fill_cancel_reconciled = lambda *_args: True
    calls = []

    def fake_execute(next_plan, *, group_plan=None):
        calls.append((next_plan, group_plan))
        return SimpleNamespace(group_id=next_plan.group_id)

    monkeypatch.setattr(bridge, "execute", fake_execute, raising=False)
    return bridge, calls, plan


def test_runtime_progression_submits_only_first_leg_when_group_has_no_reports(monkeypatch):
    bridge, calls, plan = _bridge(monkeypatch)

    results = bridge.process_track2_entry_progress()

    assert len(results) == 1
    assert len(calls) == 1
    assert calls[0][0] is plan
    assert calls[0][1] is plan


def test_runtime_progression_advances_only_after_predecessor_filled(monkeypatch):
    bridge, calls, plan = _bridge(
        monkeypatch,
        reports=(_report("inner_put", "FILLED"),),
    )

    bridge.process_track2_entry_progress()

    assert len(calls) == 1
    assert calls[0][0].legs == plan.legs
    assert calls[0][1] is plan


def test_runtime_progression_blocks_partial_rejected_and_unknown_reports(monkeypatch):
    for status, filled, remaining in (
        ("PARTIALLY_FILLED", 1, 0),
        ("REJECTED", 0, 1),
        ("UNKNOWN", 0, 1),
        ("RECONCILIATION_REQUIRED", 0, 1),
        ("CANCEL_REQUESTED", 0, 1),
    ):
        bridge, calls, _ = _bridge(
            monkeypatch,
            reports=(_report("inner_put", status, filled, remaining),),
        )
        assert bridge.process_track2_entry_progress() == ()
        assert calls == []


def test_runtime_progression_advances_after_confirmed_zero_fill_cancel(monkeypatch):
    bridge, calls, plan = _bridge(
        monkeypatch,
        reports=(_report("inner_put", "CANCELLED", 0, 1),),
    )

    bridge.process_track2_entry_progress()

    assert len(calls) == 1
    assert calls[0][0].legs == plan.legs
    assert calls[0][1] is plan


def test_runtime_progression_blocks_zero_fill_cancel_without_position_reconciliation(monkeypatch):
    bridge, calls, _ = _bridge(
        monkeypatch,
        reports=(_report("inner_put", "CANCELLED", 0, 1),),
    )
    bridge._track2_zero_fill_cancel_reconciled = lambda *_args: False

    assert bridge.process_track2_entry_progress() == ()
    assert calls == []


def test_runtime_progression_does_not_submit_while_any_group_order_is_pending(monkeypatch):
    bridge, calls, _ = _bridge(
        monkeypatch,
        reports=(_report("inner_put", "FILLED"),),
        pending=("pending",),
    )

    assert bridge.process_track2_entry_progress() == ()
    assert calls == []


def test_runtime_progression_stops_after_all_four_legs_are_filled(monkeypatch):
    bridge, calls, plan = _bridge(
        monkeypatch,
        reports=tuple(_report(leg.leg_id, "FILLED") for leg in _plan().legs),
    )

    assert bridge.process_track2_entry_progress() == ()
    assert calls == []



def _real_zero_fill_guard_bridge(plan, *, account_positions=None, lots=(), pending=()):
    class _VssfOwner:
        def __init__(self):
            self.vssf_runtime = SimpleNamespace(
                account=SimpleNamespace(positions=account_positions or {})
            )

        def _authoritative_execute(self):
            return None

    owner = _VssfOwner()
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = "test-run"
    bridge.bundle = SimpleNamespace(
        execution=SimpleNamespace(_authoritative_execute=owner._authoritative_execute)
    )
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: tuple(lots))
    bridge.pending_legs = {
        f"pending-{i}": (plan, plan.legs[0], object())
        for i, _ in enumerate(pending)
    }
    bridge.identity_for_leg = lambda _plan, _leg: SimpleNamespace(instrument_id="OPT-INNER-PUT")
    return bridge


def test_zero_fill_cancel_guard_requires_flat_group_and_account_position():
    plan = _plan()
    bridge = _real_zero_fill_guard_bridge(plan)
    assert bridge._track2_zero_fill_cancel_reconciled(
        plan, (_report("inner_put", "CANCELLED", 0, 1),)
    )


def test_zero_fill_cancel_guard_blocks_if_account_position_is_not_flat():
    plan = _plan()
    bridge = _real_zero_fill_guard_bridge(
        plan, account_positions={"OPT-INNER-PUT": {"qty": "1"}}
    )
    assert not bridge._track2_zero_fill_cancel_reconciled(
        plan, (_report("inner_put", "CANCELLED", 0, 1),)
    )


def test_zero_fill_cancel_guard_blocks_if_group_lot_remains():
    plan = _plan()
    lot = SimpleNamespace(
        run_id="test-run", strategy_id=plan.strategy_id, group_id=plan.group_id,
        instrument_id="OPT-INNER-PUT", remaining_quantity=1,
    )
    bridge = _real_zero_fill_guard_bridge(plan, lots=(lot,))
    assert not bridge._track2_zero_fill_cancel_reconciled(
        plan, (_report("inner_put", "CANCELLED", 0, 1),)
    )


def test_zero_fill_cancel_guard_blocks_while_cancelled_order_remains_pending():
    plan = _plan()
    bridge = _real_zero_fill_guard_bridge(plan, pending=("still-pending",))
    assert not bridge._track2_zero_fill_cancel_reconciled(
        plan, (_report("inner_put", "CANCELLED", 0, 1),)
    )


def test_runtime_factory_wires_track2_progression_into_market_tick_processor():
    source = Path("application/composition/automated_virtual_runtime_factory.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    processor = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "process_pending_multi_leg"
    )
    calls = {
        node.func.attr
        for node in ast.walk(processor)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "process_track2_entry_progress" in calls


def test_virtual_bridge_gates_track2_routing_on_sequence_progress():
    source = Path("application/composition/virtual_multi_leg_execution.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    execute = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "execute"
    )
    names = {node.id for node in ast.walk(execute) if isinstance(node, ast.Name)}
    assert "track2_next_leg_id" in names
    assert "evaluate_track2_entry_progress" in names
    assert "leg.leg_id != track2_next_leg_id" in source


def test_runtime_progression_does_not_advance_on_rejected_status_even_if_reported_fill_is_full(monkeypatch):
    bridge, calls, _ = _bridge(
        monkeypatch,
        reports=(_report("inner_put", "REJECTED", 1, 0),),
    )
    assert bridge.process_track2_entry_progress() == ()
    assert calls == []


def test_runtime_progression_does_not_advance_on_mixed_terminal_statuses(monkeypatch):
    first = _report("inner_put", "FILLED", 1, 0)
    second = ExecutionReport(
        client_order_id="client-inner_put",
        broker_order_id="broker-inner_put",
        execution_id="exec-inner_put-duplicate",
        status="REJECTED",
        filled_quantity=0,
        remaining_quantity=0,
        execution_price=None,
        execution_timestamp=None,
        group_id="s2-sequence-runtime",
        leg_id="inner_put",
    )
    bridge, calls, _ = _bridge(monkeypatch, reports=(first, second))
    assert bridge.process_track2_entry_progress() == ()
    assert calls == []


def test_track2_trap_close_is_terminal_execution_plan():
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    plan = SimpleNamespace(strategy_id="track2_asymmetric_trap", purpose="TRAP_CLOSE")
    assert bridge._is_terminal_execution_plan(plan) is True


def test_track2_entry_plan_is_not_terminal_execution_plan():
    bridge = VirtualMultiLegExecutionBridge.__new__(VirtualMultiLegExecutionBridge)
    plan = SimpleNamespace(strategy_id="track2_asymmetric_trap", purpose="ASYMMETRIC_TRAP_WIDE")
    assert bridge._is_terminal_execution_plan(plan) is False
