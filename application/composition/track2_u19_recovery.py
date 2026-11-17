from __future__ import annotations

from dataclasses import replace

from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionLedgerSnapshot,
    U19RecoveryDecision,
    evaluate_u19_recovery,
)
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


class ValidationOnlyTrack2U19RecoveryCoordinator:
    """Coordinates injected validation snapshots and persists a durable decision."""

    def __init__(self, store: SqliteTrack2U19RecoveryStore, *, settlement_store=None) -> None:
        self.store = store
        self.settlement_store = settlement_store

    def recover(
        self,
        *,
        group_id: str,
        broker_snapshot: U19BrokerPositionSnapshot | None,
        ledger_snapshot: U19ExecutionLedgerSnapshot | None,
    ) -> U19RecoveryDecision:
        if self.settlement_store is not None and ledger_snapshot is not None:
            open_events = self.settlement_store.open_reconciliation_events()
            unresolved = self.settlement_store.unresolved_reconciliations()
            unresolved_ids = tuple(
                "__GLOBAL_RECONCILIATION__"
                if item.get("scope_key") in {"__startup_reconciliation__", "__runtime_bootstrap__"}
                else str(item.get("client_order_id") or "").strip()
                for item in unresolved
            )
            pending_ids = tuple(dict.fromkeys(
                (*ledger_snapshot.pending_order_ids,
                 *(event["client_order_id"] for event in open_events),
                 *(item for item in unresolved_ids if item))
            ))
            if pending_ids != ledger_snapshot.pending_order_ids:
                ledger_snapshot = replace(ledger_snapshot, pending_order_ids=pending_ids)
        decision = evaluate_u19_recovery(
            group_id=group_id,
            broker_snapshot=broker_snapshot,
            ledger_snapshot=ledger_snapshot,
        )
        self.store.save(decision.to_checkpoint())
        return decision

    def recover_from_settlement_store(
        self,
        *,
        group_id: str,
        broker_snapshot: U19BrokerPositionSnapshot | None,
        snapshot_id: str,
        as_of,
        ledger_snapshot_builder,
    ) -> U19RecoveryDecision:
        """Build the local validation ledger from persisted OMS/fill lineage, then reconcile."""
        ledger_snapshot = ledger_snapshot_builder.build(
            group_id=group_id, snapshot_id=snapshot_id, as_of=as_of
        )
        return self.recover(
            group_id=group_id,
            broker_snapshot=broker_snapshot,
            ledger_snapshot=ledger_snapshot,
        )

    def recover_and_restore_u16_runtime(
        self,
        *,
        group_id: str,
        broker_snapshot: U19BrokerPositionSnapshot | None,
        ledger_snapshot: U19ExecutionLedgerSnapshot | None,
        u16_runtime: object,
    ) -> tuple[U19RecoveryDecision, bool]:
        """Persist U19 evidence first; restore U16 retry state only on verified resume."""
        decision = self.recover(
            group_id=group_id,
            broker_snapshot=broker_snapshot,
            ledger_snapshot=ledger_snapshot,
        )
        if decision.status.value != "RESTORE_ALLOWED":
            return decision, False
        restore = getattr(u16_runtime, "restore_after_u19_recovery", None)
        if not callable(restore):
            raise ValueError("U16_RUNTIME_RECOVERY_RESTORE_PORT_REQUIRED")
        restored = bool(restore(group_id, decision))
        return decision, restored
