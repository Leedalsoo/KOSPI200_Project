from dataclasses import dataclass

from contracts.types import ExecutionReport


@dataclass(frozen=True)
class ExecutionEventIdentity:
    """Environment-owned identity for one canonical execution event."""

    execution_id: str
    client_order_id: str


class ExecutionEventIdentityAdapter:
    """Preserve an execution report identity without reconstructing it downstream."""

    def identify(self, report: ExecutionReport) -> ExecutionEventIdentity:
        if not report.execution_id:
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if not report.client_order_id:
            raise ValueError("EXECUTION_EVENT_CLIENT_ORDER_ID_REQUIRED")
        return ExecutionEventIdentity(
            execution_id=report.execution_id,
            client_order_id=report.client_order_id,
        )
