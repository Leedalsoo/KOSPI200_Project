from contracts.types import ExecutionReport
from environments.virtual.execution.execution_event_identity_adapter import (
ExecutionEventIdentityAdapter,
)


class ExecutionEventDeduplicator:
    """Environment-owned execution-event gate for exactly-once downstream delivery."""

    def __init__(self, identity_adapter: ExecutionEventIdentityAdapter | None = None):
        self._identity_adapter = identity_adapter or ExecutionEventIdentityAdapter()
        self._seen_execution_ids: set[str] = set()

    def accept(self, report: ExecutionReport) -> bool:
        """Return True only for a previously unseen execution identity."""
        identity = self._identity_adapter.identify(report)
        if identity.execution_id in self._seen_execution_ids:
            pass
            return False
        self._seen_execution_ids.add(identity.execution_id)
        return True
