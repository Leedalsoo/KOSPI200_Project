from datetime import datetime, timezone

from environments.live.reconciliation import LiveReconciler
from environments.live.recovery import LiveRecovery
from environments.paper.position.paper_position import PaperPositionSnapshot
from environments.paper.reconciliation.reconciler import PaperReconciler


def _snapshot(*, is_stale=False):
    return PaperPositionSnapshot(
        instrument_id="A",
        quantity=1,
        average_price=100.0,
        observed_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        source="test",
        is_stale=is_stale,
    )


# --- LiveReconciler -------------------------------------------------------

def test_live_reconciler_flags_quantity_mismatch():
    result = LiveReconciler().compare_positions({"A": 2}, {"A": 1})
    assert result.consistent is False
    assert result.reasons == ("position mismatch: A",)


def test_live_reconciler_flags_instrument_missing_on_either_side():
    only_broker = LiveReconciler().compare_positions({"A": 1}, {})
    only_internal = LiveReconciler().compare_positions({}, {"A": 1})
    assert only_broker.consistent is False
    assert only_internal.consistent is False


def test_live_reconciler_accepts_matching_and_empty_positions():
    assert LiveReconciler().compare_positions({"A": 1}, {"A": 1}).consistent is True
    assert LiveReconciler().compare_positions({}, {}).consistent is True


# --- LiveRecovery fed by LiveReconciler -----------------------------------

def test_recovery_safe_stops_on_position_mismatch():
    result = LiveReconciler().compare_positions({"A": 2}, {"A": 1})
    decision = LiveRecovery().decide(result.consistent, broker_connected=True)
    assert decision.action == "SAFE_STOP"


def test_recovery_safe_stops_when_broker_disconnected():
    result = LiveReconciler().compare_positions({"A": 1}, {"A": 1})
    decision = LiveRecovery().decide(result.consistent, broker_connected=False)
    assert decision.action == "SAFE_STOP"


def test_recovery_resumes_only_when_connected_and_consistent():
    result = LiveReconciler().compare_positions({"A": 1}, {"A": 1})
    decision = LiveRecovery().decide(result.consistent, broker_connected=True)
    assert decision.action == "RESUME_ALLOWED"


# --- PaperReconciler (snapshot presence/staleness only) -------------------

def test_paper_reconciler_flags_missing_snapshot():
    assert PaperReconciler().compare(None, _snapshot()).matched is False
    assert PaperReconciler().compare(_snapshot(), None).matched is False
    result = PaperReconciler().compare(None, _snapshot())
    assert "missing_snapshot" in result.differences


def test_paper_reconciler_flags_stale_broker_snapshot():
    result = PaperReconciler().compare(_snapshot(is_stale=True), _snapshot())
    assert result.matched is False
    assert "stale_broker_snapshot" in result.differences


def test_paper_reconciler_accepts_fresh_snapshots():
    assert PaperReconciler().compare(_snapshot(), _snapshot()).matched is True