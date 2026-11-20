
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from application.composition.validation_only_runtime_auto_stop_switch import (
    SqliteRuntimeStopSwitchStateStore,
    ValidationOnlyRuntimeAutoStopSwitch,
)
from application.composition.validation_only_s2_source_evidence_providers import (
    build_validation_only_s2_runtime_evidence_chain,
)
from contracts.trading_state import SensorLevel
from core.risk.risk_guard import RiskGuard
from tests.application.composition.test_validation_only_s2_source_evidence_providers import (
    DECISIONS,
    ROOT,
    TICK,
    _pre_entry_alternative,
)

ORIGINAL_ROOT = ROOT.parent / "KOSPI200_Project" / "data" / "kis_market_data_restart"


class _RiskEngine:
    def __init__(self):
        self.active = False
        self.reasons = []

    def is_kill_switch_active(self):
        return self.active

    def trigger_kill_switch(self, reason):
        self.active = True
        self.reasons.append(reason)


def _risk_guard_source():
    return SimpleNamespace(
        snapshot=lambda: SimpleNamespace(
            observed_at=datetime.now(UTC),
            health_level=SensorLevel.GREEN,
            admission_allowed=True,
            kill_switch_engaged=False,
            reason="HEALTHY",
            decision_version="T11_SYNTHETIC_TEST",
        )
    )


def _chain(run_id, tmp_path):
    alternative = _pre_entry_alternative(run_id)
    stop = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=RiskGuard(),
        risk_engine=_RiskEngine(),
        state_store=SqliteRuntimeStopSwitchStateStore(tmp_path / "x2.sqlite3"),
    )
    chain = build_validation_only_s2_runtime_evidence_chain(
        project_root=ROOT,
        original_source_root=ORIGINAL_ROOT,
        run_id=run_id,
        bridge=alternative.vssf_adapter.bridge,
        vssf_runtime=alternative.vssf_adapter.vssf_runtime,
        stop_switch=stop,
        risk_guard_status_source=_risk_guard_source(),
        u19_state_store_path=tmp_path / "u19.sqlite3",
        notion_decision_refs=DECISIONS,
        scenario_source_roots=(ROOT.parent / "Q25_A8_R10",),
    )
    return chain, stop


@pytest.mark.skipif(not ORIGINAL_ROOT.is_dir(), reason="original KIS source inventory is not mounted")
def test_t11_freshness_expiry_trips_durable_x2_and_new_run_recovers_without_reset(tmp_path):
    run_id = "SYNTHETIC:T11:FRESHNESS-LATCH"
    chain, stop = _chain(run_id, tmp_path / "old-run")

    fresh = chain.supervisor.evaluate(TICK)
    assert fresh.stop_snapshot.status == "ARMED"
    assert fresh.u19_decision.order_submission_enabled is False

    stale_tick = SimpleNamespace(
        timestamp="2026-10-12T09:26:06+09:00",
        underlying_price=1034.62,
        candidate_id="S2-CANDIDATE-001",
    )
    stale = chain.supervisor.evaluate(stale_tick)

    assert stale.stop_snapshot.status == "TRIPPED"
    assert any("FRESHNESS_NOT_FRESH:STALE" in item for item in stale.attempts)
    assert "MARKET_DATA_FRESHNESS_NOT_FRESH:STALE" in stale.stop_snapshot.reasons
    assert stale.stop_snapshot.persistence_confirmed is True
    assert stale.stop_snapshot.latch_confirmed is True
    assert stale.stop_snapshot.reset_supported is False
    assert stale.stop_snapshot.cancel_orders_requested is False
    assert stale.stop_snapshot.flatten_positions_requested is False
    assert stale.stop_snapshot.runtime_stop_requested is False
    assert not hasattr(stop, "reset")

    reopened = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=RiskGuard(),
        risk_engine=_RiskEngine(),
        state_store=SqliteRuntimeStopSwitchStateStore(
            tmp_path / "old-run" / "x2.sqlite3"
        ),
    )
    reopened_snapshot = reopened.snapshot()
    assert reopened_snapshot.status == "TRIPPED"
    assert reopened_snapshot.persistence_confirmed is True
    assert reopened_snapshot.latch_confirmed is True
    assert reopened_snapshot.reset_supported is False

    recovered_chain, recovered_stop = _chain(
        "SYNTHETIC:T11:FRESH-RECOVERY",
        tmp_path / "new-run",
    )
    recovered = recovered_chain.supervisor.evaluate(TICK)

    assert recovered.stop_snapshot.status == "ARMED"
    assert recovered.u19_decision.status.value == "FLAT_CONFIRMED"
    assert recovered.u19_decision.new_entry_enabled is False
    assert recovered.u19_decision.order_submission_enabled is False
    assert recovered.invariant_report.status == "VALIDATION_ONLY_RUNTIME_INVARIANTS_PASS"
    assert recovered_stop.snapshot().status == "ARMED"
    assert reopened.snapshot().status == "TRIPPED"




def _scoped_tick(timestamp, underlying_price=1034.62):
    return SimpleNamespace(
        timestamp=timestamp,
        underlying_price=underlying_price,
        candidate_id="S2-CANDIDATE-001",
    )


@pytest.mark.skipif(not ORIGINAL_ROOT.is_dir(), reason="original KIS source inventory is not mounted")
def test_t12_exact_five_second_boundary_is_fresh_and_duplicate_tick_is_idempotent(tmp_path):
    chain, stop = _chain("SYNTHETIC:T12:BOUNDARY", tmp_path)

    first = chain.supervisor.evaluate(_scoped_tick("2026-10-12T09:26:00+09:00"))
    duplicate = chain.supervisor.evaluate(_scoped_tick("2026-10-12T09:26:00+09:00"))
    boundary = chain.supervisor.evaluate(_scoped_tick("2026-10-12T09:26:05+09:00"))

    assert first.stop_snapshot.status == "ARMED"
    assert duplicate.stop_snapshot.status == "ARMED"
    assert duplicate.attempts[-1] == "PROVENANCE_PRESERVING_ALTERNATIVE:VALIDATED"
    assert boundary.stop_snapshot.status == "ARMED"
    assert boundary.attempts[-1] == "PROVENANCE_PRESERVING_ALTERNATIVE:VALIDATED"
    assert stop.snapshot().persistence_confirmed is True


@pytest.mark.skipif(not ORIGINAL_ROOT.is_dir(), reason="original KIS source inventory is not mounted")
def test_t12_underlying_anchor_mismatch_and_time_reversal_trip_x2(tmp_path):
    chain, stop = _chain("SYNTHETIC:T12:INVALID-TICK", tmp_path)

    mismatch = chain.supervisor.evaluate(
        _scoped_tick("2026-10-12T09:26:00+09:00", underlying_price=1034.70)
    )
    assert mismatch.stop_snapshot.status == "TRIPPED"
    assert any("T7_TICK_UNDERLYING_ANCHOR_MISMATCH" in item for item in mismatch.attempts)

    reverse_chain, reverse_stop = _chain(
        "SYNTHETIC:T12:TIME-REVERSAL",
        tmp_path / "reverse",
    )
    reversed_result = reverse_chain.supervisor.evaluate(
        _scoped_tick("2026-10-12T09:25:59+09:00")
    )
    assert reversed_result.stop_snapshot.status == "TRIPPED"
    assert any("T7_TICK_PRECEDES_SYNTHETIC_SCENARIO" in item for item in reversed_result.attempts)
    assert stop.snapshot().cancel_orders_requested is False
    assert reverse_stop.snapshot().runtime_stop_requested is False


@pytest.mark.skipif(not ORIGINAL_ROOT.is_dir(), reason="original KIS source inventory is not mounted")
def test_t12_repeated_stale_tick_keeps_x2_tripped_without_duplicate_side_effects(tmp_path):
    chain, stop = _chain("SYNTHETIC:T12:REPEATED-STALE", tmp_path)
    stale_tick = _scoped_tick("2026-10-12T09:26:06+09:00")

    first = chain.supervisor.evaluate(stale_tick)
    first_snapshot = stop.snapshot()
    second = chain.supervisor.evaluate(stale_tick)
    second_snapshot = stop.snapshot()

    assert first.stop_snapshot.status == "TRIPPED"
    assert second.stop_snapshot.status == "TRIPPED"
    assert "MARKET_DATA_FRESHNESS_NOT_FRESH:STALE" in second_snapshot.reasons
    assert second_snapshot.reasons == first_snapshot.reasons
    assert second_snapshot.persistence_confirmed is True
    assert second_snapshot.latch_confirmed is True
    assert second_snapshot.cancel_orders_requested is False
    assert second_snapshot.flatten_positions_requested is False
    assert second_snapshot.runtime_stop_requested is False
