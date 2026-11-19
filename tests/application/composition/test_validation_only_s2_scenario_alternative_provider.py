from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from application.composition.validation_only_runtime_invariant_checker import (
    ValidationOnlyRuntimeInvariantChecker,
)
from application.composition.validation_only_s2_scenario_alternative_provider import (
    ValidationOnlyS2ScenarioAlternativeProvider,
)
from application.composition.validation_only_vssf_runtime_evidence_adapter import (
    ValidationOnlyVSSFRuntimeEvidenceAdapter,
)
from core.oms.track2_u19_recovery import U19RecoveryStatus, evaluate_u19_recovery

ROOT = Path(__file__).resolve().parents[3]
RUN_ID = "SYNTHETIC:T7:S2-CANDIDATE-001"


def _runtime_fixture(provider_timestamp: str):
    scenario_time = datetime.fromisoformat(provider_timestamp)
    candidate_path = (
        ROOT / "data" / "derived_scenario"
        / "q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
        / "four_leg_quotes.jsonl"
    )
    rows = [
        __import__("json").loads(line)
        for line in candidate_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = [row for row in rows if row["candidate_id"] == "S2-CANDIDATE-001"]
    reports = []
    lots = []
    fees = []
    provenance = {}
    execution_legs = {}
    positions = {}
    for row in rows:
        role = row["leg_role"]
        side = (
            "BUY" if role in {"inner_put", "inner_call"} else "SELL"
        )
        instrument_id = row["instrument_id"]
        execution_id = f"SYNTHETIC:T7:EXEC:{role}"
        client_order_id = f"SYNTHETIC:T7:ORDER:{role}"
        price = Decimal(str(row["ask"] if side == "BUY" else row["bid"]))
        multiplier = Decimal(str(row["contract_multiplier"]))
        fee = Decimal(1000)
        report = SimpleNamespace(
            client_order_id=client_order_id,
            broker_order_id=f"SYNTHETIC:T7:BROKER:{role}",
            execution_id=execution_id,
            status="FILLED",
            filled_quantity=1,
            remaining_quantity=0,
            execution_price=price,
            execution_timestamp=scenario_time,
            fee=fee,
            group_id="SYNTHETIC:T7:GROUP",
            leg_id=role,
        )
        reports.append(report)
        provenance[execution_id] = {
            "group_id": report.group_id,
            "leg_id": role,
            "instrument_id": instrument_id,
            "symbol": instrument_id,
        }
        execution_legs[execution_id] = {
            "side": side,
            "contract_multiplier": multiplier,
            "asset_type": "OPTION",
        }
        lots.append(SimpleNamespace(
            run_id=RUN_ID,
            instrument_id=instrument_id,
            execution_id=execution_id,
            side=side,
            opened_quantity=1,
            remaining_quantity=1,
            execution_timestamp=scenario_time,
            contract_multiplier=multiplier,
        ))
        fees.append(SimpleNamespace(
            execution_id=execution_id,
            fee_amount=fee,
            executed_quantity=1,
            executed_price=price,
        ))
        positions[instrument_id] = {
            "side": side,
            "qty": 1,
            "avg_price": price,
            "mark_price": price,
        }
    bridge = SimpleNamespace(
        run_id=RUN_ID,
        groups={"SYNTHETIC:T7:GROUP": tuple(reports)},
        provenance=provenance,
        execution_legs=execution_legs,
        pending_legs={},
        position_lot_store=SimpleNamespace(
            history=lambda: tuple(lots),
            open_lots=lambda: tuple(lots),
            close_events=lambda: (),
        ),
        fee_ledger=SimpleNamespace(snapshot=lambda *, run_id: tuple(fees)),
    )
    runtime = SimpleNamespace(
        account=SimpleNamespace(
            positions=positions,
            realized_pnl=Decimal(0),
            unrealized_pnl=Decimal(0),
        )
    )
    return bridge, runtime


def _provider(tick_timestamp: str):
    bridge, runtime = _runtime_fixture(tick_timestamp)
    adapter = ValidationOnlyVSSFRuntimeEvidenceAdapter(
        bridge=bridge, vssf_runtime=runtime, run_id=RUN_ID,
    )
    return ValidationOnlyS2ScenarioAlternativeProvider(
        project_root=ROOT,
        run_id=RUN_ID,
        vssf_adapter=adapter,
    )


def test_t7_s2_alternative_builds_independent_broker_snapshot_and_freshness_candidate():
    tick = SimpleNamespace(
        candidate_id="S2-CANDIDATE-001",
        timestamp="2026-10-12T09:26:00+09:00",
    )
    candidate = _provider(tick.timestamp)(tick, ())

    assert candidate is not None
    assert candidate.broker_snapshot.source == "VALIDATION_ONLY:BROKER_EXCHANGE"
    assert candidate.ledger_snapshot.source == "VALIDATION_ONLY:EXECUTION_LEDGER"
    assert candidate.freshness_verdict.status.value == "FRESH"
    assert len(candidate.broker_snapshot.positions) == 4
    assert len(candidate.ledger_snapshot.execution_events) == 4
    assert candidate.broker_snapshot.positions == candidate.ledger_snapshot.positions

    decision = evaluate_u19_recovery(
        group_id=candidate.group_id,
        broker_snapshot=candidate.broker_snapshot,
        ledger_snapshot=candidate.ledger_snapshot,
    )
    assert decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    invariant_inputs = dict(candidate.invariant_inputs)
    invariant_inputs["u19_decision"] = decision
    result = ValidationOnlyRuntimeInvariantChecker().check(**invariant_inputs)
    assert result.status == ValidationOnlyRuntimeInvariantChecker.PASS
    assert result.issues == ()


def test_t7_s2_alternative_returns_none_for_unrelated_tick():
    tick = SimpleNamespace(
        candidate_id="OTHER-CANDIDATE",
        timestamp="2026-10-12T09:26:00+09:00",
    )

    assert _provider(tick.timestamp)(tick, ()) is None


def test_t7_s2_alternative_does_not_claim_fresh_after_five_second_synthetic_age():
    tick = SimpleNamespace(
        candidate_id="S2-CANDIDATE-001",
        timestamp="2026-10-12T09:26:06+09:00",
    )
    candidate = _provider(tick.timestamp)(tick, ())

    assert candidate.freshness_verdict.status.value == "STALE"
    assert candidate.freshness_verdict.reason == "SOURCE_AGE_EXCEEDS_APPROVED_THRESHOLD"


def test_t7_s2_alternative_rejects_tick_before_scenario_time():
    tick = SimpleNamespace(
        candidate_id="S2-CANDIDATE-001",
        timestamp="2026-10-12T09:25:59+09:00",
    )

    import pytest

    with pytest.raises(ValueError, match="T7_TICK_PRECEDES_SYNTHETIC_SCENARIO"):
        _provider(tick.timestamp)(tick, ())

def test_t7_s2_alternative_runs_after_primary_and_reconciliation_are_unavailable():
    from application.composition.validation_only_runtime_evidence_supervisor import (
        ValidationOnlyRuntimeEvidenceSupervisor,
    )

    tick = SimpleNamespace(
        candidate_id="S2-CANDIDATE-001",
        timestamp="2026-10-12T09:26:00+09:00",
    )
    provider = _provider(tick.timestamp)

    class _StopSwitch:
        def __init__(self):
            self.calls = []

        def evaluate(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(status="ARMED")

    class _Recovery:
        def recover(self, *, group_id, broker_snapshot, ledger_snapshot):
            return evaluate_u19_recovery(
                group_id=group_id,
                broker_snapshot=broker_snapshot,
                ledger_snapshot=ledger_snapshot,
            )

    stop_switch = _StopSwitch()
    supervisor = ValidationOnlyRuntimeEvidenceSupervisor(
        stop_switch=stop_switch,
        invariant_checker=ValidationOnlyRuntimeInvariantChecker(),
        u19_recovery_coordinator=_Recovery(),
        risk_guard_status_source=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(
                admission_allowed=True,
                kill_switch_engaged=False,
                reason="HEALTHY",
            )
        ),
        primary_provider=lambda _tick: None,
        reconciliation_provider=lambda _tick, _attempts: None,
        alternative_provider=provider,
    )

    result = supervisor.evaluate(tick)

    assert result.candidate_source == "PROVENANCE_PRESERVING_ALTERNATIVE"
    assert result.attempts == (
        "PRIMARY_ACCEPTED_ORIGINAL:EVIDENCE_UNAVAILABLE",
        "NOTION_AND_SOURCE_RECONCILIATION:EVIDENCE_UNAVAILABLE",
        "PROVENANCE_PRESERVING_ALTERNATIVE:VALIDATED",
    )
    assert result.u19_decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert result.invariant_report.status == ValidationOnlyRuntimeInvariantChecker.PASS
    assert result.stop_snapshot.status == "ARMED"
    assert len(stop_switch.calls) == 1
