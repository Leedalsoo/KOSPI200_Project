from __future__ import annotations

from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionLedgerSnapshot,
    U19RecoveryDecision,
    evaluate_u19_recovery,
)
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


class ValidationOnlyTrack2U19RecoveryCoordinator:
    """Coordinates injected validation snapshots and persists a durable decision."""

    def __init__(self, store: SqliteTrack2U19RecoveryStore) -> None:
        self.store = store

    def recover(
        self,
        *,
        group_id: str,
        broker_snapshot: U19BrokerPositionSnapshot | None,
        ledger_snapshot: U19ExecutionLedgerSnapshot | None,
    ) -> U19RecoveryDecision:
        decision = evaluate_u19_recovery(
            group_id=group_id,
            broker_snapshot=broker_snapshot,
            ledger_snapshot=ledger_snapshot,
        )
        self.store.save(decision.to_checkpoint())
        return decision
