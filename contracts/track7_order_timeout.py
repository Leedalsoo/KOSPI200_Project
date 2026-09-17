from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Track7OrderTimeoutPolicy:
    """Explicit Track7 timeout policy; no strategy fallback is supplied here."""

    timeout_seconds: Decimal
    policy_id: str

    def __post_init__(self) -> None:
        if self.timeout_seconds <= Decimal("0"):
            raise ValueError("TRACK7_ORDER_TIMEOUT_POLICY_REQUIRED")
        if not self.policy_id:
            raise ValueError("TRACK7_ORDER_TIMEOUT_POLICY_ID_REQUIRED")


@dataclass(frozen=True)
class Track7OrderLifecycleObservation:
    client_order_id: str
    strategy_id: str
    submitted_at: datetime
    observed_at: datetime
    status: str
    source: str


class Track7OrderTimeoutSource(Protocol):
    """Authoritative broker-lifecycle + runtime-clock timeout port."""

    def observe_submission(self, client_order_id: str, strategy_id: str, submitted_at: datetime) -> None: ...

    def observe(self, client_order_id: str, observed_at: datetime, status: str) -> Track7OrderLifecycleObservation: ...

    def is_timed_out(self, client_order_id: str, observed_at: datetime, status: str) -> bool: ...
