from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.automated_virtual_trading_loop import (
    AutomatedVirtualTradingLoop,
)
from application.composition.validation_only_runtime_auto_stop_switch import (
    SqliteRuntimeStopSwitchStateStore,
    ValidationOnlyRuntimeAutoStopSwitch,
    ValidationOnlyRuntimeStopAdmissionSource,
)
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from contracts.trading_state import SensorLevel, SensorSnapshot, TradingHealthSnapshot
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionLedgerSnapshot,
    evaluate_u19_recovery,
)
from core.risk.risk_engine import RiskEngine
from core.risk.risk_guard import RiskGuard

NOW = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


class _Margin:
    def calculate_order_margin(self, command):
        return 1.0


class _BaseStatusSource:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


class _ExecutionOwner:
    def __init__(self):
        self.vssf_runtime = SimpleNamespace(margin_engine=_Margin())

    def _authoritative_execute(self):
        return None


def _inputs():
    guard = RiskGuard()
    guard.reset()
    guard.evaluate(health=TradingHealthSnapshot.from_sensors((
        SensorSnapshot("T4_X2", SensorLevel.GREEN, NOW, "HEALTHY"),
    )))
    engine = RiskEngine(margin_engine=_Margin())
    decision = evaluate_u19_recovery(
        group_id="T4-X2-GROUP",
        broker_snapshot=U19BrokerPositionSnapshot(
            "T4-X2-GROUP", "T4-X2-BROKER", NOW, "VALIDATION_ONLY:BROKER_EXCHANGE",
            (), True, True, "a" * 64,
        ),
        ledger_snapshot=U19ExecutionLedgerSnapshot(
            "T4-X2-GROUP", "T4-X2-LEDGER", NOW, "VALIDATION_ONLY:EXECUTION_LEDGER",
            (), True, "b" * 64, (), (),
        ),
    )
    invariant = SimpleNamespace(
        status="VALIDATION_ONLY_RUNTIME_INVARIANTS_PASS", issues=(),
        manifest_sha256="c" * 64,
    )
    freshness = FreshnessVerdict(
        FreshnessStatus.FRESH, "T4_X2_SYNTHETIC_FRESH", "t4-x2-v1",
        environment="VIRTUAL", instrument_id="SYNTHETIC_CONTRACT:T4_X2",
        symbol="SYNTHETIC_CONTRACT:T4_X2", source_instant=NOW,
        received_at=NOW, evidence_sha256="d" * 64,
    )
    return guard, engine, invariant, decision, guard.snapshot(), freshness


def _switch(inputs, tmp_path):
    guard, engine, *_ = inputs
    return ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=guard,
        risk_engine=engine,
        state_store=SqliteRuntimeStopSwitchStateStore(tmp_path / "t4-x2.sqlite3"),
    )


def _loop(engine, stop_switch, admission_source):
    owner = _ExecutionOwner()
    bundle = SimpleNamespace(
        execution=SimpleNamespace(_authoritative_execute=owner._authoritative_execute),
        broker=object(),
    )
    return AutomatedVirtualTradingLoop(
        bundle=bundle,
        strategy_hub=object(),
        run_id="T4-X2-SYNTHETIC-RUN",
        context_builder=lambda *_: {},
        identity_provider=lambda *_: None,
        risk_engine=engine,
        risk_guard_status_source=admission_source,
        runtime_stop_switch=stop_switch,
    )


def test_t4_virtual_loop_uses_same_engine_and_preserves_healthy_admission(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    base = _BaseStatusSource(inputs[4])
    admission = ValidationOnlyRuntimeStopAdmissionSource(base, stop_switch)
    loop = _loop(inputs[1], stop_switch, admission)

    assert loop.risk_gate.engine is inputs[1]
    assert loop._runtime_orders_blocked() is False
    assert admission.snapshot().admission_allowed is True
    assert loop.risk_gate._check_risk_guard() is None


def test_t4_x2_trip_blocks_virtual_single_and_multileg_admission(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)

    stop_switch.evaluate(
        invariant_report=inputs[2],
        u19_decision=inputs[3],
        risk_guard_snapshot=inputs[4],
        freshness_verdict=inputs[5],
        manual_stop_reason="T4_SYNTHETIC_INTEGRATION_TEST",
    )

    assert loop._runtime_orders_blocked() is True
    assert admission.snapshot().admission_allowed is False
    assert "X2_RUNTIME_STOP_LATCHED" in admission.snapshot().reason
    assert loop.risk_gate._check_risk_guard().startswith("RISK_GUARD_BLOCKED:X2_RUNTIME_STOP_LATCHED")
    assert loop.risk_gate.engine is inputs[1]


def test_t4_x2_rechecks_latch_before_pending_or_multileg_submission(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    loop = _loop(
        inputs[1], stop_switch,
        ValidationOnlyRuntimeStopAdmissionSource(_BaseStatusSource(inputs[4]), stop_switch),
    )

    assert loop._runtime_orders_blocked() is False
    stop_switch.trip("T4_PENDING_SUBMISSION_TEST")
    assert loop._runtime_orders_blocked() is True
    assert loop._runtime_orders_blocked() is True


def test_t4_x2_status_read_error_is_locally_fail_closed(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    loop = _loop(
        inputs[1], stop_switch,
        ValidationOnlyRuntimeStopAdmissionSource(_BaseStatusSource(inputs[4]), stop_switch),
    )

    class BrokenSwitch:
        def snapshot(self):
            raise OSError("status unavailable")

        def trip(self, reason):
            raise OSError("persistence unavailable")

    loop.runtime_stop_switch = BrokenSwitch()
    with pytest.raises(RuntimeError, match="X2_RUNTIME_STOP_COULD_NOT_BE_LATCHED"):
        loop._runtime_orders_blocked()

def test_t4_x2_blocks_pending_and_multileg_submitters_without_invoking_them(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    loop = _loop(
        inputs[1], stop_switch,
        ValidationOnlyRuntimeStopAdmissionSource(_BaseStatusSource(inputs[4]), stop_switch),
    )
    calls = {"pending": 0, "multi_leg": 0}

    def process_pending(_tick):
        calls["pending"] += 1
        return ("PENDING_PROCESSED",)

    def execute_multi_leg(_plan):
        calls["multi_leg"] += 1
        return "MULTI_LEG_SUBMITTED"

    loop.pending_multi_leg_processor = process_pending
    loop.multi_leg_executor = execute_multi_leg
    assert loop._process_pending_multi_leg_if_admitted("TICK") == ("PENDING_PROCESSED",)
    admitted, result = loop._execute_multi_leg_if_admitted(SimpleNamespace())
    assert admitted is True and result == "MULTI_LEG_SUBMITTED"
    assert calls == {"pending": 1, "multi_leg": 1}

    stop_switch.trip("T4_BLOCK_SUBMISSION_TEST")
    assert loop._process_pending_multi_leg_if_admitted("TICK") == ()
    admitted, result = loop._execute_multi_leg_if_admitted(SimpleNamespace())
    assert admitted is False and result is None
    assert calls == {"pending": 1, "multi_leg": 1}


def test_t4_virtual_multileg_path_obeys_base_riskguard_and_engine_latches(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    blocked_guard = SimpleNamespace(
        observed_at=NOW, admission_allowed=False, kill_switch_engaged=True,
        health_level=SensorLevel.RED, reason="SYNTHETIC_RISK_GUARD_BLOCK",
        decision_version="synthetic-risk-v1",
    )
    loop = _loop(
        inputs[1], stop_switch,
        ValidationOnlyRuntimeStopAdmissionSource(_BaseStatusSource(blocked_guard), stop_switch),
    )
    assert loop._runtime_orders_blocked() is True
    assert stop_switch.snapshot().status == "TRIPPED"

    healthy_inputs = _inputs()
    second_switch = _switch(healthy_inputs, tmp_path / "engine")
    second_loop = _loop(
        healthy_inputs[1], second_switch,
        ValidationOnlyRuntimeStopAdmissionSource(_BaseStatusSource(healthy_inputs[4]), second_switch),
    )
    healthy_inputs[1].trigger_kill_switch("SYNTHETIC_EXTERNAL_RISK_LATCH")
    assert second_loop._runtime_orders_blocked() is True
    assert second_switch.snapshot().status == "TRIPPED"


def test_t4_x2_virtual_multileg_path_exposes_concurrent_latch_to_callback_window(tmp_path):
    from threading import Event, Thread

    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    loop = _loop(
        inputs[1], stop_switch,
        ValidationOnlyRuntimeStopAdmissionSource(_BaseStatusSource(inputs[4]), stop_switch),
    )
    gate_read_completed = Event()
    allow_gate_result_return = Event()
    callback_observations = []
    callback_calls = []
    original_gate_check = loop._runtime_orders_blocked

    def interleaved_gate_check():
        admitted = original_gate_check()
        gate_read_completed.set()
        assert allow_gate_result_return.wait(timeout=5)
        return admitted

    def concurrent_latch_actor():
        assert gate_read_completed.wait(timeout=5)
        stop_switch.trip("T4_SYNTHETIC_CONCURRENT_X2_LATCH")
        allow_gate_result_return.set()

    def synthetic_executor(_plan):
        callback_calls.append("invoked")
        callback_observations.append(stop_switch.snapshot().status)
        return "SYNTHETIC_CALLBACK_ONLY"

    loop._runtime_orders_blocked = interleaved_gate_check
    loop.multi_leg_executor = synthetic_executor
    actor = Thread(target=concurrent_latch_actor)
    actor.start()
    try:
        admitted, result = loop._execute_multi_leg_if_admitted(SimpleNamespace())
    finally:
        allow_gate_result_return.set()
        actor.join(timeout=5)

    assert not actor.is_alive()
    assert admitted is True
    assert result == "SYNTHETIC_CALLBACK_ONLY"
    assert stop_switch.snapshot().status == "TRIPPED"
    assert callback_calls == ["invoked"]
    assert callback_observations == ["TRIPPED"]


def test_t4_x2_latch_during_executor_callback_does_not_interrupt_inflight_callback(tmp_path):
    from threading import Event, Thread

    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    loop = _loop(
        inputs[1], stop_switch,
        ValidationOnlyRuntimeStopAdmissionSource(_BaseStatusSource(inputs[4]), stop_switch),
    )
    callback_entered = Event()
    allow_callback_to_finish = Event()
    callback_observations = []

    def synthetic_executor(_plan):
        callback_observations.append(("entered", stop_switch.snapshot().status))
        callback_entered.set()
        assert allow_callback_to_finish.wait(timeout=5)
        callback_observations.append(("finished", stop_switch.snapshot().status))
        return "SYNTHETIC_CALLBACK_COMPLETED"

    def concurrent_latch_actor():
        assert callback_entered.wait(timeout=5)
        stop_switch.trip("T4_SYNTHETIC_X2_LATCH_DURING_CALLBACK")
        allow_callback_to_finish.set()

    loop.multi_leg_executor = synthetic_executor
    actor = Thread(target=concurrent_latch_actor)
    actor.start()
    try:
        admitted, result = loop._execute_multi_leg_if_admitted(SimpleNamespace())
    finally:
        allow_callback_to_finish.set()
        actor.join(timeout=5)

    assert not actor.is_alive()
    assert admitted is True
    assert result == "SYNTHETIC_CALLBACK_COMPLETED"
    assert stop_switch.snapshot().status == "TRIPPED"
    assert callback_observations == [
        ("entered", "ARMED"),
        ("finished", "TRIPPED"),
    ]


def test_t4_x2_latch_after_first_callback_blocks_next_multileg_dispatch(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    loop = _loop(
        inputs[1], stop_switch,
        ValidationOnlyRuntimeStopAdmissionSource(_BaseStatusSource(inputs[4]), stop_switch),
    )
    callback_calls = []

    def synthetic_executor(plan):
        callback_calls.append(plan)
        stop_switch.trip("T4_SYNTHETIC_X2_LATCH_AFTER_FIRST_CALLBACK")
        return "SYNTHETIC_FIRST_CALLBACK_COMPLETED"

    loop.multi_leg_executor = synthetic_executor
    first_admitted, first_result = loop._execute_multi_leg_if_admitted("PLAN_1")
    second_admitted, second_result = loop._execute_multi_leg_if_admitted("PLAN_2")

    assert first_admitted is True
    assert first_result == "SYNTHETIC_FIRST_CALLBACK_COMPLETED"
    assert second_admitted is False
    assert second_result is None
    assert callback_calls == ["PLAN_1"]
    assert stop_switch.snapshot().status == "TRIPPED"


def test_t4_x2_latch_during_executor_exception_preserves_latch_and_blocks_next_dispatch(tmp_path):
    from threading import Event, Thread

    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    loop = _loop(
        inputs[1], stop_switch,
        ValidationOnlyRuntimeStopAdmissionSource(_BaseStatusSource(inputs[4]), stop_switch),
    )
    callback_entered = Event()
    allow_callback_to_raise = Event()
    callback_calls = []

    def synthetic_executor(plan):
        callback_calls.append(plan)
        callback_entered.set()
        assert allow_callback_to_raise.wait(timeout=5)
        raise RuntimeError("T4_SYNTHETIC_EXECUTOR_FAILURE")

    def concurrent_latch_actor():
        assert callback_entered.wait(timeout=5)
        stop_switch.trip("T4_SYNTHETIC_X2_LATCH_DURING_EXECUTOR_EXCEPTION")
        allow_callback_to_raise.set()

    loop.multi_leg_executor = synthetic_executor
    actor = Thread(target=concurrent_latch_actor)
    actor.start()
    try:
        with pytest.raises(RuntimeError, match="T4_SYNTHETIC_EXECUTOR_FAILURE"):
            loop._execute_multi_leg_if_admitted("PLAN_EXCEPTION")
    finally:
        allow_callback_to_raise.set()
        actor.join(timeout=5)

    assert not actor.is_alive()
    assert stop_switch.snapshot().status == "TRIPPED"
    assert callback_calls == ["PLAN_EXCEPTION"]

    admitted, result = loop._execute_multi_leg_if_admitted("PLAN_AFTER_EXCEPTION")
    assert admitted is False
    assert result is None
    assert callback_calls == ["PLAN_EXCEPTION"]
    assert stop_switch.snapshot().status == "TRIPPED"


def test_t4_x2_executor_exception_latch_survives_switch_recreation_and_blocks_dispatch(tmp_path):
    from threading import Event, Thread

    inputs = _inputs()
    state_path = tmp_path / "durable-x2.sqlite3"
    stop_switch = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=inputs[0],
        risk_engine=inputs[1],
        state_store=SqliteRuntimeStopSwitchStateStore(state_path),
    )
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)
    callback_entered = Event()
    allow_callback_to_raise = Event()

    def synthetic_executor(_plan):
        callback_entered.set()
        assert allow_callback_to_raise.wait(timeout=5)
        raise RuntimeError("T4_SYNTHETIC_REOPEN_FAILURE")

    def concurrent_latch_actor():
        assert callback_entered.wait(timeout=5)
        stop_switch.trip("T4_SYNTHETIC_DURABLE_LATCH_DURING_EXCEPTION")
        allow_callback_to_raise.set()

    loop.multi_leg_executor = synthetic_executor
    actor = Thread(target=concurrent_latch_actor)
    actor.start()
    try:
        with pytest.raises(RuntimeError, match="T4_SYNTHETIC_REOPEN_FAILURE"):
            loop._execute_multi_leg_if_admitted("PLAN_DURABLE_EXCEPTION")
    finally:
        allow_callback_to_raise.set()
        actor.join(timeout=5)

    assert not actor.is_alive()
    tripped = stop_switch.snapshot()
    assert tripped.status == "TRIPPED"
    assert tripped.persistence_confirmed is True
    assert tripped.reset_supported is False

    reopened_inputs = _inputs()
    reopened_switch = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=reopened_inputs[0],
        risk_engine=reopened_inputs[1],
        state_store=SqliteRuntimeStopSwitchStateStore(state_path),
    )
    reopened_admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(reopened_inputs[4]), reopened_switch,
    )
    reopened_loop = _loop(reopened_inputs[1], reopened_switch, reopened_admission)
    reopened_calls = []
    reopened_loop.multi_leg_executor = lambda plan: reopened_calls.append(plan)

    restored = reopened_switch.snapshot()
    admitted, result = reopened_loop._execute_multi_leg_if_admitted("PLAN_AFTER_REOPEN")

    assert restored.status == "TRIPPED"
    assert restored.persistence_confirmed is True
    assert restored.latch_confirmed is True
    assert restored.reset_supported is False
    assert admitted is False
    assert result is None
    assert reopened_calls == []
    assert reopened_switch.snapshot().status == "TRIPPED"


def test_t4_x2_tripped_allows_fill_reconciliation_but_skips_planning_and_actions(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)
    tick = SimpleNamespace(timestamp="2026-11-21T09:31:00+09:00")
    calls = []
    reconciled_fill = SimpleNamespace(
        strategy_id="SYNTHETIC_TRACK7",
        routed_legs=1,
        filled_legs=1,
        execution_ids=("SYNTHETIC:LATE-FILL:001",),
    )

    def observer(observed_tick):
        calls.append(("reconcile", observed_tick.timestamp))
        return (reconciled_fill,)

    def planner(_observed_tick):
        calls.append(("plan", None))

    def processor(_observed_tick):
        calls.append(("action", None))
        return (SimpleNamespace(strategy_id="SYNTHETIC_TRACK7"),)

    loop.pending_multi_leg_observer = observer
    loop.pending_multi_leg_planner = planner
    loop.pending_multi_leg_processor = processor

    stop_switch.trip("T4_SYNTHETIC_X2_RECONCILIATION_ONLY")

    reconciliation = loop._reconcile_pending_multi_leg(tick)
    loop._plan_pending_multi_leg_if_admitted(tick)
    actions = loop._process_pending_multi_leg_if_admitted(tick)

    assert reconciliation == (reconciled_fill,)
    assert actions == ()
    assert calls == [("reconcile", tick.timestamp)]
    assert stop_switch.snapshot().status == "TRIPPED"
    assert stop_switch.snapshot().order_admission_blocked is True

def test_t4_x2_latched_on_tick_runs_reconciliation_before_strategy_and_skips_lifecycle_actions(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    calls = []
    tick = SimpleNamespace(
        timestamp="2026-11-21T09:31:00+09:00",
        seq_id=1711,
        underlying_price=Decimal("350.25"),
        volume=1,
        ask_price=Decimal("350.25"),
    )
    reconciled_fill = SimpleNamespace(
        strategy_id="SYNTHETIC_TRACK7",
        routed_legs=1,
        filled_legs=1,
        reports=(SimpleNamespace(execution_id="SYNTHETIC:ON-TICK-LATE-FILL:001"),),
    )

    class _StrategyHub:
        def run(self, contexts):
            calls.append(("strategy", tuple(contexts)))
            return SimpleNamespace(failures=(), signals=())

    class _StrategyResults:
        def collect(self, *, tick_sequence, context, result):
            calls.append(("collect", tick_sequence))
            return ()

    class _StrategyDecision:
        def arbitrate(self, evaluations, **kwargs):
            calls.append(("arbitrate", len(evaluations)))
            return SimpleNamespace(
                arbitration=SimpleNamespace(approved_signals=(), rejected_signals=()),
                execution_plans=(),
                cancel_requests=(),
            )

    loop = _loop(inputs[1], stop_switch, admission)
    loop.bundle.account = SimpleNamespace(snapshot=lambda: None)
    loop.strategy_hub = _StrategyHub()
    loop.context_builder = lambda observed_tick, state: (
        calls.append(("context", observed_tick.seq_id)) or {}
    )
    loop.strategy_results = _StrategyResults()
    loop.strategy_to_decision = _StrategyDecision()
    loop.decision_to_command = SimpleNamespace(build_commands=lambda evaluations, approved: ())

    def observer(observed_tick):
        calls.append(("reconcile", observed_tick.seq_id))
        return (reconciled_fill,)

    def planner(_observed_tick):
        calls.append(("plan", None))

    def processor(_observed_tick):
        calls.append(("action", None))
        return ()

    loop.pending_multi_leg_observer = observer
    loop.pending_multi_leg_planner = planner
    loop.pending_multi_leg_processor = processor
    stop_switch.trip("T4_SYNTHETIC_X2_FULL_ON_TICK")

    result = loop.on_tick(tick)

    assert calls == [
        ("reconcile", tick.seq_id),
        ("context", tick.seq_id),
        ("strategy", ()),
        ("collect", tick.seq_id),
        ("arbitrate", 0),
    ]
    assert result.execution_ids == ("SYNTHETIC:ON-TICK-LATE-FILL:001",)
    assert result.routed == 1
    assert result.filled == 1
    assert stop_switch.snapshot().status == "TRIPPED"
    assert stop_switch.snapshot().order_admission_blocked is True

def test_t4_x2_latched_full_on_tick_skips_decision_cancel_side_effect(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    calls = []
    tick = SimpleNamespace(
        timestamp="2026-11-21T09:32:00+09:00",
        seq_id=1712,
        underlying_price=Decimal("350.25"),
        volume=1,
        ask_price=Decimal("350.25"),
    )

    class _StrategyHub:
        def run(self, contexts):
            calls.append(("strategy", tuple(contexts)))
            return SimpleNamespace(failures=(), signals=())

    class _StrategyResults:
        def collect(self, *, tick_sequence, context, result):
            calls.append(("collect", tick_sequence))
            return ()

    class _StrategyDecision:
        def arbitrate(self, evaluations, **kwargs):
            calls.append(("arbitrate", len(evaluations)))
            return SimpleNamespace(
                arbitration=SimpleNamespace(approved_signals=(), rejected_signals=()),
                execution_plans=(),
                cancel_requests=(
                    SimpleNamespace(
                        strategy_id="SYNTHETIC_TRACK7",
                        client_order_ids=("SYNTHETIC-CANCEL-ORDER-001",),
                    ),
                ),
            )

    loop = _loop(inputs[1], stop_switch, admission)
    loop.bundle.account = SimpleNamespace(snapshot=lambda: None)
    loop.strategy_hub = _StrategyHub()
    loop.context_builder = lambda observed_tick, state: (
        calls.append(("context", observed_tick.seq_id)) or {}
    )
    loop.strategy_results = _StrategyResults()
    loop.strategy_to_decision = _StrategyDecision()
    loop.decision_to_command = SimpleNamespace(build_commands=lambda evaluations, approved: ())
    loop.pending_multi_leg_observer = lambda observed_tick: ()
    loop.pending_multi_leg_planner = lambda observed_tick: calls.append(("plan", None))
    loop.pending_multi_leg_processor = lambda observed_tick: calls.append(("action", None)) or ()
    loop.broker_adapter = SimpleNamespace(
        cancel=lambda client_order_id: calls.append(("cancel", client_order_id))
    )
    stop_switch.trip("T4_SYNTHETIC_X2_CANCEL_GATE")

    result = loop.on_tick(tick)

    assert calls == [
        ("context", tick.seq_id),
        ("strategy", ()),
        ("collect", tick.seq_id),
        ("arbitrate", 0),
    ]
    assert result.rejected == 1
    assert stop_switch.snapshot().status == "TRIPPED"
    assert stop_switch.snapshot().order_admission_blocked is True

def test_t4_x2_latched_full_on_tick_denies_synthetic_single_leg_route(tmp_path):
    from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
    from shared.contracts.canonical import (
        CanonicalAssetType, CanonicalOrderCommand, CanonicalOrderSide,
    )

    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)
    instrument_id = "SYNTHETIC_CONTRACT:T4_X2_SINGLE_LEG"
    observed_at = NOW
    freshness = FreshnessVerdict(
        status=FreshnessStatus.FRESH,
        reason="T4_SYNTHETIC_SINGLE_LEG_ONLY",
        policy_version="T4-X2-SYNTHETIC-v1",
        source="DERIVED_SCENARIO_TEST_FIXTURE",
        tr_id="SYNTHETIC-TEST",
        environment="VIRTUAL_VALIDATION_ONLY",
        instrument_id=instrument_id,
        symbol=instrument_id,
        source_instant=observed_at,
        received_at=observed_at,
        evidence_sha256="e" * 64,
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(strategy_id="SYNTHETIC_TRACK1", freshness_verdict=freshness),
        runtime_context=SimpleNamespace(
            client_order_id=lambda _strategy_id: "SYNTHETIC-X2-SINGLE-ORDER-001",
        ),
        result=SimpleNamespace(kind="EXECUTION"),
    )
    command = CanonicalOrderCommand(
        client_order_id="SYNTHETIC-X2-SINGLE-ORDER-001",
        track_id="SYNTHETIC_TRACK1",
        asset_type=CanonicalAssetType.OPTION,
        side=CanonicalOrderSide.BUY,
        qty=1,
        price=1.25,
        option_type=None,
        strike=350.0,
        symbol=instrument_id,
        expiry="2026-11-26",
        tag_id="SYNTHETIC_ENTRY",
        strategy_id="SYNTHETIC_TRACK1",
        instrument_id=instrument_id,
    )

    class _StrategyHub:
        def run(self, _contexts):
            return SimpleNamespace(failures=(), signals=(object(),))

    class _Decision:
        def arbitrate(self, _evaluations, **_kwargs):
            return SimpleNamespace(
                arbitration=SimpleNamespace(approved_signals=(
                    SimpleNamespace(signal_id="SYNTHETIC-SIGNAL-001", track_id="SYNTHETIC_TRACK1"),
                ), rejected_signals=()),
                execution_plans=(),
                cancel_requests=(),
            )

    loop.bundle.account = SimpleNamespace(snapshot=lambda: SimpleNamespace(
        total_balance=1_000_000, realized_pnl=0, used_margin=0, free_margin=1_000_000,
    ))
    loop.bundle.position = SimpleNamespace(snapshot=lambda: {})
    loop.strategy_hub = _StrategyHub()
    loop.context_builder = lambda *_: {"SYNTHETIC_TRACK1": object()}
    loop.strategy_results = SimpleNamespace(collect=lambda **_kwargs: (evaluation,))
    loop.strategy_to_decision = _Decision()
    loop.decision_to_command = SimpleNamespace(build_commands=lambda _evaluations, _approved: (command,))
    loop.identity_provider = lambda *_args: SimpleNamespace(instrument_id=instrument_id)
    loop.pending_multi_leg_observer = lambda _tick: ()
    stop_switch.trip("T4_SYNTHETIC_X2_SINGLE_LEG_ROUTE_GATE")

    tick = SimpleNamespace(
        timestamp=observed_at.isoformat(), seq_id=1713,
        underlying_price=350.25, volume=1, ask_price=1.25,
    )
    result = loop.on_tick(tick)

    assert result.approved == 1
    assert result.routed == 0
    assert result.filled == 0
    assert result.rejected == 1
    assert loop.broker_adapter.last_report is None
    assert stop_switch.snapshot().status == "TRIPPED"
    assert stop_switch.snapshot().order_admission_blocked is True

def test_t4_x2_latched_full_on_tick_skips_multi_leg_executor(tmp_path):
    from core.strategy.execution_plan import ExecutionPlanKind

    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)
    calls = []
    multi_leg_plan = SimpleNamespace(plan_id="SYNTHETIC-T4-X2-MULTILEG-001")
    execution_plan = SimpleNamespace(
        kind=ExecutionPlanKind.MULTI_LEG,
        multi_leg_plan=multi_leg_plan,
        strategy_id="SYNTHETIC_TRACK1",
        signal_id="SYNTHETIC-MULTILEG-SIGNAL-001",
    )

    class _StrategyHub:
        def run(self, _contexts):
            return SimpleNamespace(failures=(), signals=(object(),))

    class _Decision:
        def arbitrate(self, _evaluations, **_kwargs):
            return SimpleNamespace(
                arbitration=SimpleNamespace(approved_signals=(
                    SimpleNamespace(
                        signal_id="SYNTHETIC-MULTILEG-SIGNAL-001",
                        track_id="SYNTHETIC_TRACK1",
                    ),
                ), rejected_signals=()),
                execution_plans=(execution_plan,),
                cancel_requests=(),
            )

    def execute_multi_leg(plan):
        calls.append(plan)
        return SimpleNamespace(routed_legs=2, filled_legs=2, group_complete=True)

    evaluation = SimpleNamespace(
        context=SimpleNamespace(strategy_id="SYNTHETIC_TRACK1"),
        runtime_context=SimpleNamespace(client_order_id=lambda _strategy_id: "SYNTHETIC-MULTILEG"),
        result=SimpleNamespace(kind="EXECUTION"),
    )
    loop.bundle.account = SimpleNamespace(snapshot=lambda: SimpleNamespace(
        total_balance=1_000_000, realized_pnl=0, used_margin=0, free_margin=1_000_000,
    ))
    loop.bundle.position = SimpleNamespace(snapshot=lambda: {})
    loop.strategy_hub = _StrategyHub()
    loop.context_builder = lambda *_: {"SYNTHETIC_TRACK1": object()}
    loop.strategy_results = SimpleNamespace(collect=lambda **_kwargs: (evaluation,))
    loop.strategy_to_decision = _Decision()
    loop.decision_to_command = SimpleNamespace(build_commands=lambda _evaluations, _approved: ())
    loop.multi_leg_executor = execute_multi_leg
    loop.pending_multi_leg_observer = lambda _tick: ()
    loop.pending_multi_leg_planner = lambda _tick: ()
    loop.pending_multi_leg_processor = lambda _tick: ()
    stop_switch.trip("T4_SYNTHETIC_X2_MULTILEG_FULL_ON_TICK")

    tick = SimpleNamespace(
        timestamp=NOW.isoformat(), seq_id=1714,
        underlying_price=350.25, volume=1, ask_price=1.25,
    )
    result = loop.on_tick(tick)

    assert result.approved == 1
    assert result.routed == 0
    assert result.filled == 0
    assert result.rejected == 1
    assert calls == []
    assert stop_switch.snapshot().status == "TRIPPED"
    assert stop_switch.snapshot().order_admission_blocked is True


def test_t4_x2_trip_inside_first_full_on_tick_multi_leg_blocks_next_plan(tmp_path):
    from core.strategy.execution_plan import ExecutionPlanKind

    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)
    calls = []
    execution_plans = tuple(
        SimpleNamespace(
            kind=ExecutionPlanKind.MULTI_LEG,
            multi_leg_plan=SimpleNamespace(plan_id=f"SYNTHETIC-T4-X2-MULTILEG-{index:03d}"),
            strategy_id="SYNTHETIC_TRACK1",
            signal_id=f"SYNTHETIC-MULTILEG-SIGNAL-{index:03d}",
        )
        for index in (1, 2)
    )
    approved_signals = tuple(
        SimpleNamespace(
            signal_id=f"SYNTHETIC-MULTILEG-SIGNAL-{index:03d}",
            track_id="SYNTHETIC_TRACK1",
        )
        for index in (1, 2)
    )

    class _StrategyHub:
        def run(self, _contexts):
            return SimpleNamespace(failures=(), signals=(object(), object()))

    class _Decision:
        def arbitrate(self, _evaluations, **_kwargs):
            return SimpleNamespace(
                arbitration=SimpleNamespace(
                    approved_signals=approved_signals, rejected_signals=(),
                ),
                execution_plans=execution_plans,
                cancel_requests=(),
            )

    def execute_multi_leg(plan):
        calls.append(plan.plan_id)
        if len(calls) == 1:
            stop_switch.trip("T4_SYNTHETIC_X2_TRIP_DURING_FIRST_MULTI_LEG")
        return SimpleNamespace(routed_legs=2, filled_legs=2, group_complete=True)

    evaluation = SimpleNamespace(
        context=SimpleNamespace(strategy_id="SYNTHETIC_TRACK1"),
        runtime_context=SimpleNamespace(
            client_order_id=lambda _strategy_id: "SYNTHETIC-MULTILEG",
        ),
        result=SimpleNamespace(kind="EXECUTION"),
    )
    loop.bundle.account = SimpleNamespace(snapshot=lambda: SimpleNamespace(
        total_balance=1_000_000, realized_pnl=0, used_margin=0, free_margin=1_000_000,
    ))
    loop.bundle.position = SimpleNamespace(snapshot=lambda: {})
    loop.strategy_hub = _StrategyHub()
    loop.context_builder = lambda *_: {"SYNTHETIC_TRACK1": object()}
    loop.strategy_results = SimpleNamespace(collect=lambda **_kwargs: (evaluation,))
    loop.strategy_to_decision = _Decision()
    loop.decision_to_command = SimpleNamespace(build_commands=lambda _evaluations, _approved: ())
    loop.multi_leg_executor = execute_multi_leg
    loop.pending_multi_leg_observer = lambda _tick: ()
    loop.pending_multi_leg_planner = lambda _tick: ()
    loop.pending_multi_leg_processor = lambda _tick: ()

    tick = SimpleNamespace(
        timestamp=NOW.isoformat(), seq_id=1715,
        underlying_price=350.25, volume=1, ask_price=1.25,
    )
    result = loop.on_tick(tick)

    assert result.approved == 2
    assert result.routed == 2
    assert result.filled == 2
    assert result.rejected == 1
    assert calls == ["SYNTHETIC-T4-X2-MULTILEG-001"]
    assert stop_switch.snapshot().status == "TRIPPED"
    assert stop_switch.snapshot().order_admission_blocked is True


def test_t4_x2_full_on_tick_multi_leg_exception_after_latch_blocks_next_tick(tmp_path):
    from core.strategy.execution_plan import ExecutionPlanKind

    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)
    calls = []
    execution_plans = tuple(
        SimpleNamespace(
            kind=ExecutionPlanKind.MULTI_LEG,
            multi_leg_plan=SimpleNamespace(plan_id=f"SYNTHETIC-T4-X2-EXCEPTION-{index:03d}"),
            strategy_id="SYNTHETIC_TRACK1",
            signal_id=f"SYNTHETIC-X2-EXCEPTION-SIGNAL-{index:03d}",
        )
        for index in (1, 2)
    )
    approved_signals = tuple(
        SimpleNamespace(
            signal_id=f"SYNTHETIC-X2-EXCEPTION-SIGNAL-{index:03d}",
            track_id="SYNTHETIC_TRACK1",
        )
        for index in (1, 2)
    )

    class _StrategyHub:
        def run(self, _contexts):
            return SimpleNamespace(failures=(), signals=(object(), object()))

    class _Decision:
        def arbitrate(self, _evaluations, **_kwargs):
            return SimpleNamespace(
                arbitration=SimpleNamespace(
                    approved_signals=approved_signals, rejected_signals=(),
                ),
                execution_plans=execution_plans,
                cancel_requests=(),
            )

    def execute_multi_leg(plan):
        calls.append(plan.plan_id)
        stop_switch.trip("T4_SYNTHETIC_X2_TRIP_BEFORE_MULTI_LEG_EXCEPTION")
        raise RuntimeError("SYNTHETIC_MULTI_LEG_EXECUTOR_FAILURE")

    evaluation = SimpleNamespace(
        context=SimpleNamespace(strategy_id="SYNTHETIC_TRACK1"),
        runtime_context=SimpleNamespace(
            client_order_id=lambda _strategy_id: "SYNTHETIC-MULTILEG-EXCEPTION",
        ),
        result=SimpleNamespace(kind="EXECUTION"),
    )
    loop.bundle.account = SimpleNamespace(snapshot=lambda: SimpleNamespace(
        total_balance=1_000_000, realized_pnl=0, used_margin=0, free_margin=1_000_000,
    ))
    loop.bundle.position = SimpleNamespace(snapshot=lambda: {})
    loop.strategy_hub = _StrategyHub()
    loop.context_builder = lambda *_: {"SYNTHETIC_TRACK1": object()}
    loop.strategy_results = SimpleNamespace(collect=lambda **_kwargs: (evaluation,))
    loop.strategy_to_decision = _Decision()
    loop.decision_to_command = SimpleNamespace(build_commands=lambda _evaluations, _approved: ())
    loop.multi_leg_executor = execute_multi_leg
    loop.pending_multi_leg_observer = lambda _tick: ()
    loop.pending_multi_leg_planner = lambda _tick: ()
    loop.pending_multi_leg_processor = lambda _tick: ()

    tick = SimpleNamespace(
        timestamp=NOW.isoformat(), seq_id=1716,
        underlying_price=350.25, volume=1, ask_price=1.25,
    )
    with pytest.raises(RuntimeError, match="SYNTHETIC_MULTI_LEG_EXECUTOR_FAILURE"):
        loop.on_tick(tick)

    assert calls == ["SYNTHETIC-T4-X2-EXCEPTION-001"]
    assert stop_switch.snapshot().status == "TRIPPED"
    assert stop_switch.snapshot().order_admission_blocked is True

    retry_tick = SimpleNamespace(
        timestamp=NOW.isoformat(), seq_id=1717,
        underlying_price=350.25, volume=1, ask_price=1.25,
    )
    retry_result = loop.on_tick(retry_tick)

    assert retry_result.approved == 2
    assert retry_result.routed == 0
    assert retry_result.filled == 0
    assert retry_result.rejected == 2
    assert calls == ["SYNTHETIC-T4-X2-EXCEPTION-001"]
    assert stop_switch.snapshot().status == "TRIPPED"



def test_t4_x2_partial_multi_leg_result_after_latch_blocks_next_plan(tmp_path):
    from core.strategy.execution_plan import ExecutionPlanKind

    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)
    calls = []
    execution_plans = tuple(
        SimpleNamespace(
            kind=ExecutionPlanKind.MULTI_LEG,
            multi_leg_plan=SimpleNamespace(
                plan_id=f"SYNTHETIC-T4-X2-PARTIAL-{index:03d}",
            ),
            strategy_id="SYNTHETIC_TRACK1",
            signal_id=f"SYNTHETIC-X2-PARTIAL-SIGNAL-{index:03d}",
        )
        for index in (1, 2)
    )
    approved_signals = tuple(
        SimpleNamespace(
            signal_id=f"SYNTHETIC-X2-PARTIAL-SIGNAL-{index:03d}",
            track_id="SYNTHETIC_TRACK1",
        )
        for index in (1, 2)
    )

    class _StrategyHub:
        def run(self, _contexts):
            return SimpleNamespace(failures=(), signals=(object(), object()))

    class _Decision:
        def arbitrate(self, _evaluations, **_kwargs):
            return SimpleNamespace(
                arbitration=SimpleNamespace(
                    approved_signals=approved_signals, rejected_signals=(),
                ),
                execution_plans=execution_plans,
                cancel_requests=(),
            )

    def execute_multi_leg(plan):
        calls.append(plan.plan_id)
        if len(calls) == 1:
            stop_switch.trip("T4_SYNTHETIC_X2_PARTIAL_MULTI_LEG")
            return SimpleNamespace(
                routed_legs=1,
                filled_legs=0,
                group_complete=False,
                pending_legs=0,
            )
        return SimpleNamespace(routed_legs=2, filled_legs=2, group_complete=True)

    evaluation = SimpleNamespace(
        context=SimpleNamespace(strategy_id="SYNTHETIC_TRACK1"),
        runtime_context=SimpleNamespace(
            client_order_id=lambda _strategy_id: "SYNTHETIC-MULTILEG-PARTIAL",
        ),
        result=SimpleNamespace(kind="EXECUTION"),
    )
    loop.bundle.account = SimpleNamespace(snapshot=lambda: SimpleNamespace(
        total_balance=1_000_000, realized_pnl=0, used_margin=0, free_margin=1_000_000,
    ))
    loop.bundle.position = SimpleNamespace(snapshot=lambda: {})
    loop.strategy_hub = _StrategyHub()
    loop.context_builder = lambda *_: {"SYNTHETIC_TRACK1": object()}
    loop.strategy_results = SimpleNamespace(collect=lambda **_kwargs: (evaluation,))
    loop.strategy_to_decision = _Decision()
    loop.decision_to_command = SimpleNamespace(build_commands=lambda _evaluations, _approved: ())
    loop.multi_leg_executor = execute_multi_leg
    loop.pending_multi_leg_observer = lambda _tick: ()
    loop.pending_multi_leg_planner = lambda _tick: ()
    loop.pending_multi_leg_processor = lambda _tick: ()

    tick = SimpleNamespace(
        timestamp=NOW.isoformat(), seq_id=1718,
        underlying_price=350.25, volume=1, ask_price=1.25,
    )
    result = loop.on_tick(tick)

    assert result.approved == 2
    assert result.routed == 1
    assert result.filled == 0
    assert result.rejected == 2
    assert calls == ["SYNTHETIC-T4-X2-PARTIAL-001"]
    assert stop_switch.snapshot().status == "TRIPPED"
    assert stop_switch.snapshot().order_admission_blocked is True


def test_t4_x2_pending_multi_leg_result_after_latch_preserves_pending_and_blocks_next_pla(tmp_path):
    from core.strategy.execution_plan import ExecutionPlanKind

    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)
    calls = []
    execution_plans = tuple(
        SimpleNamespace(
            kind=ExecutionPlanKind.MULTI_LEG,
            multi_leg_plan=SimpleNamespace(
                plan_id=f"SYNTHETIC-T4-X2-PENDING-{index:03d}",
            ),
            strategy_id="SYNTHETIC_TRACK1",
            signal_id=f"SYNTHETIC-X2-PENDING-SIGNAL-{index:03d}",
        )
        for index in (1, 2)
    )
    approved_signals = tuple(
        SimpleNamespace(
            signal_id=f"SYNTHETIC-X2-PENDING-SIGNAL-{index:03d}",
            track_id="SYNTHETIC_TRACK1",
        )
        for index in (1, 2)
    )

    class _StrategyHub:
        def run(self, _contexts):
            return SimpleNamespace(failures=(), signals=(object(), object()))

    class _Decision:
        def arbitrate(self, _evaluations, **_kwargs):
            return SimpleNamespace(
                arbitration=SimpleNamespace(
                    approved_signals=approved_signals, rejected_signals=(),
                ),
                execution_plans=execution_plans,
                cancel_requests=(),
            )

    def execute_multi_leg(plan):
        calls.append(plan.plan_id)
        if len(calls) == 1:
            stop_switch.trip("T4_SYNTHETIC_X2_PENDING_MULTI_LEG")
            return SimpleNamespace(
                routed_legs=1,
                filled_legs=0,
                group_complete=False,
                pending_legs=1,
            )
        return SimpleNamespace(routed_legs=2, filled_legs=2, group_complete=True)

    evaluation = SimpleNamespace(
        context=SimpleNamespace(strategy_id="SYNTHETIC_TRACK1"),
        runtime_context=SimpleNamespace(
            client_order_id=lambda _strategy_id: "SYNTHETIC-MULTILEG-PARTIAL",
        ),
        result=SimpleNamespace(kind="EXECUTION"),
    )
    loop.bundle.account = SimpleNamespace(snapshot=lambda: SimpleNamespace(
        total_balance=1_000_000, realized_pnl=0, used_margin=0, free_margin=1_000_000,
    ))
    loop.bundle.position = SimpleNamespace(snapshot=lambda: {})
    loop.strategy_hub = _StrategyHub()
    loop.context_builder = lambda *_: {"SYNTHETIC_TRACK1": object()}
    loop.strategy_results = SimpleNamespace(collect=lambda **_kwargs: (evaluation,))
    loop.strategy_to_decision = _Decision()
    loop.decision_to_command = SimpleNamespace(build_commands=lambda _evaluations, _approved: ())
    loop.multi_leg_executor = execute_multi_leg
    loop.pending_multi_leg_observer = lambda _tick: ()
    loop.pending_multi_leg_planner = lambda _tick: ()
    loop.pending_multi_leg_processor = lambda _tick: ()

    tick = SimpleNamespace(
        timestamp=NOW.isoformat(), seq_id=1718,
        underlying_price=350.25, volume=1, ask_price=1.25,
    )
    result = loop.on_tick(tick)

    assert result.approved == 2
    assert result.routed == 1
    assert result.filled == 0
    assert result.rejected == 1
    assert calls == ["SYNTHETIC-T4-X2-PENDING-001"]
    assert stop_switch.snapshot().status == "TRIPPED"
    assert stop_switch.snapshot().order_admission_blocked is True



def test_t4_x2_full_on_tick_pending_observer_exception_propagates_before_strategy(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)
    calls = []

    class _StrategyHub:
        def run(self, _contexts):
            calls.append("strategy")
            return SimpleNamespace(failures=(), signals=())

    def broken_observer(_tick):
        calls.append("observer")
        raise RuntimeError("SYNTHETIC_PENDING_OBSERVER_FAILURE")

    loop.runtime_evidence_supervisor = None
    loop.pending_multi_leg_observer = broken_observer
    loop.pending_multi_leg_planner = lambda _tick: calls.append("planner")
    loop.pending_multi_leg_processor = lambda _tick: calls.append("processor")
    loop.strategy_hub = _StrategyHub()

    tick = SimpleNamespace(
        timestamp=NOW.isoformat(), seq_id=1719,
        underlying_price=350.25, volume=1, ask_price=1.25,
    )

    with pytest.raises(
        RuntimeError, match="SYNTHETIC_PENDING_OBSERVER_FAILURE",
    ):
        loop.on_tick(tick)

    assert calls == ["observer"]
    assert stop_switch.snapshot().status == "ARMED"
    assert stop_switch.snapshot().order_admission_blocked is False



def test_t4_x2_pending_observer_generator_result_is_not_consumed(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)
    yielded = []

    def observer(_tick):
        def results():
            yielded.append("consumed")
            yield SimpleNamespace(execution_id="SYNTHETIC:GENERATOR-FILL")
        return results()

    loop.pending_multi_leg_observer = observer
    tick = SimpleNamespace(timestamp=NOW.isoformat(), seq_id=1720)

    result = loop._reconcile_pending_multi_leg(tick)

    assert result == ()
    assert yielded == []
    assert stop_switch.snapshot().status == "ARMED"


def test_t4_x2_full_on_tick_tuple_reconciliation_precedes_strategy_exception(tmp_path):
    inputs = _inputs()
    stop_switch = _switch(inputs, tmp_path)
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        _BaseStatusSource(inputs[4]), stop_switch,
    )
    loop = _loop(inputs[1], stop_switch, admission)
    calls = []
    reconciled_fill = SimpleNamespace(
        strategy_id="SYNTHETIC_TRACK7",
        routed_legs=1,
        filled_legs=1,
        reports=(SimpleNamespace(execution_id="SYNTHETIC:TUPLE-THEN-STRATEGY-ERROR:001"),),
    )

    class _StrategyHub:
        def run(self, _contexts):
            calls.append("strategy")
            raise RuntimeError("SYNTHETIC_STRATEGY_HUB_FAILURE")

    def observer(_tick):
        calls.append("observer")
        return (reconciled_fill,)

    loop.runtime_evidence_supervisor = None
    loop.pending_multi_leg_observer = observer
    loop.pending_multi_leg_planner = lambda _tick: calls.append("planner")
    loop.pending_multi_leg_processor = lambda _tick: calls.append("processor")
    loop.strategy_hub = _StrategyHub()
    loop.context_builder = lambda _tick, _state: (calls.append("context") or {})

    tick = SimpleNamespace(
        timestamp=NOW.isoformat(), seq_id=1721,
        underlying_price=350.25, volume=1, ask_price=1.25,
    )

    with pytest.raises(RuntimeError, match="SYNTHETIC_STRATEGY_HUB_FAILURE"):
        loop.on_tick(tick)

    assert calls == ["observer", "planner", "context", "strategy"]
    assert reconciled_fill.reports[0].execution_id == "SYNTHETIC:TUPLE-THEN-STRATEGY-ERROR:001"
    assert stop_switch.snapshot().status == "ARMED"
    assert stop_switch.snapshot().order_admission_blocked is False
