from __future__ import annotations

from datetime import datetime
from typing import Protocol, Any


class RuntimeTickStrategySeam(Protocol):
    def evaluate_tick(self, tick: Any, observed_at: datetime) -> tuple[Any, ...]:
        ...


class StandardOptionRuntime:
    """Minimal authoritative Runtime tick boundary.

    This Runtime owns the decision to accept one authoritative tick into the
    Strategy evaluation seam. It never invents a tick sequence, timestamp,
    option identity, requested price, or execution fields.
    """

    def __init__(self, strategy_seam: RuntimeTickStrategySeam) -> None:
        self._strategy_seam = strategy_seam

    def process_tick(self, tick: Any, observed_at: datetime) -> tuple[Any, ...]:
        source_sequence = getattr(tick, "source_sequence", None)
        if source_sequence is None or source_sequence <= 0:
            raise ValueError("RUNTIME_SOURCE_SEQUENCE_REQUIRED")

        tick_timestamp = getattr(tick, "timestamp", None)
        if tick_timestamp is not None and tick_timestamp != observed_at.isoformat():
            raise ValueError("RUNTIME_TICK_TIMESTAMP_MISMATCH")

        return self._strategy_seam.evaluate_tick(tick, observed_at)
