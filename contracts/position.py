from typing import Protocol

from contracts.types import PositionSnapshot


class PositionProvider(Protocol):
    """Environment-neutral position state provider."""

    def snapshot(self) -> PositionSnapshot: ...
