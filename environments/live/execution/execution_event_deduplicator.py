from __future__ import annotations

from contracts.types import ExecutionReport


class ExecutionEventDeduplicator:
    """Live-owned exactly-once delivery gate for execution events."""

    def __init__(self, persistence_store=None) -> None:
        self._seen_execution_ids: set[str] = set()
        self._persistence_store = persistence_store

    def accept(self, report: ExecutionReport) -> bool:
        execution_id = str(report.execution_id or "").strip()
        if not execution_id:
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if self._persistence_store is not None:
            raise RuntimeError("PERSISTENT_DEDUP_REQUIRES_SETTLEMENT_TRANSACTION")
        if execution_id in self._seen_execution_ids:
            return False
        self._seen_execution_ids.add(execution_id)
        return True

    def set_persistence_store(self, store) -> None:
        if store is None:
            raise ValueError("SETTLEMENT_STORE_REQUIRED")
        self._persistence_store = store

    def remember(self, execution_id: str) -> None:
        key = str(execution_id).strip()
        if not key:
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        self._seen_execution_ids.add(key)

    def contains(self, execution_id: str) -> bool:
        key = str(execution_id).strip()
        return key in self._seen_execution_ids or (self._persistence_store is not None and self._persistence_store.has_execution(key))
