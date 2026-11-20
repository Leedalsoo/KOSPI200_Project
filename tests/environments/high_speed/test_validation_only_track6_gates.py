from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime

import pytest

from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
from core.risk.option_hedge_risk_config import DEFAULT_CONFIG_PATH
from core.strategy.contracts import SignalKind
from core.strategy.track6_daily_tail_insurance import (
    Track6DailyTailInsurance, Track6LifecyclePersistenceError,
)
from environments.high_speed.validation_only_track6_gates import (
    apply_track6_validation_gates,
    load_track6_validation_gate_evidence,
)


def test_track6_validation_gate_reads_disabled_operational_limits() -> None:
    evidence = load_track6_validation_gate_evidence()

    assert evidence.config_schema_version == "1.0.0"
    assert len(evidence.config_sha256) == 64
    assert evidence.strategy_max_gross_premium_outlay_krw == 250_000
    assert evidence.strategy_max_loss_krw == 250_000
    assert evidence.strategy_max_concurrent_positions == 1
    assert evidence.max_quote_age_seconds == 5


def test_track6_validation_gate_applies_only_for_synthetic_source() -> None:
    strategy = Track6DailyTailInsurance()
    source = SimpleNamespace(source_name="SYNTHETIC:validation-test")

    evidence = apply_track6_validation_gates(
        strategy,
        validation_only_synthetic=True,
        synthetic_runtime_sources=source,
    )

    assert evidence.config_sha256
    assert strategy.runtime_config_verified is True
    assert strategy.risk_limits_available is True


def test_track6_validation_gate_rejects_non_synthetic_context() -> None:
    strategy = Track6DailyTailInsurance()
    with pytest.raises(ValueError, match="TRACK6_VALIDATION_ONLY_SYNTHETIC_MODE_REQUIRED"):
        apply_track6_validation_gates(
            strategy,
            validation_only_synthetic=False,
            synthetic_runtime_sources=SimpleNamespace(source_name="SYNTHETIC:test"),
        )
    assert strategy.runtime_config_verified is False
    assert strategy.risk_limits_available is False


def test_track6_validation_gate_rejects_operationally_enforced_config(tmp_path: Path) -> None:
    config = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    config["activation_mode"] = "ENFORCED"
    path = tmp_path / "risk.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="TRACK6_VALIDATION_REQUIRES_OPERATIONAL_RISK_CONFIG_DISABLED"):
        load_track6_validation_gate_evidence(path)


def test_signal_observation_mode_never_invokes_decision_or_execution() -> None:
    loop = AutomatedVirtualTradingLoop.__new__(AutomatedVirtualTradingLoop)
    loop.signal_observation_only = True
    loop.pending_multi_leg_processor = lambda: pytest.fail("pending execution must be skipped")
    loop.context_builder = lambda tick, state: {
        "track6_daily_tail_insurance": SimpleNamespace(strategy_id="track6_daily_tail_insurance")
    }
    signal = SimpleNamespace(strategy_id="track6_daily_tail_insurance")
    loop.strategy_hub = SimpleNamespace(
        run=lambda contexts: SimpleNamespace(signals=(signal,), failures=())
    )
    evaluation = SimpleNamespace(
        context=SimpleNamespace(strategy_id="track6_daily_tail_insurance"),
        result=SimpleNamespace(kind=SignalKind.EXECUTION),
    )
    loop.strategy_results = SimpleNamespace(collect=lambda **kwargs: (evaluation,))

    result = loop.on_tick(SimpleNamespace(
        timestamp=datetime(2026, 11, 2, 10, 0).isoformat(),
        underlying_price=500,
        volume=1,
        seq_id=1,
    ))

    assert result.signals == 1
    assert result.approved == result.routed == result.filled == result.rejected == 0
    assert result.execution_ids == ()


def test_track6_lifecycle_persistence_failure_trips_runtime_stop_before_signal_collection():
    loop = AutomatedVirtualTradingLoop.__new__(AutomatedVirtualTradingLoop)
    loop.signal_observation_only = True
    loop.pending_multi_leg_processor = None
    loop.runtime_evidence_supervisor = None
    loop.context_builder = lambda tick, state: {
        "track6_daily_tail_insurance": SimpleNamespace(strategy_id="track6_daily_tail_insurance")
    }
    calls = []

    class _StopSwitch:
        def trip(self, reason):
            calls.append(("trip", reason))

    loop.runtime_stop_switch = _StopSwitch()
    loop.strategy_hub = SimpleNamespace(run=lambda _contexts: SimpleNamespace(
        signals=(),
        failures=(SimpleNamespace(
            strategy_id="track6_daily_tail_insurance",
            error_type="Track6LifecyclePersistenceError",
            stage="on_market_state",
            message="TRACK6_LIFECYCLE_STATE_PERSISTENCE_FAILED",
        ),),
    ))
    loop.strategy_results = SimpleNamespace(collect=lambda **_kwargs: calls.append(("collect", None)) or ())

    result = loop.on_tick(SimpleNamespace(
        timestamp=datetime(2026, 11, 21, 10, 0).isoformat(),
        underlying_price=500, volume=1, seq_id=99,
    ))

    assert calls[0] == ("trip", "X2_TRACK6_LIFECYCLE_STATE_PERSISTENCE_FAILED")
    assert calls[1] == ("collect", None)
    assert result.approved == result.routed == result.filled == 0


def test_track6_lifecycle_wraps_state_store_oserror_as_critical_persistence_failure():
    from core.strategy.track6_daily_tail_insurance import Track6LifecyclePersistenceError

    strategy = Track6DailyTailInsurance()
    strategy.lifecycle = SimpleNamespace(export_snapshot=lambda: {"run_id": "SYNTHETIC-TRACK6"})

    class _BrokenStore:
        def append(self, _snapshot):
            raise OSError("simulated state-store fsync failure")

    strategy.lifecycle_state_store = _BrokenStore()
    with pytest.raises(Track6LifecyclePersistenceError, match="TRACK6_LIFECYCLE_STATE_PERSISTENCE_FAILED") as error:
        strategy._persist_lifecycle()
    assert isinstance(error.value.__cause__, OSError)


def test_track6_lifecycle_recovery_failure_is_wrapped_and_preserves_cause():
    from core.strategy.track6_daily_tail_insurance import Track6LifecycleRecoveryError
    from core.strategy.track6_order_lifecycle import Track6LifecycleConfig

    strategy = Track6DailyTailInsurance(
        lifecycle_config=Track6LifecycleConfig(),
        lifecycle_state_store=SimpleNamespace(load_latest=lambda: (_ for _ in ()).throw(OSError("synthetic store read failure"))),
        lifecycle_run_id="SYNTHETIC-TRACK6-RECOVERY",
    )
    with pytest.raises(Track6LifecycleRecoveryError, match="TRACK6_LIFECYCLE_STATE_RECOVERY_FAILED") as error:
        strategy._ensure_lifecycle("20261121")
    assert isinstance(error.value.__cause__, OSError)


def test_track6_lifecycle_recovery_failure_trips_runtime_stop_before_signal_collection():
    loop = AutomatedVirtualTradingLoop.__new__(AutomatedVirtualTradingLoop)
    loop.signal_observation_only = True
    loop.pending_multi_leg_processor = None
    loop.runtime_evidence_supervisor = None
    loop.context_builder = lambda tick, state: {
        "track6_daily_tail_insurance": SimpleNamespace(strategy_id="track6_daily_tail_insurance")
    }
    calls = []

    class _StopSwitch:
        def trip(self, reason):
            calls.append(("trip", reason))

    loop.runtime_stop_switch = _StopSwitch()
    loop.strategy_hub = SimpleNamespace(run=lambda _contexts: SimpleNamespace(
        signals=(),
        failures=(SimpleNamespace(
            strategy_id="track6_daily_tail_insurance",
            error_type="Track6LifecycleRecoveryError",
            stage="initialize",
            message="TRACK6_LIFECYCLE_STATE_RECOVERY_FAILED",
        ),),
    ))
    loop.strategy_results = SimpleNamespace(collect=lambda **_kwargs: calls.append(("collect", None)) or ())
    result = loop.on_tick(SimpleNamespace(
        timestamp=datetime(2026, 11, 21, 10, 1).isoformat(),
        underlying_price=500, volume=1, seq_id=100,
    ))
    assert calls[0] == ("trip", "X2_TRACK6_LIFECYCLE_STATE_RECOVERY_FAILED")
    assert calls[1] == ("collect", None)
    assert result.approved == result.routed == result.filled == 0


def test_track6_torn_state_stream_is_wrapped_as_recovery_failure(tmp_path):
    from core.strategy.track6_order_lifecycle import Track6LifecycleConfig
    from core.strategy.track6_daily_tail_insurance import Track6LifecycleRecoveryError
    from environments.high_speed.track6_validation_state_store import Track6ValidationStateStore

    store = Track6ValidationStateStore(tmp_path, run_id="SYNTHETIC-TRACK6-TORN-RECOVERY")
    store.append({
        "run_id": "SYNTHETIC-TRACK6-TORN-RECOVERY",
        "trading_date": "20261121",
        "status": "FLAT_CONFIRMED",
        "open_quantity": {"put": 0, "call": 0},
        "working_client_order_id": None,
    })
    with store.path.open("ab") as stream:
        stream.write(b'{"partial":')
        stream.flush()

    strategy = Track6DailyTailInsurance(
        lifecycle_config=Track6LifecycleConfig(),
        lifecycle_state_store=store,
        lifecycle_run_id="SYNTHETIC-TRACK6-TORN-RECOVERY",
    )
    with pytest.raises(Track6LifecycleRecoveryError, match="TRACK6_LIFECYCLE_STATE_RECOVERY_FAILED") as error:
        strategy._ensure_lifecycle("20261121")
    assert error.value.__cause__ is not None


def test_track6_writer_lock_contention_propagates_as_runtime_critical_persistence_error(tmp_path):
    from core.strategy.track6_daily_tail_insurance import Track6LifecyclePersistenceError
    from environments.high_speed.track6_validation_state_store import (
        Track6ValidationStateStore, Track6ValidationStateStoreError,
    )

    run_id = "SYNTHETIC-TRACK6-RUNTIME-WRITER-CONTENTION"
    store = Track6ValidationStateStore(tmp_path, run_id=run_id)
    strategy = Track6DailyTailInsurance(lifecycle_state_store=store)
    strategy.lifecycle = SimpleNamespace(export_snapshot=lambda: {"run_id": run_id})
    competing_handle = store._acquire_writer_lock()
    try:
        with pytest.raises(Track6LifecyclePersistenceError, match="TRACK6_LIFECYCLE_STATE_PERSISTENCE_FAILED") as error:
            strategy._persist_lifecycle()
        assert isinstance(error.value.__cause__, Track6ValidationStateStoreError)
        assert "WRITER_LOCKED" in str(error.value.__cause__)
        assert not store.path.exists()
    finally:
        competing_handle.close()


class _StopAfterArbitration(Exception):
    pass


def _ordering_probe_loop(trace, *, blocked=False, strategy_failures=(), planner=None, processor=None):
    loop = AutomatedVirtualTradingLoop.__new__(AutomatedVirtualTradingLoop)
    state = {"reconciled": False, "blocked": blocked}
    loop.signal_observation_only = False
    loop.runtime_evidence_supervisor = None

    def observe(_tick):
        trace.append("reconcile_pending_fills")
        state["reconciled"] = True
        return ()

    def build_context(_tick, _market_state):
        assert state["reconciled"] is True
        trace.append("build_strategy_context")
        return {"synthetic_strategy": SimpleNamespace(strategy_id="synthetic_strategy")}

    def run_strategies(_contexts):
        trace.append("strategy_hub")
        return SimpleNamespace(signals=(), failures=strategy_failures)

    def trip(reason):
        trace.append(("x2_trip", reason))
        state["blocked"] = True

    def collect(**_kwargs):
        trace.append("signal_collection")
        return ()

    def arbitrate(*_args, **_kwargs):
        trace.append("arbitration")
        raise _StopAfterArbitration

    loop.pending_multi_leg_observer = observe
    loop.pending_multi_leg_planner = planner
    loop.pending_multi_leg_processor = processor
    loop.context_builder = build_context
    loop.strategy_hub = SimpleNamespace(run=run_strategies)
    loop.strategy_results = SimpleNamespace(collect=collect)
    loop._runtime_orders_blocked = lambda: state["blocked"]
    loop._trip_runtime_stop = trip
    loop.strategy_to_decision = SimpleNamespace(arbitrate=arbitrate)
    loop.bundle = SimpleNamespace(account=SimpleNamespace(snapshot=lambda: None))
    loop.identity_provider = lambda _item: None
    loop.multi_leg_plan_resolver = None
    loop.fsm = SimpleNamespace(pending_client_order_ids=())
    return loop


def _ordering_probe_tick():
    return SimpleNamespace(
        timestamp=datetime(2026, 11, 21, 10, 2).isoformat(),
        underlying_price=500, volume=1, seq_id=902, ask_price=500,
    )


def test_pending_fill_reconciliation_precedes_strategy_and_side_effects_follow_strategy():
    trace = []
    loop = _ordering_probe_loop(
        trace,
        planner=lambda _tick: trace.append("plan_lifecycle_actions"),
        processor=lambda _tick: trace.append("pending_side_effects") or (),
    )

    with pytest.raises(_StopAfterArbitration):
        loop.on_tick(_ordering_probe_tick())

    assert trace == [
        "reconcile_pending_fills",
        "plan_lifecycle_actions",
        "build_strategy_context",
        "strategy_hub",
        "pending_side_effects",
        "signal_collection",
        "arbitration",
    ]


def test_track6_failure_latches_x2_before_pending_side_effect_callback():
    trace = []
    failure = SimpleNamespace(
        strategy_id="track6_daily_tail_insurance",
        error_type="Track6LifecyclePersistenceError",
        stage="on_market_state",
        message="SYNTHETIC_PERSISTENCE_FAILURE",
    )
    loop = _ordering_probe_loop(
        trace,
        strategy_failures=(failure,),
        planner=lambda _tick: trace.append("plan_lifecycle_actions"),
        processor=lambda _tick: trace.append("FORBIDDEN_PENDING_SIDE_EFFECT") or (),
    )

    with pytest.raises(_StopAfterArbitration):
        loop.on_tick(_ordering_probe_tick())

    assert trace == [
        "reconcile_pending_fills",
        "plan_lifecycle_actions",
        "build_strategy_context",
        "strategy_hub",
        ("x2_trip", "X2_TRACK6_LIFECYCLE_STATE_PERSISTENCE_FAILED"),
        "signal_collection",
        "arbitration",
    ]


def test_latched_x2_still_allows_pending_fill_reconciliation_but_not_side_effects():
    trace = []
    loop = _ordering_probe_loop(
        trace,
        blocked=True,
        planner=lambda _tick: trace.append("FORBIDDEN_LIFECYCLE_PLANNING"),
        processor=lambda _tick: trace.append("FORBIDDEN_PENDING_SIDE_EFFECT") or (),
    )

    with pytest.raises(_StopAfterArbitration):
        loop.on_tick(_ordering_probe_tick())

    assert trace == [
        "reconcile_pending_fills",
        "build_strategy_context",
        "strategy_hub",
        "signal_collection",
        "arbitration",
    ]


def test_track6_clock_persistence_error_in_deferred_processor_trips_x2_before_collection():
    trace = []

    def processor(_tick):
        trace.append("pending_processor")
        raise Track6LifecyclePersistenceError("SYNTHETIC_CLOCK_PERSISTENCE_FAILURE")

    loop = _ordering_probe_loop(
        trace, planner=lambda _tick: trace.append("plan_lifecycle_actions"),
        processor=processor,
    )

    with pytest.raises(_StopAfterArbitration):
        loop.on_tick(_ordering_probe_tick())

    assert trace == [
        "reconcile_pending_fills",
        "plan_lifecycle_actions",
        "build_strategy_context",
        "strategy_hub",
        "pending_processor",
        ("x2_trip", "X2_TRACK6_LIFECYCLE_STATE_PERSISTENCE_FAILED"),
        "signal_collection",
        "arbitration",
    ]



def test_track6_lifecycle_planning_persistence_error_trips_x2_before_strategy_and_cancel():
    trace = []

    def planner(_tick):
        trace.append("lifecycle_planner")
        raise Track6LifecyclePersistenceError("SYNTHETIC_CLOCK_PERSISTENCE_FAILURE")

    loop = _ordering_probe_loop(
        trace,
        planner=planner,
        processor=lambda _tick: trace.append("FORBIDDEN_CANCEL_OR_RETRY") or (),
    )

    with pytest.raises(_StopAfterArbitration):
        loop.on_tick(_ordering_probe_tick())

    assert trace == [
        "reconcile_pending_fills",
        "lifecycle_planner",
        ("x2_trip", "X2_TRACK6_LIFECYCLE_STATE_PERSISTENCE_FAILED"),
        "build_strategy_context",
        "strategy_hub",
        "signal_collection",
        "arbitration",
    ]
