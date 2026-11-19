from datetime import UTC, datetime
from types import SimpleNamespace
import hashlib
import json

from application.composition.automated_virtual_trading_loop import (
    AutomatedVirtualTradingLoop,
)
from application.composition.validation_only_runtime_auto_stop_switch import (
    SqliteRuntimeStopSwitchStateStore,
    ValidationOnlyRuntimeAutoStopSwitch,
    ValidationOnlyRuntimeStopAdmissionSource,
)
from application.composition.validation_only_runtime_evidence_supervisor import (
    ValidationOnlyRuntimeEvidenceCandidate,
    ValidationOnlyRuntimeEvidenceSupervisor,
)
from contracts.trading_state import SensorLevel, SensorSnapshot, TradingHealthSnapshot
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionLedgerSnapshot,
    U19ExpectedGroupManifest,
    evaluate_u19_recovery,
)
from core.risk.risk_engine import RiskEngine
from core.risk.risk_guard import RiskGuard

NOW = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


class _Margin:
    def calculate_order_margin(self, command):
        return 1.0


class _Coordinator:
    def recover(self, *, group_id, broker_snapshot, ledger_snapshot, expected_group_manifest=None):
        return evaluate_u19_recovery(
            group_id=group_id,
            broker_snapshot=broker_snapshot,
            ledger_snapshot=ledger_snapshot,
            expected_group_manifest=expected_group_manifest,
            require_expected_group_manifest=True,
        )


class _Checker:
    def __init__(self, pass_report=True):
        self.pass_report = pass_report
        self.calls = 0

    def check(self, **kwargs):
        self.calls += 1
        assert "u19_decision" in kwargs
        return SimpleNamespace(
            status=(
                "VALIDATION_ONLY_RUNTIME_INVARIANTS_PASS"
                if self.pass_report else "RECONCILIATION_REQUIRED"
            ),
            issues=() if self.pass_report else ("SYNTHETIC_LINEAGE_NEEDS_RECONCILIATION",),
        )


def _evidence():
    broker = U19BrokerPositionSnapshot(
        "T5-GROUP", "T5-BROKER", NOW, "VALIDATION_ONLY:BROKER_EXCHANGE",
        (), True, True, "a" * 64,
    )
    ledger = U19ExecutionLedgerSnapshot(
        "T5-GROUP", "T5-LEDGER", NOW, "VALIDATION_ONLY:EXECUTION_LEDGER",
        (), True, "b" * 64, (), (),
    )
    manifest_payload = {
        "group_id": "T5-GROUP",
        "manifest_id": "T5-MANIFEST-001",
        "source": "VALIDATION_ONLY:EXPECTED_GROUP_MANIFEST",
        "provenance": "VALIDATION_ONLY:T5_TEST_FIXTURE",
        "leg_instrument_ids": ["SYNTHETIC_CONTRACT:T5:LEG1"],
        "expected_positions": [],
    }
    expected_manifest = U19ExpectedGroupManifest(
        group_id="T5-GROUP", manifest_id="T5-MANIFEST-001",
        source="VALIDATION_ONLY:EXPECTED_GROUP_MANIFEST",
        provenance="VALIDATION_ONLY:T5_TEST_FIXTURE",
        leg_instrument_ids=("SYNTHETIC_CONTRACT:T5:LEG1",), expected_positions=(),
        payload_sha256=hashlib.sha256(
            json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    )
    return ValidationOnlyRuntimeEvidenceCandidate(
        group_id="T5-GROUP",
        broker_snapshot=broker,
        ledger_snapshot=ledger,
        invariant_inputs={
            "order_commands": (),
            "executions": (),
            "ledger_evidence": {
                "expected_positions": (),
                "actual_open_position_lots": (),
                "vssf_positions": (),
                "fee_ledger_entries": (),
                "execution_reports": (),
            },
            "source_namespace": "SYNTHETIC:T5_VALIDATION",
            "deterministic_rule_id": "T5-RULE-001",
            "source_manifest_sha256": "c" * 64,
            "source_anchor_refs": ("accepted://runtime-v2/manifest.json",),
            "source_anchor_as_of": NOW,
            "scenario_timestamp": NOW,
            "evidence_refs": ("synthetic://t5/fixture-001",),
        },
        freshness_verdict=SimpleNamespace(status="FRESH"),
        expected_group_manifest=expected_manifest,
    )


def _supervisor(tmp_path, checker, providers):
    guard = RiskGuard()
    guard.reset()
    guard.evaluate(health=TradingHealthSnapshot.from_sensors((
        SensorSnapshot("T5", SensorLevel.GREEN, NOW, "HEALTHY"),
    )))
    engine = RiskEngine(margin_engine=_Margin())
    stop = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=guard,
        risk_engine=engine,
        state_store=SqliteRuntimeStopSwitchStateStore(tmp_path / "t5.sqlite3"),
    )
    return ValidationOnlyRuntimeEvidenceSupervisor(
        stop_switch=stop,
        invariant_checker=checker,
        u19_recovery_coordinator=_Coordinator(),
        risk_guard_status_source=SimpleNamespace(snapshot=guard.snapshot),
        **providers,
    ), stop


def test_t5_reconciles_primary_mismatch_before_using_alternative(tmp_path):
    calls = []
    candidate = _evidence()
    supervisor, stop = _supervisor(
        tmp_path,
        _Checker(pass_report=True),
        {
            "primary_provider": lambda _tick: calls.append("primary") or None,
            "reconciliation_provider": lambda _tick, _attempts: calls.append("reconcile") or candidate,
            "alternative_provider": lambda _tick, _attempts: calls.append("alternative") or candidate,
        },
    )

    result = supervisor.evaluate(SimpleNamespace(timestamp=NOW.isoformat()))

    assert calls == ["primary", "reconcile"]
    assert result.candidate_source == "NOTION_AND_SOURCE_RECONCILIATION"
    assert result.stop_snapshot.status == "ARMED"
    assert stop.snapshot().status == "ARMED"


def test_t5_uses_synthetic_alternative_only_after_reconciliation_attempt(tmp_path):
    calls = []
    candidate = _evidence()
    supervisor, stop = _supervisor(
        tmp_path,
        _Checker(pass_report=True),
        {
            "primary_provider": lambda _tick: calls.append("primary") or None,
            "reconciliation_provider": lambda _tick, _attempts: calls.append("reconcile") or None,
            "alternative_provider": lambda _tick, _attempts: calls.append("alternative") or candidate,
        },
    )

    result = supervisor.evaluate(SimpleNamespace(timestamp=NOW.isoformat()))

    assert calls == ["primary", "reconcile", "alternative"]
    assert result.candidate_source == "PROVENANCE_PRESERVING_ALTERNATIVE"
    assert result.stop_snapshot.status == "ARMED"
    assert stop.snapshot().status == "ARMED"


def test_t5_does_not_trip_until_all_evidence_paths_are_exhausted(tmp_path):
    calls = []
    supervisor, stop = _supervisor(
        tmp_path,
        _Checker(pass_report=False),
        {
            "primary_provider": lambda _tick: calls.append("primary") or _evidence(),
            "reconciliation_provider": lambda _tick, _attempts: calls.append("reconcile") or _evidence(),
            "alternative_provider": lambda _tick, _attempts: calls.append("alternative") or _evidence(),
        },
    )

    result = supervisor.evaluate(SimpleNamespace(timestamp=NOW.isoformat()))

    assert calls == ["primary", "reconcile", "alternative"]
    assert result.candidate_source is None
    assert result.stop_snapshot.status == "TRIPPED"
    assert any(reason.startswith("MANUAL_STOP:T5_EVIDENCE_RECONCILIATION_EXHAUSTED") for reason in result.stop_snapshot.reasons)
    assert stop.snapshot().status == "TRIPPED"




def test_t5_supervisor_is_invoked_once_at_the_start_of_each_virtual_tick(tmp_path):
    guard = RiskGuard()
    guard.reset()
    guard.evaluate(health=TradingHealthSnapshot.from_sensors((
        SensorSnapshot("T5_TICK", SensorLevel.GREEN, NOW, "HEALTHY"),
    )))
    engine = RiskEngine(margin_engine=_Margin())
    stop_switch = ValidationOnlyRuntimeAutoStopSwitch(
        risk_guard=guard,
        risk_engine=engine,
        state_store=SqliteRuntimeStopSwitchStateStore(tmp_path / "t5-loop.sqlite3"),
    )
    admission = ValidationOnlyRuntimeStopAdmissionSource(
        SimpleNamespace(snapshot=guard.snapshot), stop_switch,
    )
    owner = SimpleNamespace(vssf_runtime=SimpleNamespace(margin_engine=_Margin()))
    class _Execution:
        def __init__(self):
            self.__self__ = owner
        def __call__(self):
            return None
    bundle = SimpleNamespace(
        execution=SimpleNamespace(_authoritative_execute=_Execution()),
        broker=object(),
    )
    loop = AutomatedVirtualTradingLoop(
        bundle=bundle,
        strategy_hub=object(),
        run_id="T5-TICK",
        context_builder=lambda *_: {},
        identity_provider=lambda *_: None,
        risk_engine=engine,
        risk_guard_status_source=admission,
        runtime_stop_switch=stop_switch,
        signal_observation_only=True,
    )
    calls = []

    class _Supervisor:
        def evaluate(self, tick):
            calls.append(tick.seq_id)
            return SimpleNamespace(stop_snapshot=stop_switch.snapshot())

    class _Strategies:
        def run(self, _contexts):
            return SimpleNamespace(failures=(), signals=())

    loop.runtime_evidence_supervisor = _Supervisor()
    loop.strategy_hub = _Strategies()
    loop.strategy_results.collect = lambda **_kwargs: ()
    tick = SimpleNamespace(
        timestamp=NOW.isoformat(), seq_id=7, underlying_price=100,
        volume=1, ask_price=1, symbol="SYNTHETIC:T5",
    )

    loop.on_tick(tick)

    assert calls == [7]
    assert loop.last_runtime_evidence_supervision.stop_snapshot.status == "ARMED"
