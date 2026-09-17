from datetime import datetime
from decimal import Decimal

from contracts.clock import ClockProvider
from contracts.track7_order_timeout import (
    Track7OrderLifecycleObservation,
    Track7OrderTimeoutPolicy,
)


class Track7OrderTimeoutRuntimeSource:
    """Track7 timeout source backed by the injected Runtime Clock."""

    SOURCE = "VirtualBroker.lifecycle+RuntimeClock"

    def __init__(self, clock: ClockProvider, policy: Track7OrderTimeoutPolicy):
        self._clock = clock
        self._policy = policy
        self._submissions: dict[str, tuple[str, datetime]] = {}

    @property
    def policy(self) -> Track7OrderTimeoutPolicy:
        return self._policy

    def observe_submission(self, client_order_id: str, strategy_id: str, submitted_at: datetime) -> None:
        if not client_order_id or not strategy_id:
            raise ValueError("TRACK7_ORDER_LIFECYCLE_ID_REQUIRED")
        self._submissions[client_order_id] = (strategy_id, submitted_at)

    def observe(self, client_order_id: str, observed_at: datetime, status: str) -> Track7OrderLifecycleObservation:
        try:
            strategy_id, submitted_at = self._submissions[client_order_id]
        except KeyError as exc:
            raise KeyError("TRACK7_ORDER_LIFECYCLE_SUBMISSION_UNAVAILABLE") from exc
        if observed_at < submitted_at:
            raise ValueError("TRACK7_ORDER_LIFECYCLE_TIME_ORDER_INVALID")
        return Track7OrderLifecycleObservation(
            client_order_id=client_order_id,
            strategy_id=strategy_id,
            submitted_at=submitted_at,
            observed_at=observed_at,
            status=status,
            source=self.SOURCE,
        )

    def is_timed_out(self, client_order_id: str, observed_at: datetime, status: str) -> bool:
        observation = self.observe(client_order_id, observed_at, status)
        if status.upper() in {"FILLED", "CANCELLED", "REJECTED"}:
            return False
        elapsed = Decimal(str((observation.observed_at - observation.submitted_at).total_seconds()))
        return elapsed >= self._policy.timeout_seconds

    def current_time(self) -> datetime:
        return self._clock.now()
