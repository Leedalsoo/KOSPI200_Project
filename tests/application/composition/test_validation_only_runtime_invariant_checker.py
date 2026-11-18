import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from application.composition.validation_only_runtime_invariant_checker import (
    ValidationOnlyRuntimeInvariantChecker,
)
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionEvent,
    U19ExecutionLedgerSnapshot,
    U19Position,
    U19RecoveryStatus,
    evaluate_u19_recovery,
)

BASE = datetime(2026, 11, 19, 9, 0, tzinfo=timezone(timedelta(hours=9)))
GROUP = "X1-GROUP-001"
MULTIPLIER = "250000"
MANIFEST_HASH = hashlib.sha256(b"x1-manifest").hexdigest()


def _digest(payload):
    import json
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _evidence(*, pending=(), broker_positions=(), ledger_positions=(), u19_status=None):
    executions = [
        {"execution_id": "X1-EXEC-BUY", "client_order_id": "X1-ORDER-BUY", "broker_order_id": "X1-BROKER-BUY", "group_id": GROUP, "leg_id": "LEG-1", "instrument_id": "SYNTHETIC_CONTRACT:X1", "side": "BUY", "quantity": 1, "price": "10", "contract_multiplier": MULTIPLIER, "executed_at": BASE},
        {"execution_id": "X1-EXEC-SELL", "client_order_id": "X1-ORDER-SELL", "broker_order_id": "X1-BROKER-SELL", "group_id": GROUP, "leg_id": "LEG-1", "instrument_id": "SYNTHETIC_CONTRACT:X1", "side": "SELL", "quantity": 1, "price": "11", "contract_multiplier": MULTIPLIER, "executed_at": BASE + timedelta(seconds=1)},
    ]
    orders = [
        {"client_order_id": "X1-ORDER-BUY", "broker_order_id": "X1-BROKER-BUY", "group_id": GROUP, "leg_id": "LEG-1", "instrument_id": "SYNTHETIC_CONTRACT:X1", "side": "BUY", "quantity": 1, "filled_quantity": 1, "status": "FILLED"},
        {"client_order_id": "X1-ORDER-SELL", "broker_order_id": "X1-BROKER-SELL", "group_id": GROUP, "leg_id": "LEG-1", "instrument_id": "SYNTHETIC_CONTRACT:X1", "side": "SELL", "quantity": 1, "filled_quantity": 1, "status": "FILLED"},
    ]
    fee_records = [
        {"execution_id": row["execution_id"], "fee_amount": "0", "executed_quantity": 1, "executed_price": row["price"]}
        for row in executions
    ]
    ledger = {
        "opening_lots": (), "executions": executions,
        "expected_fee_records": [
            {"execution_id": row["execution_id"], "fee_amount": "0", "quantity": 1, "price": row["price"]}
            for row in executions
        ],
        "actual_position_lot_history": ({"execution_id": "X1-EXEC-BUY", "side": "BUY", "opened_quantity": 1, "contract_multiplier": MULTIPLIER},),
        "actual_open_position_lots": (),
        "actual_close_events": ({"execution_id": "X1-EXEC-SELL", "source_lot_execution_id": "X1-EXEC-BUY", "quantity": 1, "execution_timestamp": BASE + timedelta(seconds=1)},),
        "actual_fee_records": fee_records,
        "vssf_positions": {}, "vssf_realized_pnl_delta": "250000", "vssf_unrealized_pnl": "0",
        "mark_prices": {}, "source_namespace": "SYNTHETIC:X1_TEST",
        "deterministic_rule_id": "X1-DETERMINISTIC-ROUNDTRIP-v1",
        "source_manifest_sha256": MANIFEST_HASH,
        "source_anchor_refs": ("ACCEPTED_RUNTIME_V2:X1",),
        "source_anchor_as_of": BASE, "scenario_timestamp": BASE + timedelta(seconds=2),
        "evidence_refs": ("TEST:X1:BRIDGE", "TEST:X1:VSSF", "TEST:X1:U19"),
    }
    events = tuple(U19ExecutionEvent(row["execution_id"], _digest(row)) for row in executions)
    as_of = BASE + timedelta(seconds=3)
    broker = U19BrokerPositionSnapshot(
        GROUP, "X1-BROKER-SNAPSHOT", as_of, "VALIDATION_ONLY:BROKER_EXCHANGE",
        tuple(broker_positions), True, True, _digest({"broker": "x1"}),
    )
    ledger_snapshot = U19ExecutionLedgerSnapshot(
        GROUP, "X1-LEDGER-SNAPSHOT", as_of, "VALIDATION_ONLY:EXECUTION_LEDGER",
        tuple(ledger_positions), True, _digest({"ledger": "x1"}), events, tuple(pending),
    )
    decision = evaluate_u19_recovery(group_id=GROUP, broker_snapshot=broker, ledger_snapshot=ledger_snapshot)
    if u19_status is not None and decision.status is not u19_status:
        decision = replace(decision, status=u19_status)
    return {"orders": orders, "executions": executions, "ledger": ledger, "decision": decision}


def _check(evidence):
    return ValidationOnlyRuntimeInvariantChecker().check(
        order_commands=evidence["orders"], executions=evidence["executions"],
        ledger_evidence=evidence["ledger"], u19_decision=evidence["decision"],
        source_namespace="SYNTHETIC:X1_TEST", deterministic_rule_id="X1-DETERMINISTIC-ROUNDTRIP-v1",
        source_manifest_sha256=MANIFEST_HASH, source_anchor_refs=("ACCEPTED_RUNTIME_V2:X1",),
        source_anchor_as_of=BASE, scenario_timestamp=BASE + timedelta(seconds=2),
        evidence_refs=("TEST:X1:BRIDGE", "TEST:X1:VSSF", "TEST:X1:U19"),
    )


def test_x1_checker_passes_flat_roundtrip_across_orders_lots_vssf_and_u19():
    report = _check(_evidence())
    assert report.status == ValidationOnlyRuntimeInvariantChecker.PASS
    assert report.issues == ()
    assert set(report.checks.values()) == {"PASS"}
    assert report.manifest["unique_execution_count"] == 2
    assert report.manifest["u19_status"] == U19RecoveryStatus.FLAT_CONFIRMED.value
    assert report.manifest_sha256 and len(report.manifest_sha256) == 64


def test_x1_checker_detects_order_fill_overrun():
    evidence = _evidence()
    evidence["executions"][0]["quantity"] = 2
    report = _check(evidence)
    assert report.status == ValidationOnlyRuntimeInvariantChecker.RECONCILIATION_REQUIRED
    assert "RUNTIME_INVARIANT_ORDER_OVERFILLED:X1-ORDER-BUY" in report.issues


def test_x1_checker_detects_execution_order_lineage_mismatch():
    evidence = _evidence()
    evidence["executions"][0]["leg_id"] = "WRONG-LEG"
    report = _check(evidence)
    assert "RUNTIME_INVARIANT_EXECUTION_LEG_ID_MISMATCH:X1-EXEC-BUY" in report.issues


def test_x1_checker_detects_duplicate_execution_id_without_silent_deduplication():
    evidence = _evidence()
    evidence["executions"].append(dict(evidence["executions"][0]))
    report = _check(evidence)
    assert "RUNTIME_INVARIANT_EXECUTION_ID_DUPLICATE" in report.issues


def test_x1_checker_detects_execution_id_payload_conflict():
    evidence = _evidence()
    duplicate = dict(evidence["executions"][0], price="12")
    evidence["executions"].append(duplicate)
    report = _check(evidence)
    assert "RUNTIME_INVARIANT_EXECUTION_ID_CONFLICT" in report.issues


def test_x1_checker_rejects_future_source_anchor():
    evidence = _evidence()
    report = ValidationOnlyRuntimeInvariantChecker().check(
        order_commands=evidence["orders"], executions=evidence["executions"],
        ledger_evidence=evidence["ledger"], u19_decision=evidence["decision"],
        source_namespace="SYNTHETIC:X1_TEST", deterministic_rule_id="X1-DETERMINISTIC-ROUNDTRIP-v1",
        source_manifest_sha256=MANIFEST_HASH, source_anchor_refs=("ACCEPTED_RUNTIME_V2:X1",),
        source_anchor_as_of=BASE + timedelta(days=1), scenario_timestamp=BASE,
        evidence_refs=("TEST:X1",),
    )
    assert "RUNTIME_INVARIANT_FUTURE_SOURCE_ANCHOR" in report.issues


def test_x1_checker_detects_u19_pending_order_with_flat_status():
    evidence = _evidence(pending=("X1-BROKER-BUY",))
    evidence["decision"] = replace(
        evidence["decision"],
        status=U19RecoveryStatus.FLAT_CONFIRMED,
        restore_allowed=True,
        strategy_resume_allowed=True,
    )
    report = _check(evidence)
    assert "RUNTIME_INVARIANT_PENDING_ORDER_WITH_ALLOWED_RECOVERY" in report.issues


def test_x1_checker_detects_submission_or_restore_side_effect_flags():
    evidence = _evidence()
    evidence["decision"] = replace(evidence["decision"], order_submission_enabled=True)
    report = _check(evidence)
    assert "RUNTIME_INVARIANT_VALIDATION_ONLY_SIDE_EFFECT_FLAG_ENABLED" in report.issues


def test_x1_checker_detects_u19_execution_set_mismatch():
    evidence = _evidence()
    evidence["decision"] = replace(evidence["decision"], execution_events=evidence["decision"].execution_events[:1])
    report = _check(evidence)
    assert "RUNTIME_INVARIANT_U19_EXECUTION_ID_SET_MISMATCH" in report.issues


def test_x1_checker_detects_flat_status_with_nonflat_vssf_positions():
    evidence = _evidence()
    evidence["ledger"]["vssf_positions"] = {"SYNTHETIC_CONTRACT:X1": {"side": "BUY", "qty": 1, "avg_price": "10"}}
    report = _check(evidence)
    assert "RUNTIME_INVARIANT_FLAT_STATUS_HAS_VSSF_POSITIONS" in report.issues


def test_x1_checker_rejects_missing_synthetic_provenance():
    evidence = _evidence()
    report = ValidationOnlyRuntimeInvariantChecker().check(
        order_commands=evidence["orders"], executions=evidence["executions"],
        ledger_evidence=evidence["ledger"], u19_decision=evidence["decision"],
        source_namespace="LIVE", deterministic_rule_id="X1-DETERMINISTIC-ROUNDTRIP-v1",
        source_manifest_sha256="", source_anchor_refs=(), source_anchor_as_of=BASE,
        scenario_timestamp=BASE + timedelta(seconds=2), evidence_refs=(),
    )
    assert "RUNTIME_INVARIANT_SYNTHETIC_NAMESPACE_REQUIRED" in report.issues
    assert "RUNTIME_INVARIANT_SOURCE_MANIFEST_SHA256_REQUIRED" in report.issues
    assert "RUNTIME_INVARIANT_PROVENANCE_REFS_REQUIRED" in report.issues


def test_x1_checker_accepts_consistently_pending_order_without_allowing_restore():
    evidence = _evidence(pending=("X1-BROKER-BUY",))
    evidence["orders"][0]["quantity"] = 2
    evidence["orders"][0]["status"] = "PARTIALLY_FILLED"
    evidence["orders"][0]["filled_quantity"] = 1
    report = _check(evidence)
    assert report.status == ValidationOnlyRuntimeInvariantChecker.PASS
    assert report.manifest["u19_status"] == U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED.value


def test_x1_checker_detects_pending_order_not_linked_to_order_command():
    evidence = _evidence(pending=("UNKNOWN-BROKER-ORDER",))
    report = _check(evidence)
    assert "RUNTIME_INVARIANT_U19_PENDING_ORDER_NOT_IN_ORDER_SET" in report.issues


def test_x1_checker_passes_nonflat_restore_allowed_state_without_submission():
    evidence = _evidence()
    instrument = "SYNTHETIC_CONTRACT:X1"
    buy = evidence["executions"][0]
    evidence["orders"] = [evidence["orders"][0]]
    evidence["executions"] = [buy]
    fee = {"execution_id": buy["execution_id"], "fee_amount": "0", "executed_quantity": 1, "executed_price": buy["price"]}
    evidence["ledger"].update({
        "executions": [buy],
        "expected_fee_records": [{"execution_id": buy["execution_id"], "fee_amount": "0", "quantity": 1, "price": buy["price"]}],
        "actual_position_lot_history": ({"execution_id": buy["execution_id"], "side": "BUY", "opened_quantity": 1, "contract_multiplier": MULTIPLIER},),
        "actual_open_position_lots": ({"instrument_id": instrument, "execution_id": buy["execution_id"], "side": "BUY", "remaining_quantity": 1, "contract_multiplier": MULTIPLIER, "execution_timestamp": BASE},),
        "actual_close_events": (), "actual_fee_records": [fee],
        "vssf_positions": {instrument: {"side": "BUY", "qty": 1, "avg_price": "10"}},
        "vssf_realized_pnl_delta": "0", "vssf_unrealized_pnl": "250000",
        "mark_prices": {instrument: "11"},
    })
    position = U19Position(instrument, Decimal(1))
    event = evidence["decision"].execution_events[0]
    evidence["decision"] = replace(
        evidence["decision"], status=U19RecoveryStatus.RESTORE_ALLOWED,
        positions=(position,), broker_positions=(position,), ledger_positions=(position,),
        execution_events=(event,), restore_allowed=True, strategy_resume_allowed=True,
        new_entry_enabled=False, order_submission_enabled=False, runtime_restore_performed=False,
    )
    report = _check(evidence)
    assert report.status == ValidationOnlyRuntimeInvariantChecker.PASS, report.issues
    assert report.manifest["u19_status"] == U19RecoveryStatus.RESTORE_ALLOWED.value


def test_x1_checker_is_read_only_for_supplied_evidence():
    from copy import deepcopy
    evidence = _evidence()
    before = deepcopy(evidence)
    _check(evidence)
    assert evidence == before


def test_x1_checker_detects_active_order_missing_from_u19_pending_set():
    evidence = _evidence()
    evidence["orders"][0]["quantity"] = 2
    evidence["orders"][0]["status"] = "PARTIALLY_FILLED"
    report = _check(evidence)
    assert "RUNTIME_INVARIANT_ACTIVE_ORDER_MISSING_FROM_U19_PENDING:X1-ORDER-BUY" in report.issues


def test_x1_checker_detects_terminal_order_marked_pending_by_u19():
    evidence = _evidence(pending=("X1-BROKER-BUY",))
    report = _check(evidence)
    assert "RUNTIME_INVARIANT_TERMINAL_ORDER_REPORTED_PENDING:X1-ORDER-BUY" in report.issues
