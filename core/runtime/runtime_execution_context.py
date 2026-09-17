from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeExecutionContext:
    """Authoritative per-evaluation identity owned by the Runtime loop."""

    tick_sequence: int
    local_sequence: int

    def __post_init__(self) -> None:
        if self.tick_sequence <= 0:
            raise ValueError("tick_sequence must be authoritative and positive")
        if self.local_sequence <= 0:
            raise ValueError("local_sequence must be positive")

    def signal_id(self, track_id: str) -> str:
        track = str(track_id).strip()
        if not track:
            raise ValueError("track_id is required")
        return f"SIG-{self.tick_sequence}-{track}-{self.local_sequence}"

    def client_order_id(self, track_id: str) -> str:
        track = str(track_id).strip()
        if not track:
            raise ValueError("track_id is required")
        return f"ORD-T{self.tick_sequence}-{track}-{self.local_sequence}"
