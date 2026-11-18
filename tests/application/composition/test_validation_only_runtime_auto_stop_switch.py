from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from application.composition.validation_only_runtime_auto_stop_switch import (
    SqliteRuntimeStopSwitchStateStore,
    ValidationOnlyRuntimeAutoStopSwitch,
)
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from contracts.risk_guard import RiskGuardStatusSnapshot
from contracts.trading_state import SensorLevel, SensorSnapshot, TradingHealthSnapshot
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionLedgerSnapshot,
    U19RecoveryStatus,
    evaluate_u19_recovery,
)
from core.risk.risk_engine import RiskEngine, RiskGate
from core.risk.risk_guard import RiskGuard

NOW = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


class _Margin:
    def calculate_order_margin(self, command):
        return 1.0


def _safe_inputs():
    guard = RiskGuard()
    guard.reset()
    health = TradingHealthSnapshot.from_sensors((
        SensorSnapshot("X2_TEST", SensorLevel.GREEN, NOW, "HEALTHY"),
    ))
    guard.evaluate(health=health)
    engine = RiskEngine(margin_engine=_Margin())
    decision = evaluate_u19_recovery(
        group_id="X2-GROUP",
        broker_snapshot=U19BrokerPositionSnapshot(
            "X2-GROUP", "X2-BROKER", NOW, "VALIDATION_ONLY:BROKER_EXCHANGE",
            (), True, True, "a" * 64,
        ),
        ledger_snapshot=U19ExecutionLedgerSnapshot(
            "X2-GROUP", "X2-LEDGER", NOW, "VALIDATION_ONLY:EXECUTION_LEDGER",
            (), True, "b" * 64, (), (),
        ),
    )
    invariant = SimpleNamespace(status="VALIDATION_ONLY_RUNTIME_INVARIANTS_PASS", issues=())
    freshness = FreshnessVerdict(
        FreshnessStatus.FRESH, "X2_TEST_FRESH", "x2-test-v1",
        environment="VIRTUAL", instrument_id="SYNTHETIC:X2", symbol="SYNTHETIC:X2",
        source_instant=NOW, received_at=NOW, evidence_sha256="c" * 64,
    )
    return guard, engine, invariant, decision, guard.snapshot(), freshness


def _switch(inputs, tmp_path):
    guard, engine, *_ = inputs
    return ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=guard, risk_engine=engine,
        state_store=SqliteRuntimeStopSwitchStateStore(tmp_path / "x2-stop.sqlite3"),
    )


def test_x2_stays_armed_only_when_all_safety_evidence_is_healthy(tmp_path):
    inputs = _safe_inputs()
    state = _switch(inputs, tmp_path).evaluate(
        invariant_report=inputs[2], u19_decision=inputs[3],
        risk_guard_snapshot=inputs[4], freshness_verdict=inputs[5],
    )
    assert state.status == "ARMED"
    assert state.order_admission_blocked is False
    assert state.risk_guard_latched is False
    assert state.risk_engine_latched is False
    assert state.persistence_confirmed is True


def test_x2_failed_x1_report_latches_both_existing_gates_and_denies_admission(tmp_path):
    inputs = _safe_inputs()
    switch = _switch(inputs, tmp_path)
    state = switch.evaluate(
        invariant_report=SimpleNamespace(status="RECONCILIATION_REQUIRED", issues=("MISMATCH",)),
        u19_decision=inputs[3], risk_guard_snapshot=inputs[4], freshness_verdict=inputs[5],
    )
    assert state.status == "TRIPPED"
    assert state.risk_guard_latched is True
    assert state.risk_engine_latched is True
    assert state.persistence_confirmed is True
    assert state.order_admission_blocked is True
    assert state.cancel_orders_requested is False
    assert state.flatten_positions_requested is False
    assert state.runtime_stop_requested is False
    gate = RiskGate(inputs[1], risk_guard_status_source=inputs[0])
    approved, token, reason = gate.admit_order(SimpleNamespace(qty=1), account=None)
    assert approved is False and token is None
    assert "KILL_SWITCH_ENGAGED" in (reason or "")


def test_x2_pending_u19_order_trips_stop_switch(tmp_path):
    inputs = _safe_inputs()
    pending = replace(
        inputs[3], status=U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED,
        restore_allowed=False, strategy_resume_allowed=False,
        pending_order_ids=("X2-PENDING",),
    )
    state = _switch(inputs, tmp_path).evaluate(
        invariant_report=inputs[2], u19_decision=pending,
        risk_guard_snapshot=inputs[4], freshness_verdict=inputs[5],
    )
    assert state.status == "TRIPPED"
    assert "U19_PENDING_ORDERS_PRESENT" in state.reasons


@pytest.mark.parametrize("status", [FreshnessStatus.STALE, FreshnessStatus.UNKNOWN, FreshnessStatus.IDENTITY_CONFLICT])
def test_x2_nonfresh_or_conflicting_market_data_trips(status, tmp_path):
    inputs = _safe_inputs()
    freshness = replace(inputs[5], status=status, reason="TEST_FAULT")
    state = _switch(inputs, tmp_path).evaluate(
        invariant_report=inputs[2], u19_decision=inputs[3],
        risk_guard_snapshot=inputs[4], freshness_verdict=freshness,
    )
    assert state.status == "TRIPPED"
    assert any(reason.startswith("MARKET_DATA_FRESHNESS_NOT_FRESH") for reason in state.reasons)


def test_x2_missing_safety_evidence_trips_fail_closed(tmp_path):
    inputs = _safe_inputs()
    state = _switch(inputs, tmp_path).evaluate(
        invariant_report=None, u19_decision=None,
        risk_guard_snapshot=None, freshness_verdict=None,
    )
    assert state.status == "TRIPPED"
    assert {
        "X1_INVARIANT_REPORT_UNAVAILABLE", "U19_RECOVERY_DECISION_UNAVAILABLE",
        "RISK_GUARD_STATUS_UNAVAILABLE", "MARKET_DATA_FRESHNESS_UNAVAILABLE",
    }.issubset(set(state.reasons))


def test_x2_red_risk_guard_health_trips(tmp_path):
    inputs = _safe_inputs()
    blocked = replace(inputs[4], admission_allowed=False, health_level=SensorLevel.RED, reason="RED")
    state = _switch(inputs, tmp_path).evaluate(
        invariant_report=inputs[2], u19_decision=inputs[3],
        risk_guard_snapshot=blocked, freshness_verdict=inputs[5],
    )
    assert state.status == "TRIPPED"
    assert any(reason.startswith("RISK_GUARD_BLOCKED") for reason in state.reasons)


def test_x2_manual_stop_is_latched(tmp_path):
    inputs = _safe_inputs()
    state = _switch(inputs, tmp_path).evaluate(
        invariant_report=inputs[2], u19_decision=inputs[3],
        risk_guard_snapshot=inputs[4], freshness_verdict=inputs[5],
        manual_stop_reason="OPERATOR_TEST_STOP",
    )
    assert state.status == "TRIPPED"
    assert "MANUAL_STOP:OPERATOR_TEST_STOP" in state.reasons


def test_x2_latch_is_sticky_after_all_inputs_return_healthy(tmp_path):
    inputs = _safe_inputs()
    switch = _switch(inputs, tmp_path)
    switch.trip("TEST_FIRST_TRIP")
    state = switch.evaluate(
        invariant_report=inputs[2], u19_decision=inputs[3],
        risk_guard_snapshot=inputs[4], freshness_verdict=inputs[5],
    )
    assert state.status == "TRIPPED"
    assert state.order_admission_blocked is True
    assert "TEST_FIRST_TRIP" in state.reasons


def test_x2_trip_is_idempotent_and_accumulates_reasons(tmp_path):
    inputs = _safe_inputs()
    switch = _switch(inputs, tmp_path)
    switch.trip("REASON_A")
    state = switch.trip("REASON_B")
    assert state.status == "TRIPPED"
    assert state.trigger_count == 2
    assert state.reasons == ("REASON_A", "REASON_B")
    assert state.risk_guard_latched and state.risk_engine_latched


def test_x2_requires_nonempty_manual_trip_reason(tmp_path):
    inputs = _safe_inputs()
    with pytest.raises(ValueError, match="X2_STOP_REASON_REQUIRED"):
        _switch(inputs, tmp_path).trip(" ")


def test_x2_does_not_offer_automatic_reset_or_cancel_flatten_runtime_stop(tmp_path):
    inputs = _safe_inputs()
    state = _switch(inputs, tmp_path).trip("TEST_STOP")
    assert state.reset_supported is False
    assert state.cancel_orders_requested is False
    assert state.flatten_positions_requested is False
    assert state.runtime_stop_requested is False


def test_x2_stop_latch_survives_switch_reconstruction(tmp_path):
    inputs = _safe_inputs()
    store_path = tmp_path / "persistent-x2.sqlite3"
    first = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=inputs[0], risk_engine=inputs[1],
        state_store=SqliteRuntimeStopSwitchStateStore(store_path),
    )
    first.trip("PERSISTED_TEST_STOP")

    new_guard = RiskGuard()
    new_guard.reset()
    new_guard.evaluate(health=TradingHealthSnapshot.from_sensors((
        SensorSnapshot("X2_RESTART", SensorLevel.GREEN, NOW, "HEALTHY"),
    )))
    new_engine = RiskEngine(margin_engine=_Margin())
    restarted = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=new_guard, risk_engine=new_engine,
        state_store=SqliteRuntimeStopSwitchStateStore(store_path),
    )
    state = restarted.snapshot()
    assert state.status == "TRIPPED"
    assert "PERSISTED_TEST_STOP" in state.reasons
    assert state.risk_guard_latched is True
    assert state.risk_engine_latched is True
    assert state.persistence_confirmed is True


def test_x2_persisted_latch_accumulates_reasons_across_restarts(tmp_path):
    inputs = _safe_inputs()
    path = tmp_path / "x2-reasons.sqlite3"
    first = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=inputs[0], risk_engine=inputs[1],
        state_store=SqliteRuntimeStopSwitchStateStore(path),
    )
    first.trip("REASON_A")
    first.trip("REASON_B")
    new_guard = RiskGuard()
    new_engine = RiskEngine(margin_engine=_Margin())
    restarted = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=new_guard, risk_engine=new_engine,
        state_store=SqliteRuntimeStopSwitchStateStore(path),
    )
    assert restarted.snapshot().reasons == ("REASON_A", "REASON_B")


def test_x2_unavailable_state_store_trips_fail_closed():
    inputs = _safe_inputs()
    class BrokenStore:
        def load(self):
            raise OSError("unavailable")
        def trip(self, reason, tripped_at):
            raise OSError("unavailable")
    switch = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=inputs[0], risk_engine=inputs[1], state_store=BrokenStore(),
    )
    state = switch.snapshot()
    assert state.status == "TRIPPED"
    assert "X2_STOP_STATE_STORE_UNAVAILABLE" in state.reasons
    assert state.risk_guard_latched is True
    assert state.risk_engine_latched is True
    assert state.persistence_confirmed is False



def test_x2_reports_latch_failure_when_both_admission_gates_cannot_be_engaged(tmp_path):
    class BrokenGuard:
        def engage(self, reason):
            raise OSError("guard failure")
        def evaluate(self, *, health, kill_switch_engaged):
            raise OSError("guard refresh failure")
        def snapshot(self):
            return RiskGuardStatusSnapshot(NOW, True, False, SensorLevel.GREEN, "STILL_ALLOWED", "broken")
    class BrokenEngine:
        def trigger_kill_switch(self, reason):
            raise OSError("engine failure")
        def is_kill_switch_active(self):
            return False
    switch = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=BrokenGuard(), risk_engine=BrokenEngine(),
        state_store=SqliteRuntimeStopSwitchStateStore(tmp_path / "broken-latch.sqlite3"),
    )
    state = switch.trip("TEST_LATCH_FAILURE")
    assert state.status == "TRIP_LATCH_FAILED"
    assert state.latch_confirmed is False
    assert state.order_admission_blocked is False
    assert len(state.latch_errors) == 3


def test_x2_reasserts_latches_after_external_reset(tmp_path):
    inputs = _safe_inputs()
    switch = _switch(inputs, tmp_path)
    switch.trip("STICKY_RESET_TEST")

    inputs[0].reset()
    inputs[1].reset_kill_switch()

    state = switch.snapshot()
    assert state.status == "TRIPPED"
    assert state.risk_guard_latched is True
    assert state.risk_engine_latched is True
    assert state.order_admission_blocked is True


def test_x2_engine_latch_alone_blocks_order_when_guard_latch_fails(tmp_path):
    class BrokenGuard:
        def engage(self, reason):
            raise OSError("guard failure")
        def evaluate(self, *, health, kill_switch_engaged):
            raise OSError("guard refresh failure")
        def snapshot(self):
            return RiskGuardStatusSnapshot(NOW, True, False, SensorLevel.GREEN, "READY", "broken")

    engine = RiskEngine(margin_engine=_Margin())
    switch = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=BrokenGuard(), risk_engine=engine,
        state_store=SqliteRuntimeStopSwitchStateStore(tmp_path / "engine-only.sqlite3"),
    )
    state = switch.trip("ENGINE_ONLY_TEST")
    assert state.status == "TRIPPED"
    assert state.risk_guard_latched is False
    assert state.risk_engine_latched is True
    assert state.order_admission_blocked is True
    approved, token, reason = RiskGate(engine, risk_guard_status_source=BrokenGuard()).admit_order(
        SimpleNamespace(qty=1), account=None,
    )
    assert approved is False and token is None
    assert "REJECTED_BY_KILL_SWITCH" in (reason or "")


def test_x2_guard_latch_alone_blocks_order_when_engine_latch_fails(tmp_path):
    class BrokenEngine:
        def trigger_kill_switch(self, reason):
            raise OSError("engine failure")
        def is_kill_switch_active(self):
            return False

    guard = RiskGuard()
    guard.evaluate(health=TradingHealthSnapshot.from_sensors((
        SensorSnapshot("X2_GUARD_ONLY", SensorLevel.GREEN, NOW, "HEALTHY"),
    )))
    engine = BrokenEngine()
    switch = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=guard, risk_engine=engine,
        state_store=SqliteRuntimeStopSwitchStateStore(tmp_path / "guard-only.sqlite3"),
    )
    state = switch.trip("GUARD_ONLY_TEST")
    assert state.status == "TRIPPED"
    assert state.risk_guard_latched is True
    assert state.risk_engine_latched is False
    assert state.order_admission_blocked is True
    approved, token, reason = RiskGate(engine, risk_guard_status_source=guard).admit_order(
        SimpleNamespace(qty=1), account=None,
    )
    assert approved is False and token is None
    assert "RISK_GUARD_BLOCKED" in (reason or "")