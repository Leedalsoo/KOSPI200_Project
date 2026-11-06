from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.strategy.track6_order_lifecycle import (
    Track6LifecycleConfig,
    Track6LifecycleError,
    Track6LifecycleStatus,
    Track6OrderLifecycle,
    Track6RankCandidate,
)

UTC = timezone.utc
T0 = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)


def candidates():
    return (
        Track6RankCandidate(5, Decimal("487.5"), Decimal("512.5"), "P5", "C5"),
        Track6RankCandidate(6, Decimal("485"), Decimal("515"), "P6", "C6"),
    )


def machine(*, first_rank=5, timeout_split="per_order"):
    return Track6OrderLifecycle(
        Track6LifecycleConfig(first_rank=first_rank, timeout_split=timeout_split),
        run_id="S6-TEST", trading_date="20261105",
    )


def prepared(m=None):
    m = m or machine()
    action = m.start_preflight(candidates(), T0)
    assert action.kind == "PREFLIGHT"
    selected = m.preflight_result(rank=action.rank, available=True, now=T0)
    assert selected.kind == "SELECT_RANK"
    return m


def test_unresolved_first_rank_and_timeout_split_fail_closed():
    m = Track6OrderLifecycle(Track6LifecycleConfig(), run_id="S6-TEST", trading_date="20261105")
    assert not m.config_valid
    assert m.start_preflight(candidates(), T0).kind == "BLOCKED"
    assert m.snapshot.status == Track6LifecycleStatus.BLOCKED_CONFIG


@pytest.mark.parametrize("first_rank,expected", [(5, (5, 6)), (6, (6, 5))])
def test_first_rank_controls_strict_sequential_candidate_order(first_rank, expected):
    m = machine(first_rank=first_rank)
    action = m.start_preflight(candidates(), T0)
    assert m.entry_rank_order == expected
    assert action.rank == expected[0]
    fallback = m.preflight_result(rank=expected[0], available=False, now=T0)
    assert fallback.kind == "PREFLIGHT"
    assert fallback.rank == expected[1]


def test_no_fallback_after_candidate_order_has_been_submitted():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    with pytest.raises(Track6LifecycleError, match="ONLY_ONE_WORKING"):
        m.submit_order(leg_id="call", client_order_id="C-1", quantity=1, now=T0)
    assert m.snapshot.selected_rank == 5


@pytest.mark.parametrize("split,expected_deadline", [
    ("per_order", T0 + timedelta(minutes=10)),
    ("shared_elapsed", T0 + timedelta(minutes=10)),
])
def test_timeout_split_sets_explicit_order_deadline(split, expected_deadline):
    m = prepared(machine(timeout_split=split))
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    assert m.snapshot.deadline_at == expected_deadline
    assert m.timeout_action(T0 + timedelta(minutes=9, seconds=59)).kind == "WAIT"
    action = m.timeout_action(T0 + timedelta(minutes=10))
    assert action.kind == "CANCEL"
    assert action.reason == "TIMEOUT_10M"


def test_per_order_and_shared_elapsed_diverge_on_opposite_leg_timer():
    per = prepared(machine(timeout_split="per_order"))
    shared = prepared(machine(timeout_split="shared_elapsed"))
    for m in (per, shared):
        m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
        m.execution_report(leg_id="put", client_order_id="P-1", status="FILLED",
                           filled_quantity=1, remaining_quantity=0,
                           average_fill_price=Decimal("1.0"), now=T0 + timedelta(minutes=2))
        m.submit_order(leg_id="call", client_order_id="C-1", quantity=1,
                       now=T0 + timedelta(minutes=2))
    assert per.snapshot.deadline_at == T0 + timedelta(minutes=12)
    assert shared.snapshot.deadline_at == T0 + timedelta(minutes=10)


def test_timeout_cancel_with_zero_fill_ends_day_no_rank_retry():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    m.timeout_action(T0 + timedelta(minutes=10))
    action = m.execution_report(leg_id="put", client_order_id="P-1", status="CANCELLED",
                                filled_quantity=0, remaining_quantity=1,
                                average_fill_price=None, now=T0 + timedelta(minutes=10, seconds=1))
    assert action.kind == "RECONCILE_POSITION"
    assert m.snapshot.status == Track6LifecycleStatus.ENTRY_WINDOW_CLOSED


def test_partial_fill_report_for_indivisible_single_contract_requires_reconciliation():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    action = m.execution_report(leg_id="put", client_order_id="P-1", status="PARTIALLY_FILLED",
                                filled_quantity=1, remaining_quantity=0,
                                average_fill_price=Decimal("1.2"), now=T0 + timedelta(seconds=1))
    assert action.kind == "RECONCILE"
    assert m.snapshot.open_quantity["put"] == 1
    assert m.snapshot.status == Track6LifecycleStatus.RECONCILIATION_REQUIRED


def test_rejected_order_does_not_fallback_to_other_rank():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    action = m.execution_report(leg_id="put", client_order_id="P-1", status="REJECTED",
                                filled_quantity=0, remaining_quantity=1,
                                average_fill_price=None, now=T0 + timedelta(seconds=1))
    assert action.kind == "STOP"
    assert m.snapshot.status == Track6LifecycleStatus.ENTRY_WINDOW_CLOSED


def test_1510_force_close_overrides_working_order_and_requires_cancel_reconciliation():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    action = m.force_close_due(datetime(2026, 11, 5, 6, 10, tzinfo=UTC))
    assert action.kind == "CANCEL_AND_RECONCILE"
    assert m.snapshot.status == Track6LifecycleStatus.FORCE_CLOSE_PENDING


def test_1510_force_close_uses_actual_residual_quantities_and_flat_confirmation():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    m.execution_report(leg_id="put", client_order_id="P-1", status="FILLED",
                       filled_quantity=1, remaining_quantity=0,
                       average_fill_price=Decimal("1.0"), now=T0 + timedelta(seconds=1))
    action = m.force_close_due(datetime(2026, 11, 5, 6, 10, tzinfo=UTC))
    assert action.kind == "FORCE_CLOSE"
    assert action.quantity == 1
    assert m.complete_force_close(remaining_positions={"put": 0, "call": 0},
                                  orders_reconciled=True).kind == "FLAT_CONFIRMED"
    assert m.snapshot.status == Track6LifecycleStatus.FLAT_CONFIRMED


def test_restart_requires_authoritative_order_and_position_reconciliation():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    payload = m.export_snapshot()
    restored = Track6OrderLifecycle.restore_snapshot(
        Track6LifecycleConfig(first_rank=5, timeout_split="per_order"), payload
    )
    assert restored.snapshot.status == Track6LifecycleStatus.RECONCILIATION_REQUIRED
    blocked = restored.complete_restart_reconciliation(
        open_orders={}, positions={"put": 0, "call": 0}, order_ids_match=True
    )
    assert blocked.kind == "BLOCKED"
    ok = restored.complete_restart_reconciliation(
        open_orders={"P-1": "NEW"}, positions={"put": 0, "call": 0},
        order_ids_match=True,
    )
    assert ok.kind == "RECONCILED"
    assert restored.snapshot.status == Track6LifecycleStatus.ORDER_WORKING


def test_restart_rejects_position_mismatch_and_unknown_order_ids():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    restored = Track6OrderLifecycle.restore_snapshot(
        Track6LifecycleConfig(first_rank=5, timeout_split="per_order"), m.export_snapshot()
    )
    blocked = restored.complete_restart_reconciliation(
        open_orders={"P-1": "NEW"}, positions={"put": 1, "call": 0},
        order_ids_match=False,
    )
    assert blocked.kind == "BLOCKED"


def test_missing_first_rank_candidate_falls_back_only_during_preflight():
    m = machine(first_rank=5)
    action = m.start_preflight((candidates()[1],), T0)
    assert action.kind == "PREFLIGHT"
    assert action.rank == 5
    fallback = m.preflight_result(rank=5, available=True, now=T0)
    assert fallback.kind == "PREFLIGHT"
    assert fallback.rank == 6
    selected = m.preflight_result(rank=6, available=True, now=T0)
    assert selected.kind == "SELECT_RANK"
    assert m.snapshot.selected_rank == 6


def test_fill_arriving_during_cancel_race_is_preserved_and_opposite_leg_can_start():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    assert m.timeout_action(T0 + timedelta(minutes=10)).kind == "CANCEL"
    action = m.execution_report(
        leg_id="put", client_order_id="P-1", status="CANCELLED",
        filled_quantity=1, remaining_quantity=0,
        average_fill_price=Decimal("1.25"), now=T0 + timedelta(minutes=10, seconds=1),
    )
    assert action.kind == "RECONCILE_POSITION"
    assert m.snapshot.status == Track6LifecycleStatus.SINGLE_LEG_FILLED
    opposite = m.submit_order(
        leg_id="call", client_order_id="C-1", quantity=1,
        now=T0 + timedelta(minutes=10, seconds=2),
    )
    assert opposite.kind == "SUBMIT"


def test_restart_and_force_close_require_complete_two_leg_position_snapshot():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    restored = Track6OrderLifecycle.restore_snapshot(
        Track6LifecycleConfig(first_rank=5, timeout_split="per_order"), m.export_snapshot()
    )
    blocked = restored.complete_restart_reconciliation(
        open_orders={"P-1": "NEW"}, positions={"put": 0}, order_ids_match=True
    )
    assert blocked.kind == "BLOCKED"
    assert blocked.reason == "TRACK6_AUTHORITATIVE_POSITION_SNAPSHOT_INCOMPLETE"

    m.execution_report(
        leg_id="put", client_order_id="P-1", status="FILLED",
        filled_quantity=1, remaining_quantity=0,
        average_fill_price=Decimal("1.0"), now=T0 + timedelta(seconds=1),
    )
    action = m.force_close_due(datetime(2026, 11, 5, 6, 10, tzinfo=UTC))
    assert action.kind == "FORCE_CLOSE"
    blocked_close = m.complete_force_close(remaining_positions={"put": 0}, orders_reconciled=True)
    assert blocked_close.kind == "RECONCILE"

def test_per_leg_trailing_exit_updates_durable_lifecycle_and_preserves_other_leg():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    m.execution_report(leg_id="put", client_order_id="P-1", status="FILLED",
                       filled_quantity=1, remaining_quantity=0,
                       average_fill_price=Decimal("1.0"), now=T0 + timedelta(seconds=1))
    m.submit_order(leg_id="call", client_order_id="C-1", quantity=1, now=T0 + timedelta(seconds=2))
    m.execution_report(leg_id="call", client_order_id="C-1", status="FILLED",
                       filled_quantity=1, remaining_quantity=0,
                       average_fill_price=Decimal("1.1"), now=T0 + timedelta(seconds=3))

    closed = m.close_leg_filled(leg_id="put", filled_quantity=1)
    assert closed.kind == "LEG_CLOSED"
    assert m.snapshot.open_quantity == {"put": 0, "call": 1}
    assert m.snapshot.status == Track6LifecycleStatus.SINGLE_LEG_HELD

    flat = m.close_leg_filled(leg_id="call", filled_quantity=1)
    assert flat.kind == "FLAT_CONFIRMED"
    assert m.snapshot.open_quantity == {"put": 0, "call": 0}
    assert m.snapshot.status == Track6LifecycleStatus.FLAT_CONFIRMED
from types import SimpleNamespace


def test_restart_reconciles_terminal_fill_into_single_leg_exposure():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    restored = Track6OrderLifecycle.restore_snapshot(
        Track6LifecycleConfig(first_rank=5, timeout_split="per_order"), m.export_snapshot(),
    )
    report = SimpleNamespace(
        client_order_id="P-1", status="FILLED", filled_quantity=1,
        remaining_quantity=0, execution_price=Decimal("1.35"),
    )
    action = restored.complete_restart_reconciliation(
        open_orders={"P-1": report}, positions={"put": 1, "call": 0}, order_ids_match=True,
    )
    assert action.kind == "RECONCILED"
    assert restored.snapshot.status == Track6LifecycleStatus.SINGLE_LEG_HELD
    assert restored.snapshot.open_quantity == {"put": 1, "call": 0}
    assert restored.snapshot.average_fill_price["put"] == Decimal("1.35")
    assert restored.snapshot.working_client_order_id is None


def test_restart_reconciliation_blocks_terminal_fill_position_mismatch():
    m = prepared()
    m.submit_order(leg_id="put", client_order_id="P-1", quantity=1, now=T0)
    restored = Track6OrderLifecycle.restore_snapshot(
        Track6LifecycleConfig(first_rank=5, timeout_split="per_order"), m.export_snapshot(),
    )
    report = SimpleNamespace(
        client_order_id="P-1", status="FILLED", filled_quantity=1,
        remaining_quantity=0, execution_price=Decimal("1.35"),
    )
    action = restored.complete_restart_reconciliation(
        open_orders={"P-1": report}, positions={"put": 0, "call": 0}, order_ids_match=True,
    )
    assert action.kind == "BLOCKED"
    assert action.reason == "TRACK6_POSITION_STATE_MISMATCH"
