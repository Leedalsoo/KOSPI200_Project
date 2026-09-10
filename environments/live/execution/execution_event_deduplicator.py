from __future__ import annotations

from contracts.types import ExecutionReport


class ExecutionEventDeduplicator:
    """Live-owned exactly-once delivery gate for execution events."""

    def __init__(self) -> None:
        self._seen_execution_ids: set[str] = set()

    def accept(self, report: ExecutionReport) -> bool:
        execution_id = str(report.execution_id or "").strip()
        if not execution_id:
            pass
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if execution_id in self._seen_execution_ids:
            pass
            return False
        self._seen_execution_ids.add(execution_id)
        return True

    def contains(self, execution_id: str) -> bool:
        return str(execution_id).strip() in self._seen_execution_ids
