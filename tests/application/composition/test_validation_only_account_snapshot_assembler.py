from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from application.composition.validation_only_account_snapshot_assembler import (
    AccountSnapshotBundle,
    SnapshotSection,
    SyntheticSnapshotProvenance,
    snapshot_rows_sha256,
    validate_account_snapshot_bundle,
)
from environments.live.settlement.sqlite_settlement_store import SQLiteSettlementStore


AS_OF = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)


def _section(snapshot_id, as_of, rows):
    return SnapshotSection(
        snapshot_id=snapshot_id,
        as_of=as_of,
        source="VALIDATION_ONLY:SYNTHETIC_ACCOUNT_FIXTURE",
        payload_sha256=snapshot_rows_sha256(rows),
        rows=tuple(rows),
    )


def _bundle(*, execution_client_id="client-old", final_quantity=4, source_anchor_as_of=None):
    opening_as_of = AS_OF - timedelta(minutes=10)
    orders = (
        {
            "client_order_id": "client-old", "broker_order_id": "broker-old",
            "instrument_id": "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612",
            "side": "BUY", "order_quantity": 3, "cumulative_filled_quantity": 2,
            "status": "CANCELLED",
        },
        {
            "client_order_id": "client-replacement", "broker_order_id": "broker-replacement",
            "instrument_id": "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612",
            "side": "BUY", "order_quantity": 2, "cumulative_filled_quantity": 1,
            "status": "PARTIALLY_FILLED", "replaces_broker_order_id": "broker-old",
        },
    )
    executions = (
        {
            "execution_id": "SYNTHETIC:FILL-001", "client_order_id": execution_client_id,
            "broker_order_id": "broker-old", "instrument_id": "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612",
            "side": "BUY", "filled_quantity": 2, "execution_price": "10.25",
            "execution_timestamp": AS_OF - timedelta(minutes=5),
        },
        {
            "execution_id": "SYNTHETIC:FILL-002", "client_order_id": "client-replacement",
            "broker_order_id": "broker-replacement", "instrument_id": "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612",
            "side": "BUY", "filled_quantity": 1, "execution_price": "10.50",
            "execution_timestamp": AS_OF - timedelta(minutes=2),
        },
    )
    opening = ({
        "instrument_id": "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612",
        "side": "LONG", "quantity": 1, "avg_price": "9.75",
    },)
    positions = ({
        "instrument_id": "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612",
        "side": "LONG", "quantity": final_quantity, "avg_price": "10.25",
    },)
    return AccountSnapshotBundle(
        orders=_section("orders-snapshot-001", AS_OF, orders),
        executions=_section("executions-snapshot-001", AS_OF, executions),
        positions=_section("positions-snapshot-001", AS_OF, positions),
        opening_positions=_section("opening-positions-snapshot-001", opening_as_of, opening),
        provenance=SyntheticSnapshotProvenance(
            namespace="SYNTHETIC:DERIVED_SCENARIO",
            deterministic_rule_id="account-order-fill-position-v1",
            manifest_sha256="a" * 64,
            scenario_timestamp=AS_OF,
            source_anchor_refs=("TEST_ONLY:opening-position-anchor",),
            source_anchor_as_of=source_anchor_as_of or opening_as_of,
        ),
    )


def test_account_snapshot_bundle_reconciles_replacement_late_fill_and_position_quantity():
    result = validate_account_snapshot_bundle(_bundle())
    assert result.is_valid
    assert result.status == "VALIDATION_ONLY_RECONCILED"
    assert result.issues == ()
    assert result.normalized_positions == ({
        "instrument_id": "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612",
        "side": "LONG", "qty": 4, "avg_price": "10.25",
    },)
    assert len(result.snapshot_ids) == 4
    assert len(result.evidence_sha256) == 64


def test_account_snapshot_bundle_identity_or_quantity_mismatch_stays_reconciliation_required():
    result = validate_account_snapshot_bundle(_bundle(execution_client_id="wrong-client", final_quantity=4))
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "EXECUTION_ORDER_CORRELATION_MISMATCH:SYNTHETIC:FILL-001" in result.issues
    assert any(issue.startswith("ORDER_EXECUTION_CUMULATIVE_QUANTITY_MISMATCH:broker-old") for issue in result.issues)
    assert result.normalized_positions == ()


def test_account_snapshot_bundle_rejects_future_anchor_hash_and_time_mismatch():
    bundle = _bundle(source_anchor_as_of=AS_OF + timedelta(seconds=1))
    altered_orders = replace(bundle.orders, payload_sha256="0" * 64)
    altered_executions = replace(bundle.executions, as_of=AS_OF + timedelta(seconds=1))
    invalid = replace(bundle, orders=altered_orders, executions=altered_executions)
    result = validate_account_snapshot_bundle(invalid)
    assert result.status == "RECONCILIATION_REQUIRED"
    assert "SNAPSHOT_SHA256_MISMATCH:orders-snapshot-001" in result.issues
    assert "ORDERS_EXECUTIONS_POSITIONS_AS_OF_MISMATCH" in result.issues
    assert "SYNTHETIC_FUTURE_SOURCE_ANCHOR" in result.issues


def test_validated_account_snapshot_bundle_imports_multi_instrument_baseline_atomically(tmp_path):
    bundle = _bundle()
    result = validate_account_snapshot_bundle(bundle)
    assert result.is_valid
    store = SQLiteSettlementStore(tmp_path / "assembled-account-baseline.sqlite3")
    store.establish_authoritative_baseline_snapshot(
        positions_payload=result.baseline_positions_payload(),
        orders_snapshot_id=bundle.orders.snapshot_id,
        executions_snapshot_id=bundle.executions.snapshot_id,
        positions_snapshot_id=bundle.positions.snapshot_id,
        as_of=result.as_of,
        source="VALIDATION_ONLY:ACCOUNT_SNAPSHOT_BUNDLE",
        payload_sha256=result.evidence_sha256,
        authoritative_evidence_ref=f"TEST_ONLY:bundle:{result.evidence_sha256}",
    )
    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "SELECT instrument_id,position_json FROM position_states"
        ).fetchall()
        baseline = connection.execute(
            "SELECT value FROM settlement_meta WHERE key='authoritative_baseline_ready'"
        ).fetchone()[0]
    assert len(rows) == 1
    assert baseline == "1"



def test_account_snapshot_bundle_detects_duplicate_execution_and_missing_replacement_parent():
    bundle = _bundle()
    duplicate_fill = dict(bundle.executions.rows[0])
    duplicate_fill["filled_quantity"] = 1
    executions = bundle.executions.rows + (duplicate_fill,)
    orders = tuple(
        {**row, "replaces_broker_order_id": "broker-missing"} if row["broker_order_id"] == "broker-replacement" else row
        for row in bundle.orders.rows
    )
    invalid = replace(
        bundle,
        orders=_section(bundle.orders.snapshot_id, AS_OF, orders),
        executions=_section(bundle.executions.snapshot_id, AS_OF, executions),
    )
    result = validate_account_snapshot_bundle(invalid)
    assert "EXECUTION_ID_DUPLICATE:SYNTHETIC:FILL-001" in result.issues
    assert "REPLACEMENT_PARENT_NOT_FOUND:broker-replacement" in result.issues
    assert result.status == "RECONCILIATION_REQUIRED"


def test_account_snapshot_bundle_rejects_live_source_and_execution_before_opening_snapshot():
    bundle = _bundle()
    executions = tuple(
        {**row, "execution_timestamp": AS_OF - timedelta(minutes=20)}
        for row in bundle.executions.rows
    )
    invalid = replace(
        bundle,
        orders=replace(bundle.orders, source="KIS_LIVE"),
        executions=_section(bundle.executions.snapshot_id, AS_OF, executions),
    )
    result = validate_account_snapshot_bundle(invalid)
    assert "NON_VALIDATION_SOURCE_REJECTED:orders-snapshot-001" in result.issues
    assert "EXECUTION_BEFORE_OPENING_POSITION_SNAPSHOT:SYNTHETIC:FILL-001" in result.issues
    assert result.status == "RECONCILIATION_REQUIRED"
