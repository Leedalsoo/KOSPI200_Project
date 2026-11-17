from decimal import Decimal
from types import SimpleNamespace

import pytest

from environments.live.execution.kis_futures_execution_recovery_adapter import (
    KISExecutionRecoveryQuery,
    KISFuturesExecutionRecoveryAdapter,
)
from environments.live.execution.live_execution_recovery_service import (
    LiveExecutionRecoveryService,
    RecoveryReconciliationHandlerRequired,
)
from environments.live.settlement.sqlite_settlement_store import SQLiteSettlementStore


class _RecoveryTransport:
    def inquire(self, query):
        assert query.virtual is True
        return {
            "output1": [
                {
                    "odno": "broker-order-1",
                    "tot_ccld_qty": "2",
                    "avg_idx": "10.50",
                    "ord_dt": "20261118",
                    "ord_tmd": "093000",
                },
                {
                    "odno": "broker-order-1",
                    "tot_ccld_qty": "3",
                    "avg_idx": "10.60",
                    "ord_dt": "20261118",
                    "ord_tmd": "093001",
                },
            ]
        }


class _CorrelationProvider:
    def resolve(self, broker_order_id):
        assert broker_order_id == "broker-order-1"
        return SimpleNamespace(
            client_order_id="client-order-1",
            order_quantity=5,
            prior_filled_quantity=1,
            prior_average_price=Decimal("10.00"),
        )


def _query():
    return KISExecutionRecoveryQuery(
        cano="TEST-CANO",
        account_product_code="TEST-PRODUCT",
        start_order_date="20261118",
        end_order_date="20261118",
        virtual=True,
    )


def test_rest_cumulative_snapshots_route_to_inbox_not_execution_or_position(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "recovery-snapshots.sqlite3")
    individual_reports = []
    cumulative_seen = []

    def on_snapshot(report, cumulative):
        cumulative_seen.append(cumulative)
        return store.record_reconciliation_event_pending(
            event_id=report.execution_id,
            client_order_id=report.client_order_id,
            broker_order_id=report.broker_order_id,
            event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
            payload={
                "snapshot_identity": report.execution_id,
                "delta_quantity_from_prior_snapshot": report.filled_quantity,
                "cumulative_filled_quantity": cumulative,
                "remaining_quantity": report.remaining_quantity,
                "delta_average_price": str(report.execution_price),
                "source_execution_timestamp": report.execution_timestamp.isoformat(),
                "source_execution_timestamp_timezone": "UNSPECIFIED",
                "source_authority": "KIS_REST_ORDER_LEVEL_SNAPSHOT_NOT_INDIVIDUAL_EXECUTION",
                "execution_journal_commit": False,
                "position_mutation": False,
            },
        )

    service = LiveExecutionRecoveryService(
        transport=_RecoveryTransport(),
        adapter=KISFuturesExecutionRecoveryAdapter(),
        correlation_provider=_CorrelationProvider(),
        on_report=individual_reports.append,
        on_reconciliation_required=on_snapshot,
    )
    results = service.recover(_query())

    assert results == (True, True)
    assert cumulative_seen == [2, 3]
    assert individual_reports == []
    assert store.load_execution_journal_records() == ()
    assert store.load_position_state("OPT-NOT-TOUCHED") is None
    events = store.open_reconciliation_events(scope_key="client-order-1")
    assert len(events) == 2
    assert all(event["payload"]["execution_journal_commit"] is False for event in events)
    assert all(event["payload"]["position_mutation"] is False for event in events)
    assert all(event["payload"]["source_execution_timestamp_timezone"] == "UNSPECIFIED" for event in events)

    # Same REST snapshot page is idempotent in the reconciliation inbox.
    assert service.recover(_query()) == (False, False)
    assert len(store.open_reconciliation_events(scope_key="client-order-1")) == 2


def test_rest_cumulative_snapshot_without_reconciliation_handler_never_reaches_fill_callback():
    individual_reports = []
    service = LiveExecutionRecoveryService(
        transport=_RecoveryTransport(),
        adapter=KISFuturesExecutionRecoveryAdapter(),
        correlation_provider=_CorrelationProvider(),
        on_report=individual_reports.append,
    )
    with pytest.raises(
        RecoveryReconciliationHandlerRequired,
        match="KIS_REST_ORDER_SNAPSHOT_REQUIRES_RECONCILIATION_HANDLER",
    ):
        service.recover(_query())
    assert individual_reports == []
from datetime import datetime, timezone
from decimal import Decimal
import hashlib

from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionLedgerSnapshot,
    U19RecoveryStatus,
)
from environments.live.settlement.sqlite_settlement_store import SettlementStoreError
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


def test_recovery_snapshot_identity_collision_keeps_both_order_ids_in_u19_gate(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "snapshot-collision.sqlite3")
    store.record_reconciliation_event_pending(
        event_id="REST-CCNL-SNAPSHOT|broker-1|2|10.50",
        client_order_id="client-original",
        broker_order_id="broker-1",
        event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
        payload={"cumulative_filled_quantity": 2, "source": "VALIDATION_ONLY"},
    )
    with pytest.raises(SettlementStoreError, match="RECONCILIATION_EVENT_ID_COLLISION"):
        store.record_reconciliation_event_pending(
            event_id="REST-CCNL-SNAPSHOT|broker-1|2|10.50",
            client_order_id="client-other",
            broker_order_id="broker-1",
            event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
            payload={"cumulative_filled_quantity": 2, "source": "CONFLICTING_VALIDATION_ONLY"},
        )

    as_of = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
    digest = hashlib.sha256(b"empty-validation-snapshot").hexdigest()
    broker = U19BrokerPositionSnapshot(
        group_id="SYNTHETIC:RECOVERY-GROUP", snapshot_id="broker-empty", as_of=as_of,
        source="VALIDATION_ONLY:BROKER_EXCHANGE", positions=(), complete=True,
        capability_verified=True, payload_sha256=digest,
    )
    ledger = U19ExecutionLedgerSnapshot(
        group_id="SYNTHETIC:RECOVERY-GROUP", snapshot_id="ledger-empty", as_of=as_of,
        source="VALIDATION_ONLY:EXECUTION_LEDGER", positions=(), complete=True,
        payload_sha256=digest, execution_events=(), pending_order_ids=(),
    )
    decision = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "u19-collision.sqlite3"),
        settlement_store=store,
    ).recover(
        group_id="SYNTHETIC:RECOVERY-GROUP", broker_snapshot=broker, ledger_snapshot=ledger
    )
    assert decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert set(decision.pending_order_ids) == {"client-original", "client-other"}
    assert decision.restore_allowed is False


def test_rest_snapshot_events_resolve_individually_and_only_last_clears_order_gate(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "snapshot-event-resolution.sqlite3")
    for index in (1, 2):
        store.record_reconciliation_event_pending(
            event_id=f"REST-CCNL-SNAPSHOT|broker-1|{index + 1}|10.{index}0",
            client_order_id="client-order-1",
            broker_order_id="broker-order-1",
            event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
            payload={"cumulative_filled_quantity": index + 1, "source_authority": "VALIDATION_ONLY"},
        )

    first = store.resolve_reconciliation_event(
        event_id="REST-CCNL-SNAPSHOT|broker-1|2|10.10",
        scope_key="client-order-1",
        evidence_ref="TEST_ONLY:independent-inquiry:first-snapshot",
    )
    assert first is True
    assert len(store.open_reconciliation_events(scope_key="client-order-1")) == 1
    assert store.has_unresolved_reconciliation()

    second = store.resolve_reconciliation_event(
        event_id="REST-CCNL-SNAPSHOT|broker-1|3|10.20",
        scope_key="client-order-1",
        evidence_ref="TEST_ONLY:independent-inquiry:second-snapshot",
    )
    assert second is True
    assert store.resolve_reconciliation_event(
        event_id="REST-CCNL-SNAPSHOT|broker-1|3|10.20",
        scope_key="client-order-1",
        evidence_ref="TEST_ONLY:duplicate-resolution",
    ) is False
    assert store.open_reconciliation_events(scope_key="client-order-1") == ()
    assert not store.has_unresolved_reconciliation()
    assert store.load_execution_journal_records() == ()
    assert store.load_position_state("OPT-NOT-TOUCHED") is None


def test_only_pending_rest_snapshot_events_are_resolvable_not_late_fills_or_conflicts(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "snapshot-resolution-guard.sqlite3")
    store.record_late_fill_pending(
        execution_id="late-fill-event-1",
        client_order_id="client-late",
        broker_order_id="broker-late",
        payload={"execution_id": "late-fill-event-1"},
    )
    with pytest.raises(SettlementStoreError, match="RECONCILIATION_EVENT_KIND_NOT_EXTERNALLY_RESOLVABLE"):
        store.resolve_reconciliation_event(
            event_id="late-fill-event-1",
            scope_key="client-late",
            evidence_ref="TEST_ONLY:cannot-resolve-late-fill-without-settlement",
        )

    store.record_reconciliation_event_pending(
        event_id="REST-CCNL-SNAPSHOT|broker-conflict|2|10.50",
        client_order_id="client-conflict",
        broker_order_id="broker-conflict",
        event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
        payload={"cumulative_filled_quantity": 2},
    )
    with pytest.raises(SettlementStoreError, match="RECONCILIATION_EVENT_ID_COLLISION"):
        store.record_reconciliation_event_pending(
            event_id="REST-CCNL-SNAPSHOT|broker-conflict|2|10.50",
            client_order_id="client-conflict",
            broker_order_id="broker-conflict",
            event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
            payload={"cumulative_filled_quantity": 3},
        )
    with pytest.raises(SettlementStoreError, match="RECONCILIATION_EVENT_CONFLICT_REQUIRES_MANUAL_REVIEW"):
        store.resolve_reconciliation_event(
            event_id="REST-CCNL-SNAPSHOT|broker-conflict|2|10.50",
            scope_key="client-conflict",
            evidence_ref="TEST_ONLY:must-not-clear-conflict",
        )
