from datetime import datetime
from typing import Protocol


class ClockProvider(Protocol):
    """Environment-neutral time source injected into Runtime/Environment."""

    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...

    def sleep_policy(self, seconds: float) -> None: ...
