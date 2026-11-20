from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace

import pytest

from application.composition.validation_only_runtime_evidence_supervisor import (
    ValidationOnlyRuntimeEvidenceCandidate,
)
from application.composition.validation_only_runtime_invariant_checker import (
    ValidationOnlyRuntimeInvariantChecker,
)
from application.composition.validation_only_vssf_runtime_evidence_adapter import (
    ValidationOnlyVSSFRuntimeEvidenceAdapter,
)
from contracts.market_data_freshness import FreshnessStatus
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExpectedGroupManifest,
    U19Position,
    U19RecoveryStatus,
    evaluate_u19_recovery,
)

AS_OF = datetime(2026, 10, 12, 1, 0, 2, tzinfo=UTC)
MANIFEST_SHA = "1" * 64
SCOPE = "VALIDATION_ONLY:RUN:RUN-T6:CANDIDATE:S2-CANDIDATE-001"


def _fixture(*, account_qty=1, broker_qty=1, include_provenance=True):
    lot = SimpleNamespace(
        run_id="RUN-T6",
        group_id=SCOPE,
        instrument_id="SYNTHETIC_CONTRACT:T6:OPT1",
        execution_id="SYNTHETIC:T6:EXEC-1",
        side="BUY",
        opened_quantity=1,
        remaining_quantity=1,
        execution_timestamp=AS_OF.replace(second=0),
        contract_multiplier=Decimal(10),
    )
    report = SimpleNamespace(
        client_order_id="SYNTHETIC:T6:ORDER-1",
        broker_order_id="SYNTHETIC:T6:BROKER-1",
        execution_id="SYNTHETIC:T6:EXEC-1",
        status="FILLED",
        filled_quantity=1,
        remaining_quantity=0,
        execution_price=Decimal(100),
        execution_timestamp=AS_OF.replace(second=0),
        fee=Decimal(0),
        group_id=SCOPE,
        leg_id="LEG-1",
    )
    bridge = SimpleNamespace(
        run_id="RUN-T6",
        groups={SCOPE: (report,)},
        provenance=(
            {
                report.execution_id: {
                    "group_id": report.group_id,
                    "leg_id": "LEG-1",
                    "instrument_id": lot.instrument_id,
                    "symbol": "SYNTHETIC:T6:SYMBOL-1",
                }
            } if include_provenance else {}
        ),
        execution_legs={
            report.execution_id: {
                "side": "BUY",
                "contract_multiplier": Decimal(10),
            }
        },
        pending_legs={},
        position_lot_store=SimpleNamespace(
            history=lambda: (lot,),
            open_lots=lambda: (lot,) if account_qty else (),
            close_events=lambda: (),
        ),
        fee_ledger=SimpleNamespace(
            snapshot=lambda *, run_id: (
                SimpleNamespace(
                    execution_id=report.execution_id,
                    group_id=SCOPE,
                    fee_amount=Decimal(0),
                    executed_quantity=1,
                    executed_price=Decimal(100),
                ),
            )
        ),
    )
    vssf = SimpleNamespace(
        validation_candidate_id="S2-CANDIDATE-001",
        account=SimpleNamespace(
            positions=(
                {
                    "SYNTHETIC:T6:SYMBOL-1": {
                        "side": "BUY",
                        "qty": account_qty,
                        "avg_price": Decimal(100),
                        "mark_price": Decimal(105),
                    }
                } if account_qty else {}
            ),
            realized_pnl=Decimal(0),
            unrealized_pnl=Decimal(50) if account_qty else Decimal(0),
        )
    )
    broker_positions = (
        (U19Position(lot.instrument_id, Decimal(broker_qty)),)
        if broker_qty else ()
    )
    broker = U19BrokerPositionSnapshot(
        group_id=SCOPE,
        snapshot_id="SYNTHETIC:T6:BROKER-SNAPSHOT",
        as_of=AS_OF,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=broker_positions,
        complete=True,
        capability_verified=True,
        payload_sha256="2" * 64,
    )
    adapter = ValidationOnlyVSSFRuntimeEvidenceAdapter(
        bridge=bridge, vssf_runtime=vssf, run_id="RUN-T6",
    )
    return adapter, broker, report, lot, bridge, vssf


def _expected_manifest(broker):
    leg_ids = ("SYNTHETIC_CONTRACT:T6:OPT1",)
    positions = tuple(broker.positions)
    payload = {
        "group_id": SCOPE,
        "manifest_id": "SYNTHETIC:T6:EXPECTED-001",
        "source": "VALIDATION_ONLY:EXPECTED_GROUP_MANIFEST",
        "provenance": "VALIDATION_ONLY:T6_TEST_FIXTURE",
        "leg_instrument_ids": list(leg_ids),
        "expected_positions": [
            {"instrument_id": item.instrument_id, "signed_quantity": str(item.signed_quantity)}
            for item in sorted(positions, key=lambda item: item.instrument_id)
        ],
    }
    return U19ExpectedGroupManifest(
        group_id=SCOPE, manifest_id="SYNTHETIC:T6:EXPECTED-001",
        source="VALIDATION_ONLY:EXPECTED_GROUP_MANIFEST",
        provenance="VALIDATION_ONLY:T6_TEST_FIXTURE", leg_instrument_ids=leg_ids,
        expected_positions=positions,
        payload_sha256=hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    )


def _build(adapter, broker):
    return adapter.build_candidate(
        as_of=AS_OF,
        broker_snapshot=broker,
        expected_group_manifest=_expected_manifest(broker),
        freshness_verdict=SimpleNamespace(status=FreshnessStatus.FRESH),
        source_namespace="SYNTHETIC:Q25_A8_T6_VSSF_RUNTIME",
        deterministic_rule_id="Q25_A8_T6_VSSF_READONLY_RULE_V1",
        source_manifest_sha256=MANIFEST_SHA,
        source_anchor_refs=("data/derived_scenario/manifest.json",),
        source_anchor_as_of=AS_OF.replace(second=0),
        scenario_timestamp=AS_OF.replace(second=1),
        evidence_refs=(
            "data/accepted_market_data/runtime_v2/manifest.json",
            "data/derived_scenario/four_leg_quotes.jsonl",
        ),
    )


def test_t6_vssf_adapter_builds_candidate_from_read_only_runtime_ledgers():
    adapter, broker, report, lot, _bridge, _vssf = _fixture()

    candidate = _build(adapter, broker)

    assert isinstance(candidate, ValidationOnlyRuntimeEvidenceCandidate)
    assert candidate.group_id == SCOPE
    assert candidate.ledger_snapshot.source == "VALIDATION_ONLY:EXECUTION_LEDGER"
    assert candidate.ledger_snapshot.positions == (U19Position(lot.instrument_id, Decimal(1)),)
    assert candidate.ledger_snapshot.pending_order_ids == ()
    assert candidate.invariant_inputs["order_commands"][0]["quantity"] == 1
    assert candidate.invariant_inputs["executions"][0]["execution_id"] == report.execution_id

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
    assert result.manifest["read_only"] is True


def test_t6_vssf_adapter_preserves_broker_mismatch_for_u19_reconciliation():
    adapter, _broker, _report, lot, _bridge, _vssf = _fixture()
    mismatch = U19BrokerPositionSnapshot(
        group_id=SCOPE,
        snapshot_id="SYNTHETIC:T6:BROKER-MISMATCH",
        as_of=AS_OF,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=(U19Position(lot.instrument_id, Decimal(2)),),
        complete=True,
        capability_verified=True,
        payload_sha256="3" * 64,
    )

    candidate = _build(adapter, mismatch)
    decision = evaluate_u19_recovery(
        group_id=candidate.group_id,
        broker_snapshot=candidate.broker_snapshot,
        ledger_snapshot=candidate.ledger_snapshot,
    )

    assert decision.status is U19RecoveryStatus.POSITION_LEDGER_MISMATCH
    assert decision.restore_allowed is False
    assert decision.new_entry_enabled is False
    assert decision.order_submission_enabled is False


def test_t6_vssf_adapter_does_not_guess_missing_execution_provenance():
    adapter, broker, _report, _lot, _bridge, _vssf = _fixture(include_provenance=False)

    with pytest.raises(TypeError, match="T6_VSSF_EXECUTION_PROVENANCE_MISSING"):
        _build(adapter, broker)


def test_t6_vssf_adapter_requires_synthetic_source_and_no_future_anchor():
    adapter, broker, _report, _lot, _bridge, _vssf = _fixture()

    with pytest.raises(ValueError, match="T6_VALIDATION_SYNTHETIC_NAMESPACE_REQUIRED"):
        adapter.build_candidate(
            as_of=AS_OF,
            broker_snapshot=broker,
            expected_group_manifest=_expected_manifest(broker),
            freshness_verdict=SimpleNamespace(status=FreshnessStatus.FRESH),
            source_namespace="KIS:LIVE",
            deterministic_rule_id="RULE",
            source_manifest_sha256=MANIFEST_SHA,
            source_anchor_refs=("anchor",),
            source_anchor_as_of=AS_OF,
            scenario_timestamp=AS_OF,
            evidence_refs=("evidence",),
        )

    with pytest.raises(ValueError, match="T6_SOURCE_SCENARIO_TIME_ORDER_INVALID"):
        adapter.build_candidate(
            as_of=AS_OF,
            broker_snapshot=broker,
            expected_group_manifest=_expected_manifest(broker),
            freshness_verdict=SimpleNamespace(status=FreshnessStatus.FRESH),
            source_namespace="SYNTHETIC:T6",
            deterministic_rule_id="RULE",
            source_manifest_sha256=MANIFEST_SHA,
            source_anchor_refs=("anchor",),
            source_anchor_as_of=AS_OF,
            scenario_timestamp=AS_OF.replace(second=3),
            evidence_refs=("evidence",),
        )


def test_adapter_scopes_same_run_candidates_to_distinct_group_ids():
    adapter, _broker, _report, _lot, bridge, vssf = _fixture()
    second = ValidationOnlyVSSFRuntimeEvidenceAdapter(
        bridge=bridge,
        vssf_runtime=vssf,
        run_id="RUN-T6",
        candidate_id="S2-CANDIDATE-002",
    )

    assert adapter.scope_group_id == SCOPE
    assert second.scope_group_id == "VALIDATION_ONLY:RUN:RUN-T6:CANDIDATE:S2-CANDIDATE-002"
    assert adapter.scope_group_id != second.scope_group_id


def test_t6_adapter_excludes_other_candidate_reports_lots_and_fees():
    adapter, broker, report_a, lot_a, bridge, vssf = _fixture()
    group_b = "VALIDATION_ONLY:RUN:RUN-T6:CANDIDATE:S2-CANDIDATE-002"
    report_b = SimpleNamespace(
        client_order_id="SYNTHETIC:T6:ORDER-B", broker_order_id="SYNTHETIC:T6:BROKER-B",
        execution_id="SYNTHETIC:T6:EXEC-B", status="FILLED", filled_quantity=1,
        remaining_quantity=0, execution_price=Decimal(200), execution_timestamp=AS_OF,
        fee=Decimal("0.25"), group_id=group_b, leg_id="LEG-B",
    )
    lot_b = SimpleNamespace(
        run_id="RUN-T6", group_id=group_b, instrument_id="SYNTHETIC_CONTRACT:T6:OPT-B",
        execution_id=report_b.execution_id, side="BUY", opened_quantity=1,
        remaining_quantity=1, execution_timestamp=AS_OF, contract_multiplier=Decimal(10),
    )
    bridge.groups[group_b] = (report_b,)
    bridge.provenance[report_b.execution_id] = {
        "group_id": group_b, "leg_id": "LEG-B", "instrument_id": lot_b.instrument_id,
        "symbol": "SYNTHETIC:T6:SYMBOL-B",
    }
    bridge.execution_legs[report_b.execution_id] = {"side": "BUY", "contract_multiplier": Decimal(10)}
    bridge.position_lot_store.history = lambda: (lot_a, lot_b)
    bridge.position_lot_store.open_lots = lambda: (lot_a, lot_b)
    fee_a = SimpleNamespace(execution_id=report_a.execution_id, group_id=SCOPE, fee_amount=Decimal(0), executed_quantity=1, executed_price=Decimal(100))
    fee_b = SimpleNamespace(execution_id=report_b.execution_id, group_id=group_b, fee_amount=Decimal("0.25"), executed_quantity=1, executed_price=Decimal(200))
    bridge.fee_ledger.snapshot = lambda *, run_id: (fee_a, fee_b)

    candidate = _build(adapter, broker)
    evidence = candidate.invariant_inputs["ledger_evidence"]
    assert [row["execution_id"] for row in candidate.invariant_inputs["executions"]] == [report_a.execution_id]
    assert [row.execution_id for row in evidence["actual_position_lot_history"]] == [lot_a.execution_id]
    assert [row.execution_id for row in evidence["actual_open_position_lots"]] == [lot_a.execution_id]
    assert [row.execution_id for row in evidence["actual_fee_records"]] == [report_a.execution_id]


def test_t6_adapter_rejects_report_group_tampering_inside_candidate_bucket():
    adapter, broker, report, _lot, bridge, _vssf = _fixture()
    report.group_id = "VALIDATION_ONLY:RUN:RUN-T6:CANDIDATE:S2-CANDIDATE-002"
    with pytest.raises(ValueError, match="T6_VSSF_REPORT_GROUP_SCOPE_MISMATCH"):
        _build(adapter, broker)


def test_t6_adapter_rejects_cross_candidate_close_event_lineage():
    adapter, broker, _report_a, lot_a, bridge, _vssf = _fixture()
    group_b = "VALIDATION_ONLY:RUN:RUN-T6:CANDIDATE:S2-CANDIDATE-002"
    report_b = SimpleNamespace(
        client_order_id="ORDER-B", execution_id="EXEC-B", group_id=group_b,
        status="FILLED", filled_quantity=1, remaining_quantity=0,
    )
    bridge.groups[group_b] = (report_b,)
    bridge.position_lot_store.close_events = lambda: (
        SimpleNamespace(execution_id="EXEC-B", source_lot_execution_id=lot_a.execution_id,
                        quantity=1, execution_timestamp=AS_OF),
    )
    with pytest.raises(ValueError, match="T6_VSSF_CROSS_GROUP_POSITION_LOT_CLOSE"):
        _build(adapter, broker)


def test_t6_adapter_requires_explicit_candidate_scoped_vssf_account_for_multi_candidate_bridge():
    adapter, broker, _report, _lot, bridge, vssf = _fixture()
    group_b = "VALIDATION_ONLY:RUN:RUN-T6:CANDIDATE:S2-CANDIDATE-002"
    bridge.groups[group_b] = ()
    del vssf.validation_candidate_id
    with pytest.raises(ValueError, match="T6_VSSF_RUNTIME_CANDIDATE_SCOPE_REQUIRED"):
        _build(adapter, broker)
