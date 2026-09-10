"""Control Tower view models for runtime status display."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvironmentStatusView:
    environment: str | None = None
    runtime_state: str = "UNKNOWN"
    market_state: str = "UNKNOWN"
    account_state: str = "UNKNOWN"
    position_state: str = "UNKNOWN"
    pnl: float | None = None
    orders_state: str = "UNKNOWN"
    risk_state: str = "UNKNOWN"
    kill_switch: bool = True
    live_approval: bool = False
    credential_ready: bool = False
    execution_allowed: bool = False
    speed_multiplier: float | None = None
    scenario: str | None = None
    error: str | None = None


def from_runtime_status(status) -> EnvironmentStatusView:
    """Map only the Runtime status contract; never expose concrete environment objects."""
    return EnvironmentStatusView(
        environment=status.environment,
        runtime_state=status.state,
    )
