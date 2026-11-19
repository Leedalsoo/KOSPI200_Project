from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3
import pytest

from application.composition.validation_only_account_snapshot_assembler import (
    AccountSnapshotBundle,
    SnapshotSection,
    SyntheticSnapshotProvenance,
    snapshot_rows_sha256,
    validate_account_snapshot_bundle,
)
from application.composition.validation_only_account_snapshot_u19_reconciler import (
    ValidationOnlyAccountSnapshotU19Reconciler,
)
from application.composition.track2_u19_ledger_snapshot_builder import (
    ValidationOnlyU19LedgerSnapshotBuilder,
)
from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from core.oms.track2_u19_recovery import (
    U19ExpectedGroupManifest,
    U19Position,
    U19RecoveryStatus,
    _expected_group_manifest_digest,
)
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import (
    LiveExecutionPositionBridge,
    LivePositionFillAdapter,
)
from environments.live.position.live_position_aggregate import LivePositionAggregate
from environments.live.settlement.sqlite_settlement_store import SQLiteSettlementStore
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


AS_OF = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
GROUP_ID = "SYNTHETIC:GROUP:ACCOUNT-U19"


def _section(snapshot_id, as_of, rows):
    return SnapshotSection(
        snapshot_id=snapshot_id,
        as_of=as_of,
        source="VALIDATION_ONLY:SYNTHETIC_ACCOUNT_FIXTURE",
        payload_sha256=snapshot_rows_sha256(rows),
        rows=tuple(rows),
    )


def _bundle(*, final_quantity=4, executions=None):
    instrument = "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612"
    orders = (
        {
            "client_order_id": "client-old", "broker_order_id": "broker-old",
            "instrument_id": instrument, "side": "BUY", "order_quantity": 3,
            "cumulative_filled_quantity": 2, "status": "CANCELLED",
        },
        {
            "client_order_id": "client-replacement", "broker_order_id": "broker-replacement",
            "instrument_id": instrument, "side": "BUY", "order_quantity": 2,
            "cumulative_filled_quantity": 1, "status": "PARTIALLY_FILLED",
            "replaces_broker_order_id": "broker-old",
        },
    )
    fills = executions or (
        {
            "execution_id": "SYNTHETIC:FILL-001", "client_order_id": "client-old",
            "broker_order_id": "broker-old", "instrument_id": instrument,
            "side": "BUY", "filled_quantity": 1, "execution_price": "10.00",
            "execution_timestamp": AS_OF - timedelta(minutes=5),
        },
        {
            "execution_id": "SYNTHETIC:FILL-002", "client_order_id": "client-old",
            "broker_order_id": "broker-old", "instrument_id": instrument,
            "side": "BUY", "filled_quantity": 1, "execution_price": "10.10",
            "execution_timestamp": AS_OF - timedelta(minutes=4),
        },
        {
            "execution_id": "SYNTHETIC:FILL-003", "client_order_id": "client-replacement",
            "broker_order_id": "broker-replacement", "instrument_id": instrument,
            "side": "BUY", "filled_quantity": 1, "execution_price": "10.20",
            "execution_timestamp": AS_OF - timedelta(minutes=2),
        },
    )
    opening_as_of = AS_OF - timedelta(minutes=10)
    opening = ({
        "instrument_id": instrument, "side": "LONG", "quantity": 1, "avg_price": "9.75",
    },)
    positions = ({
        "instrument_id": instrument, "side": "LONG", "quantity": final_quantity,
        "avg_price": "10.10",
    },)
    return AccountSnapshotBundle(
        orders=_section("orders-account", AS_OF, orders),
        executions=_section("executions-account", AS_OF, fills),
        positions=_section("positions-account", AS_OF, positions),
        opening_positions=_section("opening-account", opening_as_of, opening),
        provenance=SyntheticSnapshotProvenance(
            namespace="SYNTHETIC:DERIVED_SCENARIO",
            deterministic_rule_id="account-u19-four-way-v1",
            manifest_sha256="b" * 64,
            scenario_timestamp=AS_OF,
            source_anchor_refs=("TEST_ONLY:account-opening-anchor",),
            source_anchor_as_of=opening_as_of,
        ),
    )


def _seed_order(
    store, *, client_id, broker_id, instrument, quantity, leg_id, fills,
    group_id=GROUP_ID, side="BUY", execution_times=None,
):
    oms = OrderStateMachine(persistence_store=store)
    oms.apply_intent(OrderIntent(
        client_order_id=client_id, instrument_id=instrument, side=side,
        quantity=quantity, intent_type="OPEN", strategy_id="S2",
        group_id=group_id, leg_id=leg_id,
    ))
    oms.register_broker_order_command(BrokerOrderCommand(
        client_order_id=client_id, instrument_id=instrument, side=side,
        quantity=quantity, order_type="LIMIT", broker_symbol=instrument,
        asset_type="OPTION", strategy_id="S2", group_id=group_id,
        leg_id=leg_id, position_role="OPEN",
    ))
    oms.apply_ack(OrderAckEvent(client_order_id=client_id, accepted=True, broker_order_id=broker_id))
    position = LivePositionAggregate(instrument)
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=store),
        position_aggregate=position,
        settlement_store=store,
    )
    for index, (execution_id, quantity_filled, price) in enumerate(fills):
        cumulative = sum(item[1] for item in fills[: index + 1])
        bridge.settle(ExecutionReport(
            client_order_id=client_id, broker_order_id=broker_id,
            execution_id=execution_id,
            status="FILLED" if cumulative == quantity else "PARTIALLY_FILLED",
            filled_quantity=quantity_filled, remaining_quantity=quantity - cumulative,
            execution_price=Decimal(price),
            execution_timestamp=(execution_times or {}).get(execution_id, AS_OF - timedelta(minutes={"SYNTHETIC:FILL-001": 5, "SYNTHETIC:FILL-002": 4, "SYNTHETIC:FILL-003": 2}.get(execution_id, 1 + index))),
            fee=Decimal("1"), group_id=group_id, leg_id=leg_id,
        ))
    return oms


def _make_reconciler(
    tmp_path, *, old_first_fill_quantity=1, require_expected_group_manifest=False,
):
    instrument = "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612"
    settlement = SQLiteSettlementStore(tmp_path / "settlement.sqlite3")
    old = _seed_order(
        settlement, client_id="client-old", broker_id="broker-old",
        instrument=instrument, quantity=(3 if old_first_fill_quantity == 1 else 4), leg_id="call",
        fills=(('SYNTHETIC:FILL-001', old_first_fill_quantity, '10.00'), ('SYNTHETIC:FILL-002', 1, '10.10')),
    )
    old.apply_cancel(ExecutionReport(
        client_order_id="client-old", broker_order_id="broker-old",
        execution_id="SYNTHETIC:CANCEL-ACK", status="CANCELLED",
        filled_quantity=0, remaining_quantity=1, execution_price=None,
        execution_timestamp=AS_OF - timedelta(minutes=1),
        group_id=GROUP_ID, leg_id="call",
    ))
    _seed_order(
        settlement, client_id="client-replacement", broker_id="broker-replacement",
        instrument=instrument, quantity=2, leg_id="call",
        fills=(("SYNTHETIC:FILL-003", 1, "10.20"),),
    )
    settlement.record_order_replacement_link(
        link_id="SYNTHETIC:REPLACE-001",
        original_client_order_id="client-old", original_broker_order_id="broker-old",
        replacement_client_order_id="client-replacement",
        replacement_broker_order_id="broker-replacement",
        group_id=GROUP_ID, leg_id="call",
        cancel_request_ref="VALIDATION_ONLY:CANCEL-REQUEST",
        cancel_ack_ref="VALIDATION_ONLY:CANCEL-ACK",
        source="VALIDATION_ONLY:ORDER_REPLACEMENT_FIXTURE", payload={},
    )
    checkpoint = SqliteTrack2U19RecoveryStore(tmp_path / "u19-checkpoint.sqlite3")
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        checkpoint, settlement_store=settlement,
        require_expected_group_manifest=require_expected_group_manifest,
    )
    reconciler = ValidationOnlyAccountSnapshotU19Reconciler(
        ledger_snapshot_builder=ValidationOnlyU19LedgerSnapshotBuilder(settlement),
        recovery_coordinator=coordinator,
    )
    return reconciler, checkpoint.path


def test_account_snapshot_bundle_reconciles_four_ways_through_u19_and_checkpoint_reopen(tmp_path):
    bundle = _bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, checkpoint_path = _make_reconciler(tmp_path)

    result = reconciler.reconcile(
        bundle=bundle, validation=validation, group_id=GROUP_ID,
        snapshot_id="account-four-way-001", as_of=AS_OF,
    )

    assert result.is_valid
    assert result.issues == ()
    assert result.ledger_snapshot is not None
    assert {event.execution_id for event in result.ledger_snapshot.execution_events} == {
        "SYNTHETIC:FILL-001", "SYNTHETIC:FILL-002", "SYNTHETIC:FILL-003",
    }
    assert result.projected_ledger_snapshot.positions == result.broker_snapshot.positions
    assert result.recovery_decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert result.recovery_decision.new_entry_enabled is False
    assert result.recovery_decision.order_submission_enabled is False

    reopened = SqliteTrack2U19RecoveryStore(checkpoint_path)
    checkpoint = reopened.load_latest(GROUP_ID)
    assert checkpoint["status"] == U19RecoveryStatus.RESTORE_ALLOWED.value
    assert checkpoint["broker_positions"] == checkpoint["ledger_positions"]
    assert {item["execution_id"] for item in checkpoint["execution_events"]} == {
        "SYNTHETIC:FILL-001", "SYNTHETIC:FILL-002", "SYNTHETIC:FILL-003",
    }
    assert checkpoint["new_entry_enabled"] is False
    assert checkpoint["order_submission_enabled"] is False


def test_account_snapshot_u19_mismatch_is_reconciliation_required_not_immediate_block(tmp_path):
    bundle = _bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path, old_first_fill_quantity=2)

    result = reconciler.reconcile(
        bundle=bundle, validation=validation, group_id=GROUP_ID,
        snapshot_id="account-position-mismatch", as_of=AS_OF,
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_POSITION_U19_LEDGER_PROJECTION_MISMATCH" in result.issues
    assert "ACCOUNT_U19_EXECUTION_QUANTITY_MISMATCH:SYNTHETIC:FILL-001" in result.issues
    assert result.recovery_decision.status is U19RecoveryStatus.POSITION_LEDGER_MISMATCH


def test_account_snapshot_u19_execution_id_gap_requests_reconciliation(tmp_path):
    bundle = _bundle()
    changed = tuple(
        {**row, "execution_id": "SYNTHETIC:FILL-UNKNOWN"}
        if row["execution_id"] == "SYNTHETIC:FILL-003" else row
        for row in bundle.executions.rows
    )
    bundle = replace(bundle, executions=_section(bundle.executions.snapshot_id, AS_OF, changed))
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path)

    result = reconciler.reconcile(
        bundle=bundle, validation=validation, group_id=GROUP_ID,
        snapshot_id="account-execution-gap", as_of=AS_OF,
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_U19_EXECUTION_ID_SET_MISMATCH" in result.issues
    assert result.recovery_decision is None


def test_account_snapshot_u19_preserves_pending_late_fill_gate(tmp_path):
    reconciler, _ = _make_reconciler(tmp_path)
    settlement = reconciler.ledger_snapshot_builder.settlement_store
    settlement.record_late_fill_pending(
        execution_id="SYNTHETIC:LATE-FILL-PENDING",
        client_order_id="client-old", broker_order_id="broker-old",
        payload={"execution_id": "SYNTHETIC:LATE-FILL-PENDING", "source": "VALIDATION_ONLY"},
    )
    bundle = _bundle()
    validation = validate_account_snapshot_bundle(bundle)

    result = reconciler.reconcile(
        bundle=bundle, validation=validation, group_id=GROUP_ID,
        snapshot_id="account-pending-late-fill", as_of=AS_OF,
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert result.recovery_decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert result.recovery_decision.new_entry_enabled is False
    assert result.recovery_decision.order_submission_enabled is False


def test_account_snapshot_missing_section_or_invalid_validation_does_not_call_u19_builder(tmp_path):
    bundle = _bundle()
    invalid = replace(
        validate_account_snapshot_bundle(bundle),
        status="RECONCILIATION_REQUIRED",
        issues=("SNAPSHOT_SECTION_MISSING:EXECUTIONS",),
    )
    reconciler, _ = _make_reconciler(tmp_path)

    result = reconciler.reconcile(
        bundle=bundle, validation=invalid, group_id=GROUP_ID,
        snapshot_id="account-missing-section", as_of=AS_OF,
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert result.issues == ("SNAPSHOT_SECTION_MISSING:EXECUTIONS",)
    assert result.ledger_snapshot is None







def test_account_snapshot_u19_as_of_mismatch_is_reconciliation_required(tmp_path):
    bundle = _bundle()
    validation = validate_account_snapshot_bundle(bundle)
    reconciler, _ = _make_reconciler(tmp_path)

    result = reconciler.reconcile(
        bundle=bundle, validation=validation, group_id=GROUP_ID,
        snapshot_id="account-as-of-mismatch", as_of=AS_OF + timedelta(minutes=1),
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_U19_SNAPSHOT_AS_OF_MISMATCH" in result.issues
    assert result.recovery_decision.status is U19RecoveryStatus.SNAPSHOT_AS_OF_MISMATCH



GROUP_TWO = "SYNTHETIC:GROUP:ACCOUNT-U19-SECOND"
SHARED_INSTRUMENT = "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612"
SECOND_INSTRUMENT = "SYNTHETIC_CONTRACT:KOSPI200_PUT_202612"


def _multi_group_bundle(*, final_shared=3, final_second=1, shared_sell_quantity=1):
    orders = (
        {
            "client_order_id": "client-old", "broker_order_id": "broker-old",
            "group_id": GROUP_ID, "instrument_id": SHARED_INSTRUMENT,
            "side": "BUY", "order_quantity": 3, "cumulative_filled_quantity": 2,
            "status": "CANCELLED",
        },
        {
            "client_order_id": "client-replacement", "broker_order_id": "broker-replacement",
            "group_id": GROUP_ID, "instrument_id": SHARED_INSTRUMENT,
            "side": "BUY", "order_quantity": 2, "cumulative_filled_quantity": 1,
            "status": "PARTIALLY_FILLED", "replaces_broker_order_id": "broker-old",
        },
        {
            "client_order_id": "client-g2-shared", "broker_order_id": "broker-g2-shared",
            "group_id": GROUP_TWO, "instrument_id": SHARED_INSTRUMENT,
            "side": "SELL", "order_quantity": (shared_sell_quantity + 1), "cumulative_filled_quantity": shared_sell_quantity,
            "status": "PARTIALLY_FILLED",
        },
        {
            "client_order_id": "client-g2-second", "broker_order_id": "broker-g2-second",
            "group_id": GROUP_TWO, "instrument_id": SECOND_INSTRUMENT,
            "side": "SELL", "order_quantity": 1, "cumulative_filled_quantity": 1,
            "status": "FILLED",
        },
    )
    executions = (
        {
            "execution_id": "SYNTHETIC:FILL-001", "client_order_id": "client-old",
            "broker_order_id": "broker-old", "group_id": GROUP_ID,
            "instrument_id": SHARED_INSTRUMENT, "side": "BUY",
            "filled_quantity": 1, "execution_price": "10.00",
            "execution_timestamp": AS_OF - timedelta(minutes=5),
        },
        {
            "execution_id": "SYNTHETIC:FILL-002", "client_order_id": "client-old",
            "broker_order_id": "broker-old", "group_id": GROUP_ID,
            "instrument_id": SHARED_INSTRUMENT, "side": "BUY",
            "filled_quantity": 1, "execution_price": "10.10",
            "execution_timestamp": AS_OF - timedelta(minutes=4),
        },
        {
            "execution_id": "SYNTHETIC:FILL-003", "client_order_id": "client-replacement",
            "broker_order_id": "broker-replacement", "group_id": GROUP_ID,
            "instrument_id": SHARED_INSTRUMENT, "side": "BUY",
            "filled_quantity": 1, "execution_price": "10.20",
            "execution_timestamp": AS_OF - timedelta(minutes=2),
        },
        {
            "execution_id": "SYNTHETIC:G2-FILL-001", "client_order_id": "client-g2-shared",
            "broker_order_id": "broker-g2-shared", "group_id": GROUP_TWO,
            "instrument_id": SHARED_INSTRUMENT, "side": "SELL",
            "filled_quantity": shared_sell_quantity, "execution_price": "10.30",
            "execution_timestamp": AS_OF - timedelta(minutes=1),
        },
        {
            "execution_id": "SYNTHETIC:G2-FILL-002", "client_order_id": "client-g2-second",
            "broker_order_id": "broker-g2-second", "group_id": GROUP_TWO,
            "instrument_id": SECOND_INSTRUMENT, "side": "SELL",
            "filled_quantity": 1, "execution_price": "8.30",
            "execution_timestamp": AS_OF - timedelta(seconds=30),
        },
    )
    opening = ({
        "instrument_id": SHARED_INSTRUMENT, "side": "LONG",
        "quantity": 1, "avg_price": "9.75",
    },)
    positions = (
        {
            "instrument_id": SHARED_INSTRUMENT, "side": ("FLAT" if final_shared == 0 else "LONG"),
            "quantity": final_shared, "avg_price": "10.10",
        },
        {
            "instrument_id": SECOND_INSTRUMENT, "side": "SHORT",
            "quantity": final_second, "avg_price": "8.30",
        },
    )
    opening_as_of = AS_OF - timedelta(minutes=10)
    return AccountSnapshotBundle(
        orders=_section("orders-multi-account", AS_OF, orders),
        executions=_section("executions-multi-account", AS_OF, executions),
        positions=_section("positions-multi-account", AS_OF, positions),
        opening_positions=_section("opening-multi-account", opening_as_of, opening),
        provenance=SyntheticSnapshotProvenance(
            namespace="SYNTHETIC:DERIVED_SCENARIO",
            deterministic_rule_id="account-u19-multi-group-netting-v1",
            manifest_sha256="c" * 64,
            scenario_timestamp=AS_OF,
            source_anchor_refs=("TEST_ONLY:multi-group-opening-anchor",),
            source_anchor_as_of=opening_as_of,
        ),
    )


def _seed_second_group(reconciler, *, shared_sell_quantity=1):
    settlement = reconciler.ledger_snapshot_builder.settlement_store
    _seed_order(
        settlement, client_id="client-g2-shared", broker_id="broker-g2-shared",
        instrument=SHARED_INSTRUMENT, quantity=(shared_sell_quantity + 1), leg_id="shared",
        fills=(("SYNTHETIC:G2-FILL-001", shared_sell_quantity, "10.30"),),
        execution_times={"SYNTHETIC:G2-FILL-001": AS_OF - timedelta(minutes=1)},
        group_id=GROUP_TWO, side="SELL",
    )
    _seed_order(
        settlement, client_id="client-g2-second", broker_id="broker-g2-second",
        instrument=SECOND_INSTRUMENT, quantity=1, leg_id="second",
        fills=(("SYNTHETIC:G2-FILL-002", 1, "8.30"),),
        execution_times={"SYNTHETIC:G2-FILL-002": AS_OF - timedelta(seconds=30)},
        group_id=GROUP_TWO, side="SELL",
    )


def _expected_group_manifests(bundle, group_ids=(GROUP_ID, GROUP_TWO)):
    """Build independent validation-only expectations from the scenario sidecar."""
    manifests = []
    for group_id in sorted(group_ids):
        leg_ids = tuple(sorted({
            str(row.get("instrument_id") or "").strip()
            for row in bundle.orders.rows
            if row.get("group_id") == group_id and str(row.get("instrument_id") or "").strip()
        } | {
            str(row.get("instrument_id") or "").strip()
            for row in bundle.executions.rows
            if row.get("group_id") == group_id and str(row.get("instrument_id") or "").strip()
        }))
        quantities = {}
        for row in bundle.executions.rows:
            if row.get("group_id") != group_id:
                continue
            instrument = str(row.get("instrument_id") or "").strip()
            side = str(row.get("side") or "").upper()
            quantity = int(row.get("filled_quantity"))
            signed = quantity if side in {"BUY", "LONG"} else -quantity if side in {"SELL", "SHORT"} else 0
            quantities[instrument] = quantities.get(instrument, 0) + signed
        positions = tuple(
            U19Position(instrument, Decimal(quantity))
            for instrument, quantity in sorted(quantities.items()) if quantity
        )
        manifest = U19ExpectedGroupManifest(
            group_id=group_id,
            manifest_id=f"SYNTHETIC:EXPECTED:{group_id}",
            source="VALIDATION_ONLY:EXPECTED_GROUP_MANIFEST",
            provenance="VALIDATION_ONLY:DERIVED_SCENARIO_SIDECAR",
            leg_instrument_ids=leg_ids,
            expected_positions=positions,
            payload_sha256="0" * 64,
        )
        manifests.append(replace(manifest, payload_sha256=_expected_group_manifest_digest(manifest)))
    return tuple(manifests)


def test_multi_group_strict_recovery_requires_manifest_without_promoting_account_snapshot(tmp_path):
    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    reconciler, _ = _make_reconciler(tmp_path, require_expected_group_manifest=True)
    _seed_second_group(reconciler)

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation, group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-manifest-missing", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MANIFEST-MISSING",
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert result.recovery_decision.status is U19RecoveryStatus.EXPECTED_GROUP_MANIFEST_UNAVAILABLE
    assert result.expected_group_manifest is None
    assert result.recovery_decision.new_entry_enabled is False
    assert result.recovery_decision.order_submission_enabled is False


def test_multi_group_rejects_tampered_child_manifest_before_checkpoint(tmp_path):
    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    reconciler, checkpoint_path = _make_reconciler(tmp_path, require_expected_group_manifest=True)
    _seed_second_group(reconciler)
    manifests = list(_expected_group_manifests(bundle))
    manifests[1] = replace(manifests[1], payload_sha256="f" * 64)

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation, group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-manifest-tampered", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MANIFEST-TAMPERED",
        expected_group_manifests=tuple(manifests),
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_EXPECTED_GROUP_MANIFEST_INVALID_OR_GROUP_SET_MISMATCH" in result.issues
    assert result.recovery_decision is None
    assert SqliteTrack2U19RecoveryStore(checkpoint_path).load_latest(
        "SYNTHETIC:ACCOUNT_AGGREGATE:MANIFEST-TAMPERED"
    ) is None


def test_multi_group_manifest_position_mismatch_is_reported_before_checkpoint(tmp_path):
    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    reconciler, checkpoint_path = _make_reconciler(tmp_path, require_expected_group_manifest=True)
    _seed_second_group(reconciler)
    manifests = list(_expected_group_manifests(bundle))
    child = manifests[1]
    changed_positions = tuple(
        U19Position(item.instrument_id, item.signed_quantity - Decimal(1))
        if item.instrument_id == SHARED_INSTRUMENT else item
        for item in child.expected_positions
    )
    changed_child = replace(child, expected_positions=changed_positions, payload_sha256="0" * 64)
    manifests[1] = replace(
        changed_child, payload_sha256=_expected_group_manifest_digest(changed_child),
    )

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation, group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-manifest-position-mismatch", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MANIFEST-POSITION-MISMATCH",
        expected_group_manifests=tuple(manifests),
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_EXPECTED_GROUP_MANIFEST_POSITION_PROJECTION_MISMATCH" in result.issues
    assert result.recovery_decision is None
    assert SqliteTrack2U19RecoveryStore(checkpoint_path).load_latest(
        "SYNTHETIC:ACCOUNT_AGGREGATE:MANIFEST-POSITION-MISMATCH"
    ) is None


def test_multi_group_manifest_requires_exact_child_group_set(tmp_path):
    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    reconciler, _ = _make_reconciler(tmp_path)
    _seed_second_group(reconciler)

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation, group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-manifest-group-gap", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MANIFEST-GROUP-GAP",
        expected_group_manifests=_expected_group_manifests(bundle, (GROUP_ID,)),
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_EXPECTED_GROUP_MANIFEST_INVALID_OR_GROUP_SET_MISMATCH" in result.issues
    assert result.recovery_decision is None


def test_multi_group_account_snapshot_nets_shared_instrument_and_reopens_aggregate_u19_checkpoint(tmp_path):
    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, checkpoint_path = _make_reconciler(tmp_path)
    _seed_second_group(reconciler)

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation,
        group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-account-001", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MULTI-001",
        expected_group_manifests=_expected_group_manifests(bundle),
    )

    assert result.is_valid
    assert result.issues == ()
    assert {item.group_id for item in result.group_ledger_snapshots} == {GROUP_ID, GROUP_TWO}
    assert {event.execution_id for event in result.ledger_snapshot.execution_events} == {
        "SYNTHETIC:FILL-001", "SYNTHETIC:FILL-002", "SYNTHETIC:FILL-003",
        "SYNTHETIC:G2-FILL-001", "SYNTHETIC:G2-FILL-002",
    }
    assert {item.instrument_id: item.signed_quantity for item in result.ledger_snapshot.positions} == {
        SHARED_INSTRUMENT: Decimal("2"), SECOND_INSTRUMENT: Decimal("-1"),
    }
    assert {item.instrument_id: item.signed_quantity for item in result.projected_ledger_snapshot.positions} == {
        SHARED_INSTRUMENT: Decimal("3"), SECOND_INSTRUMENT: Decimal("-1"),
    }
    assert result.projected_ledger_snapshot.positions == result.broker_snapshot.positions
    assert result.recovery_decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert result.expected_group_manifest is not None
    assert result.expected_group_manifest.leg_instrument_ids == (SHARED_INSTRUMENT, SECOND_INSTRUMENT)
    assert result.expected_group_manifest.expected_positions == result.projected_ledger_snapshot.positions
    assert result.recovery_decision.expected_group_manifest_id == result.expected_group_manifest.manifest_id
    assert result.recovery_decision.expected_group_manifest_sha256 == result.expected_group_manifest.payload_sha256
    assert result.recovery_decision.new_entry_enabled is False
    assert result.recovery_decision.order_submission_enabled is False

    checkpoint = SqliteTrack2U19RecoveryStore(checkpoint_path).load_latest(
        "SYNTHETIC:ACCOUNT_AGGREGATE:MULTI-001"
    )
    assert checkpoint["status"] == U19RecoveryStatus.RESTORE_ALLOWED.value
    assert checkpoint["broker_positions"] == checkpoint["ledger_positions"]
    assert {item["execution_id"] for item in checkpoint["execution_events"]} == {
        "SYNTHETIC:FILL-001", "SYNTHETIC:FILL-002", "SYNTHETIC:FILL-003",
        "SYNTHETIC:G2-FILL-001", "SYNTHETIC:G2-FILL-002",
    }


def test_multi_group_account_snapshot_rejects_missing_group_lineage_without_blocking_other_validation(tmp_path):
    bundle = _multi_group_bundle()
    changed_orders = tuple(
        {key: value for key, value in row.items() if key != "group_id"}
        if row["client_order_id"] == "client-g2-shared" else row
        for row in bundle.orders.rows
    )
    bundle = replace(bundle, orders=_section(bundle.orders.snapshot_id, AS_OF, changed_orders))
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path)
    _seed_second_group(reconciler)

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation,
        group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-missing-lineage", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MULTI-MISSING",
        expected_group_manifests=_expected_group_manifests(bundle),
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_ORDER_GROUP_LINEAGE_MISSING" in result.issues
    assert result.recovery_decision is None


def test_multi_group_account_snapshot_keeps_late_fill_pending_for_owning_group(tmp_path):
    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path)
    _seed_second_group(reconciler)
    reconciler.ledger_snapshot_builder.settlement_store.record_late_fill_pending(
        execution_id="SYNTHETIC:G2-LATE-FILL-PENDING",
        client_order_id="client-g2-shared", broker_order_id="broker-g2-shared",
        payload={"execution_id": "SYNTHETIC:G2-LATE-FILL-PENDING", "source": "VALIDATION_ONLY"},
    )

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation,
        group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-late-fill", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MULTI-LATE",
        expected_group_manifests=_expected_group_manifests(bundle),
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert result.recovery_decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert "client-g2-shared" in result.recovery_decision.pending_order_ids
    assert result.recovery_decision.new_entry_enabled is False
    assert result.recovery_decision.order_submission_enabled is False


def test_multi_group_account_snapshot_does_not_checkpoint_on_execution_position_mismatch(tmp_path):
    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path)
    _seed_second_group(reconciler, shared_sell_quantity=2)

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation,
        group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-position-mismatch", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MULTI-MISMATCH",
        expected_group_manifests=_expected_group_manifests(bundle),
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_POSITION_U19_GROUP_AGGREGATE_MISMATCH" in result.issues
    assert "ACCOUNT_U19_EXECUTION_QUANTITY_MISMATCH:SYNTHETIC:G2-FILL-001" in result.issues
    assert result.recovery_decision is None







def test_multi_group_account_snapshot_normalizes_flat_position_after_cross_group_offset(tmp_path):
    bundle = _multi_group_bundle(final_shared=0, shared_sell_quantity=4)
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path)
    _seed_second_group(reconciler, shared_sell_quantity=4)

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation,
        group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-flat-netting", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MULTI-FLAT",
        expected_group_manifests=_expected_group_manifests(bundle),
    )

    assert result.is_valid
    assert {item.instrument_id: item.signed_quantity for item in result.projected_ledger_snapshot.positions} == {
        SECOND_INSTRUMENT: Decimal("-1"),
    }
    assert result.expected_group_manifest.leg_instrument_ids == (SHARED_INSTRUMENT, SECOND_INSTRUMENT)
    assert {item.instrument_id for item in result.expected_group_manifest.expected_positions} == {
        SECOND_INSTRUMENT,
    }
    assert result.broker_snapshot.positions == result.projected_ledger_snapshot.positions


def test_multi_group_account_snapshot_is_independent_of_execution_row_order(tmp_path):
    bundle = _multi_group_bundle()
    reversed_rows = tuple(reversed(bundle.executions.rows))
    bundle = replace(
        bundle,
        executions=_section(bundle.executions.snapshot_id, AS_OF, reversed_rows),
    )
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path)
    _seed_second_group(reconciler)

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation,
        group_ids=(GROUP_TWO, GROUP_ID),
        snapshot_id="multi-group-out-of-order", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MULTI-ORDER",
        expected_group_manifests=_expected_group_manifests(bundle),
    )

    assert result.is_valid
    assert tuple(event.execution_id for event in result.ledger_snapshot.execution_events) == tuple(sorted(
        event.execution_id for event in result.ledger_snapshot.execution_events
    ))
    canonical_bundle = _multi_group_bundle()
    canonical_reconciler, _ = _make_reconciler(tmp_path / "canonical")
    _seed_second_group(canonical_reconciler)
    canonical = canonical_reconciler.reconcile_account(
        bundle=canonical_bundle, validation=validate_account_snapshot_bundle(canonical_bundle),
        group_ids=(GROUP_ID, GROUP_TWO), snapshot_id="multi-group-canonical-order", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MULTI-ORDER",
        expected_group_manifests=_expected_group_manifests(canonical_bundle),
    )
    assert canonical.expected_group_manifest.payload_sha256 == result.expected_group_manifest.payload_sha256
    assert canonical.expected_group_manifest.leg_instrument_ids == result.expected_group_manifest.leg_instrument_ids


def test_multi_group_account_snapshot_detects_order_group_crosswalk_mismatch(tmp_path):
    bundle = _multi_group_bundle()
    changed_orders = tuple(
        {**row, "group_id": GROUP_ID}
        if row["client_order_id"] == "client-g2-shared" else row
        for row in bundle.orders.rows
    )
    bundle = replace(bundle, orders=_section(bundle.orders.snapshot_id, AS_OF, changed_orders))
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path)
    _seed_second_group(reconciler)

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation,
        group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-order-crosswalk-mismatch", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MULTI-CROSSWALK",
        expected_group_manifests=_expected_group_manifests(bundle),
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_EXECUTION_GROUP_ORDER_MISMATCH:SYNTHETIC:G2-FILL-001" in result.issues
    assert result.recovery_decision is None


def test_multi_group_account_snapshot_detects_order_quantity_crosswalk_mismatch(tmp_path):
    bundle = _multi_group_bundle()
    changed_orders = tuple(
        {**row, "order_quantity": 3}
        if row["client_order_id"] == "client-g2-shared" else row
        for row in bundle.orders.rows
    )
    bundle = replace(bundle, orders=_section(bundle.orders.snapshot_id, AS_OF, changed_orders))
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path)
    _seed_second_group(reconciler)

    result = reconciler.reconcile_account(
        bundle=bundle, validation=validation,
        group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-order-quantity-mismatch", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:MULTI-ORDER-QTY",
        expected_group_manifests=_expected_group_manifests(bundle),
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_U19_ORDER_LINEAGE_MISMATCH:client-g2-shared" in result.issues
    assert result.recovery_decision is None


def test_multi_group_reconciliation_imports_validation_baseline_and_keeps_startup_gate_pending(tmp_path):
    import json
    import sqlite3

    from application.composition.validation_only_account_snapshot_baseline_adapter import (
        ValidationOnlyAccountSnapshotBaselineAdapter,
        ValidationOnlyBaselineImportError,
    )
    from application.composition.live_execution_position_composition_factory import (
        create_live_execution_position_composition,
    )

    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path)
    _seed_second_group(reconciler)
    reconciliation = reconciler.reconcile_account(
        bundle=bundle, validation=validation,
        group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-baseline-import", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:BASELINE-IMPORT",
        expected_group_manifests=_expected_group_manifests(bundle),
    )
    assert reconciliation.is_valid

    baseline_path = tmp_path / "validation-only-account-baseline.sqlite3"
    baseline_store = SQLiteSettlementStore(baseline_path)
    with pytest.raises(ValidationOnlyBaselineImportError, match="VALIDATION_ONLY_BASELINE_OPT_IN_REQUIRED"):
        ValidationOnlyAccountSnapshotBaselineAdapter(baseline_store)

    adapter = ValidationOnlyAccountSnapshotBaselineAdapter(baseline_store, validation_only=True)
    imported = adapter.import_reconciled_snapshot(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
    )

    assert imported.is_valid
    assert imported.imported_position_count == 2
    assert imported.startup_gate_status == "PENDING"
    unresolved = baseline_store.unresolved_reconciliations()
    assert [(item["scope_key"], item["status"]) for item in unresolved] == [
        ("__startup_reconciliation__", "PENDING"),
    ]
    with sqlite3.connect(baseline_path) as connection:
        bootstrap = connection.execute(
            "SELECT status FROM reconciliation_state WHERE scope_key='__runtime_bootstrap__'"
        ).fetchone()[0]
        evidence = json.loads(connection.execute(
            "SELECT value FROM settlement_meta WHERE key='authoritative_baseline_evidence'"
        ).fetchone()[0])
        positions = connection.execute(
            "SELECT instrument_id,position_json FROM position_states ORDER BY instrument_id"
        ).fetchall()
    assert bootstrap == "RESOLVED"
    assert evidence["source"] == "VALIDATION_ONLY:ACCOUNT_U19_BASELINE_IMPORT"
    assert evidence["payload_sha256"] == imported.evidence_sha256
    assert {item[0] for item in positions} == {SHARED_INSTRUMENT, SECOND_INSTRUMENT}

    # A fixture-only startup snapshot can exercise the gate API; this does not grant Live authority.
    assert baseline_store.resolve_startup_reconciliation(
        orders_snapshot_id=bundle.orders.snapshot_id,
        executions_snapshot_id=bundle.executions.snapshot_id,
        positions_snapshot_id=bundle.positions.snapshot_id,
        as_of=validation.as_of,
        source="VALIDATION_ONLY:STARTUP_GATE_FIXTURE",
        payload_sha256=imported.evidence_sha256,
        authoritative_evidence_ref=f"VALIDATION_ONLY:STARTUP_GATE:{imported.evidence_sha256}",
    )
    assert not baseline_store.has_unresolved_reconciliation()

    reopened = SQLiteSettlementStore(baseline_path)
    position = LivePositionAggregate(SHARED_INSTRUMENT)
    composition = create_live_execution_position_composition(
        execution_source=object(),
        order_state_machine=OrderStateMachine(),
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
        settlement_store=reopened,
    )
    assert composition.settlement_store is reopened
    restarted_gate = reopened.unresolved_reconciliations()
    assert [(item["scope_key"], item["status"]) for item in restarted_gate] == [
        ("__startup_reconciliation__", "PENDING"),
    ]


def test_validation_baseline_adapter_does_not_import_unreconciled_account(tmp_path):
    from application.composition.validation_only_account_snapshot_baseline_adapter import (
        ValidationOnlyAccountSnapshotBaselineAdapter,
        ValidationOnlyBaselineImportError,
    )

    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path)
    _seed_second_group(reconciler)
    changed = replace(
        bundle,
        positions=_section(
            bundle.positions.snapshot_id, AS_OF,
            tuple({**row, "quantity": 99} if row["instrument_id"] == SHARED_INSTRUMENT else row
                  for row in bundle.positions.rows),
        ),
    )
    invalid_validation = validate_account_snapshot_bundle(changed)
    assert not invalid_validation.is_valid
    baseline_store = SQLiteSettlementStore(tmp_path / "must-not-import.sqlite3")
    adapter = ValidationOnlyAccountSnapshotBaselineAdapter(baseline_store, validation_only=True)

    with pytest.raises(ValidationOnlyBaselineImportError, match="ACCOUNT_SNAPSHOT_VALIDATION_REQUIRED"):
        adapter.import_reconciled_snapshot(
            bundle=changed, validation=invalid_validation,
            reconciliation=object(),
        )

    assert not baseline_store.has_unresolved_reconciliation()
    with sqlite3.connect(baseline_store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM position_states").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM settlement_meta WHERE key='authoritative_baseline_ready'"
        ).fetchone()[0] == 0


def test_validation_baseline_adapter_rejects_stale_bundle_validation_before_import(tmp_path):
    from application.composition.validation_only_account_snapshot_baseline_adapter import (
        ValidationOnlyAccountSnapshotBaselineAdapter,
        ValidationOnlyBaselineImportError,
    )

    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    changed = replace(
        bundle,
        orders=_section("orders-account-revised", AS_OF, bundle.orders.rows),
    )
    baseline_store = SQLiteSettlementStore(tmp_path / "stale-baseline.sqlite3")
    adapter = ValidationOnlyAccountSnapshotBaselineAdapter(baseline_store, validation_only=True)

    with pytest.raises(ValidationOnlyBaselineImportError, match="ACCOUNT_SNAPSHOT_VALIDATION_STALE_OR_MISMATCHED"):
        adapter.import_reconciled_snapshot(
            bundle=changed, validation=validation,
            reconciliation=object(),
        )

    assert not baseline_store.has_unresolved_reconciliation()
    with sqlite3.connect(baseline_store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM position_states").fetchone()[0] == 0


def test_validation_baseline_adapter_rejects_u19_mismatch_without_import(tmp_path):
    from application.composition.validation_only_account_snapshot_baseline_adapter import (
        ValidationOnlyAccountSnapshotBaselineAdapter,
        ValidationOnlyBaselineImportError,
    )

    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path, old_first_fill_quantity=2)
    _seed_second_group(reconciler)
    reconciliation = reconciler.reconcile_account(
        bundle=bundle, validation=validation,
        group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-baseline-u19-mismatch", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:U19-MISMATCH",
        expected_group_manifests=_expected_group_manifests(bundle),
    )
    assert not reconciliation.is_valid
    baseline_store = SQLiteSettlementStore(tmp_path / "u19-mismatch-no-import.sqlite3")
    adapter = ValidationOnlyAccountSnapshotBaselineAdapter(baseline_store, validation_only=True)

    with pytest.raises(ValidationOnlyBaselineImportError, match="ACCOUNT_U19_RECONCILIATION_REQUIRED"):
        adapter.import_reconciled_snapshot(
            bundle=bundle, validation=validation, reconciliation=reconciliation,
        )

    assert not baseline_store.has_unresolved_reconciliation()
    with sqlite3.connect(baseline_store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM position_states").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM settlement_meta WHERE key='authoritative_baseline_ready'"
        ).fetchone()[0] == 0


def _prepare_validation_startup_fixture(tmp_path):
    from application.composition.validation_only_account_snapshot_baseline_adapter import (
        ValidationOnlyAccountSnapshotBaselineAdapter,
    )

    u19_dir = tmp_path / "u19-startup"
    u19_dir.mkdir()
    bundle = _multi_group_bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(u19_dir)
    _seed_second_group(reconciler)
    reconciliation = reconciler.reconcile_account(
        bundle=bundle, validation=validation,
        group_ids=(GROUP_ID, GROUP_TWO),
        snapshot_id="multi-group-startup-adapter", as_of=AS_OF,
        aggregate_group_id="SYNTHETIC:ACCOUNT_AGGREGATE:STARTUP-ADAPTER",
        expected_group_manifests=_expected_group_manifests(bundle),
    )
    assert reconciliation.is_valid
    store = SQLiteSettlementStore(tmp_path / "startup-settlement.sqlite3")
    baseline_adapter = ValidationOnlyAccountSnapshotBaselineAdapter(store, validation_only=True)
    baseline_import = baseline_adapter.import_reconciled_snapshot(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
    )
    assert baseline_import.is_valid
    return bundle, validation, reconciliation, baseline_import, store


def test_validation_only_startup_adapter_resolves_only_complete_clean_synthetic_evidence(tmp_path):
    import json

    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    with pytest.raises(ValueError, match="VALIDATION_ONLY_STARTUP_OPT_IN_REQUIRED"):
        ValidationOnlyAccountSnapshotStartupAdapter(store)

    adapter = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True)
    result = adapter.reconcile_startup(
        bundle=bundle, validation=validation,
        reconciliation=reconciliation, baseline_import=baseline_import,
    )
    assert result.is_valid
    assert result.status == "VALIDATION_ONLY_STARTUP_RECONCILED"
    assert result.resolved is True
    assert result.evidence_sha256 and len(result.evidence_sha256) == 64
    assert not store.has_unresolved_reconciliation()
    with sqlite3.connect(store.path) as connection:
        evidence = json.loads(connection.execute(
            "SELECT value FROM settlement_meta WHERE key='startup_reconciliation_evidence'"
        ).fetchone()[0])
    assert evidence["source"] == "VALIDATION_ONLY:ACCOUNT_U19_STARTUP_RECONCILIATION"
    assert evidence["coverage"] == ["orders", "fills", "positions"]
    assert evidence["payload_sha256"] == result.evidence_sha256


def test_validation_only_startup_adapter_keeps_gate_pending_until_every_inbox_event_is_resolved(tmp_path):
    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    store.record_reconciliation_event_pending(
        event_id="SYNTHETIC:STARTUP-LATE-FILL-001",
        client_order_id="client-late-fill",
        broker_order_id="broker-late-fill",
        event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
        payload={"cumulative_filled_quantity": 1, "source_authority": "VALIDATION_ONLY"},
    )
    adapter = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True)
    pending = adapter.reconcile_startup(
        bundle=bundle, validation=validation,
        reconciliation=reconciliation, baseline_import=baseline_import,
    )
    assert pending.status == "RECONCILIATION_REQUIRED"
    assert pending.resolved is False
    assert any("OPEN_RECONCILIATION_INBOX:SYNTHETIC:STARTUP-LATE-FILL-001:PENDING" == item for item in pending.issues)
    assert any(
        item["scope_key"] == "__startup_reconciliation__" and item["status"] == "PENDING"
        for item in store.unresolved_reconciliations()
    )

    store.resolve_reconciliation_event(
        event_id="SYNTHETIC:STARTUP-LATE-FILL-001",
        scope_key="client-late-fill",
        evidence_ref="VALIDATION_ONLY:INDEPENDENT-LATE-FILL-CROSSCHECK",
    )
    resolved = adapter.reconcile_startup(
        bundle=bundle, validation=validation,
        reconciliation=reconciliation, baseline_import=baseline_import,
    )
    assert resolved.is_valid
    assert resolved.resolved is True


def test_validation_only_startup_adapter_never_clears_conflicts_or_other_unresolved_scopes(tmp_path):
    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    adapter = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True)
    store.mark_reconciliation_pending(
        scope_key="client-unresolved-order",
        client_order_id="client-unresolved-order",
        broker_order_id="broker-unresolved-order",
        reason="TEST_UNRESOLVED_ORDER",
        payload={"synthetic": True},
    )
    pending = adapter.reconcile_startup(
        bundle=bundle, validation=validation,
        reconciliation=reconciliation, baseline_import=baseline_import,
    )
    assert pending.status == "RECONCILIATION_REQUIRED"
    assert any("OTHER_UNRESOLVED_RECONCILIATION:client-unresolved-order:PENDING" == item for item in pending.issues)
    assert any(item["scope_key"] == "client-unresolved-order" for item in store.unresolved_reconciliations())

    # Clear the test-only scope using the dedicated per-scope evidence API.
    store.resolve_reconciliation(
        scope_key="client-unresolved-order",
        authoritative_evidence_ref="VALIDATION_ONLY:MANUAL-CROSSCHECK",
    )
    store.mark_reconciliation_pending(
        scope_key="__startup_reconciliation__",
        client_order_id="__startup_reconciliation__",
        broker_order_id=None,
        reason="TEST_STARTUP_CONFLICT",
        payload={"conflict": True},
        conflict=True,
    )
    conflict = adapter.reconcile_startup(
        bundle=bundle, validation=validation,
        reconciliation=reconciliation, baseline_import=baseline_import,
    )
    assert conflict.status == "RECONCILIATION_REQUIRED"
    assert conflict.issues == ("STARTUP_GATE_CONFLICT_REQUIRES_MANUAL_REVIEW",)
    assert any(
        item["scope_key"] == "__startup_reconciliation__" and item["status"] == "CONFLICT"
        for item in store.unresolved_reconciliations()
    )


def test_validation_only_startup_adapter_rechecks_snapshot_and_u19_before_gate_resolution(tmp_path):
    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    adapter = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True)
    changed = replace(
        bundle,
        executions=_section("executions-startup-mutated", AS_OF, bundle.executions.rows),
    )
    stale = adapter.reconcile_startup(
        bundle=changed, validation=validation,
        reconciliation=reconciliation, baseline_import=baseline_import,
    )
    assert stale.status == "RECONCILIATION_REQUIRED"
    assert stale.issues == ("ACCOUNT_SNAPSHOT_VALIDATION_STALE_OR_MISMATCHED",)
    assert any(
        item["scope_key"] == "__startup_reconciliation__" and item["status"] == "PENDING"
        for item in store.unresolved_reconciliations()
    )

    mismatched = replace(reconciliation, status="RECONCILIATION_REQUIRED", issues=("TEST_U19_MISMATCH",))
    rejected = adapter.reconcile_startup(
        bundle=bundle, validation=validation,
        reconciliation=mismatched, baseline_import=baseline_import,
    )
    assert rejected.status == "RECONCILIATION_REQUIRED"
    assert rejected.issues == ("ACCOUNT_U19_RECONCILIATION_REQUIRED",)
    assert any(
        item["scope_key"] == "__startup_reconciliation__" and item["status"] == "PENDING"
        for item in store.unresolved_reconciliations()
    )


def test_validation_only_startup_adapter_keeps_gate_pending_for_unreconciled_u19_orders(tmp_path):
    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    pending_ledger = replace(
        reconciliation.ledger_snapshot,
        pending_order_ids=("SYNTHETIC:PENDING-LATE-FILL-ORDER",),
    )
    pending_reconciliation = replace(reconciliation, ledger_snapshot=pending_ledger)
    adapter = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True)
    result = adapter.reconcile_startup(
        bundle=bundle, validation=validation,
        reconciliation=pending_reconciliation, baseline_import=baseline_import,
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert any("U19_PENDING_ORDERS:" in issue for issue in result.issues)
    assert any(
        item["scope_key"] == "__startup_reconciliation__" and item["status"] == "PENDING"
        for item in store.unresolved_reconciliations()
    )


def test_validation_only_startup_adapter_does_not_resolve_conflicting_inbox_event(tmp_path):
    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    store.record_reconciliation_event_pending(
        event_id="SYNTHETIC:STARTUP-CONFLICT-EVENT",
        client_order_id="client-conflict",
        broker_order_id="broker-conflict",
        event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
        payload={"cumulative_filled_quantity": 2, "source_authority": "VALIDATION_ONLY"},
    )
    store.mark_reconciliation_pending(
        scope_key="client-conflict",
        client_order_id="client-conflict",
        broker_order_id="broker-conflict",
        reason="TEST_INBOX_CONFLICT",
        payload={"conflict": True},
        conflict=True,
    )
    adapter = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True)
    result = adapter.reconcile_startup(
        bundle=bundle, validation=validation,
        reconciliation=reconciliation, baseline_import=baseline_import,
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert any("OPEN_RECONCILIATION_INBOX:SYNTHETIC:STARTUP-CONFLICT-EVENT:PENDING" == issue for issue in result.issues)
    assert any(
        item["scope_key"] == "client-conflict" and item["status"] == "CONFLICT"
        for item in store.unresolved_reconciliations()
    )
    assert any(
        item["execution_id"] == "SYNTHETIC:STARTUP-CONFLICT-EVENT" and item["status"] == "PENDING"
        for item in store.open_reconciliation_events()
    )


def test_validation_baseline_import_is_idempotent_and_rejects_changed_evidence(tmp_path):
    from application.composition.validation_only_account_snapshot_baseline_adapter import (
        ValidationOnlyAccountSnapshotBaselineAdapter,
        ValidationOnlyBaselineImportError,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    adapter = ValidationOnlyAccountSnapshotBaselineAdapter(store, validation_only=True)
    repeated = adapter.import_reconciled_snapshot(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
    )
    assert repeated.is_valid
    assert repeated.status == "VALIDATION_ONLY_BASELINE_ALREADY_IMPORTED"
    assert repeated.evidence_sha256 == baseline_import.evidence_sha256
    assert repeated.startup_gate_status == "PENDING"

    changed_bundle = replace(
        bundle,
        provenance=replace(bundle.provenance, deterministic_rule_id="different-deterministic-rule"),
    )
    changed_validation = validate_account_snapshot_bundle(changed_bundle)
    assert changed_validation.is_valid
    with pytest.raises(ValidationOnlyBaselineImportError, match="BASELINE_EVIDENCE_IDEMPOTENCY_CONFLICT"):
        adapter.import_reconciled_snapshot(
            bundle=changed_bundle, validation=changed_validation, reconciliation=reconciliation,
        )
    assert store.authoritative_baseline_evidence()["payload_sha256"] == baseline_import.evidence_sha256


def test_validation_startup_lineage_manifest_persists_and_is_idempotent_after_sqlite_reopen(tmp_path):
    import hashlib
    import json

    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    adapter = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True)
    first = adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert first.is_valid and first.resolved
    persisted = store.startup_reconciliation_evidence()
    manifest = persisted["lineage_manifest"]
    assert manifest["baseline_import_evidence_sha256"] == baseline_import.evidence_sha256
    assert manifest["snapshot_validation_evidence_sha256"] == validation.evidence_sha256
    assert manifest["snapshot_ids"] == [
        bundle.orders.snapshot_id, bundle.executions.snapshot_id, bundle.positions.snapshot_id,
    ]
    assert manifest["u19_snapshot_ids"]
    assert manifest["new_entry_enabled"] is False
    assert manifest["order_submission_enabled"] is False
    expected_digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert expected_digest == first.evidence_sha256 == persisted["payload_sha256"]

    repeated = adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert repeated.status == "VALIDATION_ONLY_STARTUP_ALREADY_RECONCILED"
    assert repeated.evidence_sha256 == first.evidence_sha256

    reopened = SQLiteSettlementStore(store.path)
    reopened_adapter = ValidationOnlyAccountSnapshotStartupAdapter(reopened, validation_only=True)
    after_restart = reopened_adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert after_restart.status == "VALIDATION_ONLY_STARTUP_ALREADY_RECONCILED"
    assert after_restart.evidence_sha256 == first.evidence_sha256


def test_validation_startup_rejects_changed_evidence_reuse_until_gate_is_rearmed(tmp_path):
    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    adapter = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True)
    first = adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert first.is_valid

    changed_baseline = replace(baseline_import, evidence_sha256="f" * 64)
    changed = adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=changed_baseline,
    )
    assert changed.status == "RECONCILIATION_REQUIRED"
    assert changed.issues == ("VALIDATION_ONLY_BASELINE_PERSISTED_EVIDENCE_MISMATCH",)

    store.mark_startup_reconciliation_pending()
    assert store.reconciliation_status("__startup_reconciliation__") == "PENDING"
    accepted_after_new_gate = adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert accepted_after_new_gate.is_valid
    assert accepted_after_new_gate.resolved


def test_fresh_live_composition_rearms_startup_gate_without_enabling_orders(tmp_path):
    from application.composition.live_execution_position_composition_factory import (
        create_live_execution_position_composition,
    )
    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    adapter = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True)
    resolved = adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert resolved.is_valid
    assert store.reconciliation_status("__startup_reconciliation__") == "RESOLVED"

    position = LivePositionAggregate(SHARED_INSTRUMENT)
    composition = create_live_execution_position_composition(
        execution_source=object(),
        order_state_machine=OrderStateMachine(),
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
        settlement_store=SQLiteSettlementStore(store.path),
    )
    assert composition.settlement_store.reconciliation_status("__startup_reconciliation__") == "PENDING"
    rearmed = adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert rearmed.is_valid and rearmed.resolved
    assert composition.settlement_store.reconciliation_status("__startup_reconciliation__") == "RESOLVED"


def test_validation_startup_keeps_unresolved_inbox_and_conflict_after_sqlite_reopen(tmp_path):
    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    store.record_reconciliation_event_pending(
        event_id="SYNTHETIC:PERSISTED-LATE-FILL",
        client_order_id="client-persisted-late-fill",
        broker_order_id="broker-persisted-late-fill",
        event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
        payload={"cumulative_filled_quantity": 1, "source_authority": "VALIDATION_ONLY"},
    )
    store.mark_reconciliation_pending(
        scope_key="client-persisted-late-fill",
        client_order_id="client-persisted-late-fill",
        broker_order_id="broker-persisted-late-fill",
        reason="PERSISTED_LATE_FILL_CONFLICT",
        payload={"conflict": True},
        conflict=True,
    )

    reopened = SQLiteSettlementStore(store.path)
    adapter = ValidationOnlyAccountSnapshotStartupAdapter(reopened, validation_only=True)
    result = adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert result.status == "RECONCILIATION_REQUIRED"
    assert any("OPEN_RECONCILIATION_INBOX:SYNTHETIC:PERSISTED-LATE-FILL:PENDING" == issue for issue in result.issues)
    assert any(
        item["scope_key"] == "client-persisted-late-fill" and item["status"] == "CONFLICT"
        for item in reopened.unresolved_reconciliations()
    )
    assert any(
        item["execution_id"] == "SYNTHETIC:PERSISTED-LATE-FILL" and item["status"] == "PENDING"
        for item in reopened.open_reconciliation_events()
    )
    assert reopened.reconciliation_status("__startup_reconciliation__") == "PENDING"


def test_startup_lineage_audit_tracks_three_restart_cycles_and_is_append_only(tmp_path):
    import sqlite3

    from application.composition.live_execution_position_composition_factory import (
        create_live_execution_position_composition,
    )
    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    adapter = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True)
    first = adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert first.is_valid and first.resolved

    for _ in range(2):
        reopened = SQLiteSettlementStore(store.path)
        position = LivePositionAggregate(SHARED_INSTRUMENT)
        composition = create_live_execution_position_composition(
            execution_source=object(),
            order_state_machine=OrderStateMachine(),
            position_fill_adapter=LivePositionFillAdapter(position),
            execution_event_deduplicator=ExecutionEventDeduplicator(),
            position_aggregate=position,
            settlement_store=reopened,
        )
        assert composition.settlement_store.reconciliation_status("__startup_reconciliation__") == "PENDING"
        cycle_adapter = ValidationOnlyAccountSnapshotStartupAdapter(
            composition.settlement_store, validation_only=True,
        )
        result = cycle_adapter.reconcile_startup(
            bundle=bundle, validation=validation, reconciliation=reconciliation,
            baseline_import=baseline_import,
        )
        assert result.is_valid and result.resolved

    final_store = SQLiteSettlementStore(store.path)
    final_adapter = ValidationOnlyAccountSnapshotStartupAdapter(final_store, validation_only=True)
    repeated = final_adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert repeated.status == "VALIDATION_ONLY_STARTUP_ALREADY_RECONCILED"

    audit = final_store.startup_lineage_audit()
    assert audit["current_gate_status"] == "RESOLVED"
    assert audit["resolution_count"] == 3
    assert audit["history_count"] == 6
    assert audit["open_inbox_count"] == 0
    assert audit["unresolved_scope_count"] == 0
    assert [event["event_type"] for event in audit["history"]].count("GATE_REGISTERED") == 1
    assert [event["event_type"] for event in audit["history"]].count("GATE_REARMED") == 2
    assert all(
        event["lineage_status"] == "SUPPORTED_CURRENT_BASELINE"
        for event in audit["history"] if event["event_type"] == "STARTUP_RESOLVED"
    )

    with sqlite3.connect(final_store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="STARTUP_RECONCILIATION_HISTORY_APPEND_ONLY"):
            connection.execute("UPDATE startup_reconciliation_history SET gate_status='PENDING' WHERE event_id=1")
        with pytest.raises(sqlite3.IntegrityError, match="STARTUP_RECONCILIATION_HISTORY_APPEND_ONLY"):
            connection.execute("DELETE FROM startup_reconciliation_history WHERE event_id=1")


def test_startup_lineage_audit_marks_unknown_manifest_version_without_changing_gate(tmp_path):
    import sqlite3

    from environments.live.settlement.sqlite_settlement_store import encode_record
    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    result = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True).reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert result.is_valid and result.resolved

    future_manifest = {"manifest_version": "Q25-A8-U19-BASELINE-STARTUP-LINEAGE-v999"}
    payload = {
        "payload_sha256": "0" * 64,
        "lineage_manifest": future_manifest,
    }
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """INSERT INTO startup_reconciliation_history
               (event_type,gate_status,evidence_sha256,manifest_version,
                baseline_evidence_sha256,payload_json)
               VALUES('STARTUP_RESOLVED','RESOLVED',?,?,?,?)""",
            (
                "0" * 64, future_manifest["manifest_version"],
                baseline_import.evidence_sha256, encode_record(payload),
            ),
        )

    audit = store.startup_lineage_audit()
    assert audit["current_gate_status"] == "RESOLVED"
    assert audit["history"][-1]["lineage_status"] == "UNSUPPORTED_MANIFEST_VERSION"


def test_startup_lineage_audit_detects_baseline_evidence_replacement(tmp_path):
    import json
    import sqlite3

    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    result = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True).reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert result.is_valid and result.resolved

    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT value FROM settlement_meta WHERE key='authoritative_baseline_evidence'"
        ).fetchone()
        evidence = json.loads(row[0])
        evidence["payload_sha256"] = "f" * 64
        connection.execute(
            "UPDATE settlement_meta SET value=? WHERE key='authoritative_baseline_evidence'",
            (json.dumps(evidence, sort_keys=True, separators=(",", ":")),),
        )

    audit = store.startup_lineage_audit()
    resolved_events = [item for item in audit["history"] if item["event_type"] == "STARTUP_RESOLVED"]
    assert resolved_events
    assert all(
        item["lineage_status"] == "BASELINE_EVIDENCE_CHANGED_SINCE_RESOLUTION"
        for item in resolved_events
    )
    assert audit["current_gate_status"] == "RESOLVED"


def test_validation_baseline_import_rejects_changed_snapshot_ids_without_overwriting_baseline(tmp_path):
    from application.composition.validation_only_account_snapshot_baseline_adapter import (
        ValidationOnlyAccountSnapshotBaselineAdapter,
        ValidationOnlyBaselineImportError,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    changed_bundle = replace(
        bundle,
        orders=_section("orders-new-snapshot-cycle", AS_OF, bundle.orders.rows),
    )
    changed_validation = validate_account_snapshot_bundle(changed_bundle)
    assert changed_validation.is_valid
    adapter = ValidationOnlyAccountSnapshotBaselineAdapter(store, validation_only=True)
    with pytest.raises(ValidationOnlyBaselineImportError, match="BASELINE_EVIDENCE_IDEMPOTENCY_CONFLICT"):
        adapter.import_reconciled_snapshot(
            bundle=changed_bundle, validation=changed_validation, reconciliation=reconciliation,
        )
    persisted = store.authoritative_baseline_evidence()
    assert persisted["orders_snapshot_id"] == bundle.orders.snapshot_id
    assert persisted["payload_sha256"] == baseline_import.evidence_sha256


def test_startup_lineage_audit_surfaces_legacy_unversioned_evidence_without_mutation(tmp_path):
    import sqlite3

    from environments.live.settlement.sqlite_settlement_store import encode_record

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    legacy = {
        "source": "VALIDATION_ONLY:LEGACY_STARTUP",
        "payload_sha256": "a" * 64,
        "orders_snapshot_id": bundle.orders.snapshot_id,
        "executions_snapshot_id": bundle.executions.snapshot_id,
        "positions_snapshot_id": bundle.positions.snapshot_id,
    }
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """INSERT INTO settlement_meta(key,value) VALUES('startup_reconciliation_evidence',?)""",
            (encode_record(legacy),),
        )

    audit = store.startup_lineage_audit()
    assert audit["current_gate_status"] == "PENDING"
    legacy_events = [item for item in audit["history"] if item["event_type"] == "LEGACY_EXISTING_EVIDENCE"]
    assert len(legacy_events) == 1
    assert legacy_events[0]["lineage_status"] == "LEGACY_UNVERSIONED"
    assert store.reconciliation_status("__startup_reconciliation__") == "PENDING"


def test_startup_lineage_audit_detects_manifest_hash_mismatch(tmp_path):
    import sqlite3

    from environments.live.settlement.sqlite_settlement_store import encode_record

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    manifest = {
        "manifest_version": "Q25-A8-U19-BASELINE-STARTUP-LINEAGE-v1",
        "baseline_import_evidence_sha256": baseline_import.evidence_sha256,
    }
    payload = {"payload_sha256": "0" * 64, "lineage_manifest": manifest}
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """INSERT INTO startup_reconciliation_history
               (event_type,gate_status,evidence_sha256,manifest_version,
                baseline_evidence_sha256,payload_json)
               VALUES('STARTUP_RESOLVED','RESOLVED',?,?,?,?)""",
            (
                "0" * 64, manifest["manifest_version"],
                baseline_import.evidence_sha256, encode_record(payload),
            ),
        )

    audit = store.startup_lineage_audit()
    assert audit["current_gate_status"] == "PENDING"
    assert audit["history"][-1]["lineage_status"] == "MANIFEST_HASH_MISMATCH"


def test_validation_only_baseline_generation_reset_preserves_history_and_reconciles_new_manifest(tmp_path):
    from application.composition.validation_only_account_snapshot_baseline_adapter import (
        ValidationOnlyAccountSnapshotBaselineAdapter,
    )
    from application.composition.validation_only_account_snapshot_startup_adapter import (
        ValidationOnlyAccountSnapshotStartupAdapter,
    )

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    startup_adapter = ValidationOnlyAccountSnapshotStartupAdapter(store, validation_only=True)
    first_startup = startup_adapter.reconcile_startup(
        bundle=bundle, validation=validation, reconciliation=reconciliation,
        baseline_import=baseline_import,
    )
    assert first_startup.is_valid and first_startup.resolved

    changed_bundle = replace(
        bundle,
        orders=replace(bundle.orders, snapshot_id="orders-generation-2"),
        executions=replace(bundle.executions, snapshot_id="executions-generation-2"),
        positions=replace(bundle.positions, snapshot_id="positions-generation-2"),
        provenance=replace(
            bundle.provenance,
            deterministic_rule_id="SYNTHETIC-ACCOUNT-REPLAY-RULE-v2",
        ),
    )
    changed_validation = validate_account_snapshot_bundle(changed_bundle)
    assert changed_validation.is_valid
    reset_result = ValidationOnlyAccountSnapshotBaselineAdapter(
        store, validation_only=True,
    ).import_reconciled_snapshot(
        bundle=changed_bundle,
        validation=changed_validation,
        reconciliation=reconciliation,
        expected_previous_evidence_sha256=baseline_import.evidence_sha256,
        reset_reason="VALIDATION_ONLY_NEW_SNAPSHOT_GENERATION_AFTER_SOURCE_CROSSCHECK",
    )
    assert reset_result.status == "VALIDATION_ONLY_BASELINE_GENERATION_REPLACED_STARTUP_PENDING"
    assert reset_result.evidence_sha256 != baseline_import.evidence_sha256
    assert store.reconciliation_status("__startup_reconciliation__") == "PENDING"

    second_startup = startup_adapter.reconcile_startup(
        bundle=changed_bundle,
        validation=changed_validation,
        reconciliation=reconciliation,
        baseline_import=reset_result,
    )
    assert second_startup.is_valid and second_startup.resolved

    history = store.validation_baseline_history()
    assert len(history) == 2
    assert history[0]["event_type"] == "INITIAL_IMPORT"
    assert history[1]["event_type"] == "VALIDATION_ONLY_RESET"
    assert history[1]["previous_payload_sha256"] == baseline_import.evidence_sha256
    assert history[1]["new_payload_sha256"] == reset_result.evidence_sha256
    assert history[1]["reset_reason"] == "VALIDATION_ONLY_NEW_SNAPSHOT_GENERATION_AFTER_SOURCE_CROSSCHECK"

    baseline_audit = store.validation_baseline_lineage_audit()
    assert baseline_audit["generation_count"] == 2
    assert baseline_audit["history_chain_valid"] is True
    assert baseline_audit["current_baseline_matches_latest_generation"] is True
    assert all(item["lineage_status"] == "CHAIN_VALID" for item in baseline_audit["history"])

    audit = store.startup_lineage_audit()
    assert audit["baseline_lineage"]["history_chain_valid"] is True
    resolutions = [item for item in audit["history"] if item["event_type"] == "STARTUP_RESOLVED"]
    assert len(resolutions) == 2
    assert resolutions[0]["lineage_status"] == "BASELINE_EVIDENCE_CHANGED_SINCE_RESOLUTION"
    assert resolutions[1]["lineage_status"] == "SUPPORTED_CURRENT_BASELINE"
    assert audit["current_gate_status"] == "RESOLVED"


def test_validation_only_baseline_reset_rejects_position_changes_without_mutation(tmp_path):
    from environments.live.settlement.sqlite_settlement_store import SettlementStoreError

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    positions = validation.baseline_positions_payload()
    changed_positions = [dict(item) for item in positions]
    changed_positions[0]["qty"] = int(changed_positions[0]["qty"]) + 1
    with pytest.raises(SettlementStoreError, match="BASELINE_RESET_POSITION_STATE_CHANGE_REQUIRES_SEPARATE_RECONCILIATION"):
        store.replace_validation_only_baseline_snapshot(
            positions_payload=changed_positions,
            orders_snapshot_id="orders-position-change",
            executions_snapshot_id="executions-position-change",
            positions_snapshot_id="positions-position-change",
            as_of=validation.as_of,
            source="VALIDATION_ONLY:ACCOUNT_U19_BASELINE_IMPORT",
            payload_sha256="b" * 64,
            authoritative_evidence_ref="VALIDATION_ONLY:RESET_POSITION_CHANGE",
            expected_previous_payload_sha256=baseline_import.evidence_sha256,
            reset_reason="TEST_POSITION_CHANGE_MUST_NOT_BE_SILENTLY_ACCEPTED",
        )
    assert store.authoritative_baseline_evidence()["payload_sha256"] == baseline_import.evidence_sha256
    assert len(store.validation_baseline_history()) == 1
    assert store.reconciliation_status("__startup_reconciliation__") == "PENDING"


def test_validation_only_baseline_reset_preserves_pending_inbox_and_conflict(tmp_path):
    from environments.live.settlement.sqlite_settlement_store import SettlementStoreError

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    store.record_reconciliation_event_pending(
        event_id="SYNTHETIC:RESET-LATE-FILL",
        client_order_id="client-reset-pending",
        broker_order_id="broker-reset-pending",
        event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
        payload={"cumulative_filled_quantity": 1},
    )
    with pytest.raises(SettlementStoreError, match="BASELINE_IMPORT_HAS_OTHER_UNRESOLVED_RECONCILIATION"):
        store.replace_validation_only_baseline_snapshot(
            positions_payload=validation.baseline_positions_payload(),
            orders_snapshot_id="orders-reset-pending",
            executions_snapshot_id="executions-reset-pending",
            positions_snapshot_id="positions-reset-pending",
            as_of=validation.as_of,
            source="VALIDATION_ONLY:ACCOUNT_U19_BASELINE_IMPORT",
            payload_sha256="c" * 64,
            authoritative_evidence_ref="VALIDATION_ONLY:RESET_PENDING",
            expected_previous_payload_sha256=baseline_import.evidence_sha256,
            reset_reason="TEST_PENDING_INBOX_MUST_REMAIN_OPEN",
        )
    assert store.authoritative_baseline_evidence()["payload_sha256"] == baseline_import.evidence_sha256
    assert store.open_reconciliation_events()[0]["status"] == "PENDING"
    assert len(store.validation_baseline_history()) == 1


def test_validation_only_baseline_reset_rejects_persisted_orders_and_startup_conflict(tmp_path):
    from environments.live.settlement.sqlite_settlement_store import SettlementStoreError

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    store.save_order_state("client-existing-order", {"status": "FILLED"})
    with pytest.raises(SettlementStoreError, match="BASELINE_RESET_PERSISTED_ORDERS_PRESENT"):
        store.replace_validation_only_baseline_snapshot(
            positions_payload=validation.baseline_positions_payload(),
            orders_snapshot_id="orders-reset-order",
            executions_snapshot_id="executions-reset-order",
            positions_snapshot_id="positions-reset-order",
            as_of=validation.as_of,
            source="VALIDATION_ONLY:ACCOUNT_U19_BASELINE_IMPORT",
            payload_sha256="d" * 64,
            authoritative_evidence_ref="VALIDATION_ONLY:RESET_ORDER",
            expected_previous_payload_sha256=baseline_import.evidence_sha256,
            reset_reason="TEST_EXISTING_ORDER_STATE_MUST_BLOCK_RESET",
        )
    assert store.authoritative_baseline_evidence()["payload_sha256"] == baseline_import.evidence_sha256

    conflict_dir = tmp_path / "conflict-case"
    conflict_dir.mkdir()
    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(
        conflict_dir
    )
    store.mark_reconciliation_pending(
        scope_key="__startup_reconciliation__",
        client_order_id="__startup_reconciliation__",
        broker_order_id=None,
        reason="TEST_STARTUP_CONFLICT",
        payload={"conflict": True},
        conflict=True,
    )
    with pytest.raises(SettlementStoreError, match="BASELINE_RESET_STARTUP_CONFLICT_REQUIRES_MANUAL_REVIEW"):
        store.replace_validation_only_baseline_snapshot(
            positions_payload=validation.baseline_positions_payload(),
            orders_snapshot_id="orders-reset-conflict",
            executions_snapshot_id="executions-reset-conflict",
            positions_snapshot_id="positions-reset-conflict",
            as_of=validation.as_of,
            source="VALIDATION_ONLY:ACCOUNT_U19_BASELINE_IMPORT",
            payload_sha256="e" * 64,
            authoritative_evidence_ref="VALIDATION_ONLY:RESET_CONFLICT",
            expected_previous_payload_sha256=baseline_import.evidence_sha256,
            reset_reason="TEST_CONFLICT_MUST_REMAIN_MANUAL",
        )
    assert store.reconciliation_status("__startup_reconciliation__") == "CONFLICT"
    assert store.authoritative_baseline_evidence()["payload_sha256"] == baseline_import.evidence_sha256
    assert len(store.validation_baseline_history()) == 1


def test_validation_baseline_history_is_append_only_after_reset(tmp_path):
    import sqlite3
    from environments.live.settlement.sqlite_settlement_store import SettlementStoreError

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    store.replace_validation_only_baseline_snapshot(
        positions_payload=validation.baseline_positions_payload(),
        orders_snapshot_id="orders-reset-same-position",
        executions_snapshot_id="executions-reset-same-position",
        positions_snapshot_id="positions-reset-same-position",
        as_of=validation.as_of,
        source="VALIDATION_ONLY:ACCOUNT_U19_BASELINE_IMPORT",
        payload_sha256="9" * 64,
        authoritative_evidence_ref="VALIDATION_ONLY:RESET_SAME_POSITION",
        expected_previous_payload_sha256=baseline_import.evidence_sha256,
        reset_reason="TEST_EXPLICIT_NEW_SNAPSHOT_GENERATION",
    )
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="VALIDATION_BASELINE_HISTORY_APPEND_ONLY"):
            connection.execute(
                "UPDATE validation_baseline_history SET reset_reason='rewritten' WHERE generation_id=1"
            )
        with pytest.raises(sqlite3.IntegrityError, match="VALIDATION_BASELINE_HISTORY_APPEND_ONLY"):
            connection.execute("DELETE FROM validation_baseline_history WHERE generation_id=1")


def test_validation_baseline_lineage_audit_detects_current_generation_hash_replacement(tmp_path):
    import json
    import sqlite3

    bundle, validation, reconciliation, baseline_import, store = _prepare_validation_startup_fixture(tmp_path)
    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT value FROM settlement_meta WHERE key='authoritative_baseline_evidence'"
        ).fetchone()
        payload = json.loads(row[0])
        payload["payload_sha256"] = "f" * 64
        connection.execute(
            "UPDATE settlement_meta SET value=? WHERE key='authoritative_baseline_evidence'",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
        )

    audit = store.validation_baseline_lineage_audit()
    assert audit["generation_count"] == 1
    assert audit["history_chain_valid"] is False
    assert audit["current_baseline_matches_latest_generation"] is False
    assert audit["history"][0]["lineage_status"] == "CHAIN_VALID"
