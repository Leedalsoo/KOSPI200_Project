from typing import Iterable, Protocol

from contracts.types import ExecutionReport


class ExecutionProvider(Protocol):
    """Environment-neutral execution result provider."""

    def reports(self) -> Iterable[ExecutionReport]: ...

    def query_execution(self, execution_id: str) -> ExecutionReport | None: ...
