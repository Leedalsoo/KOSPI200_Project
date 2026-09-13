"""Composition helpers for authoritative Live runtime risk state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LiveRuntimeRiskStateProviders:
    account_snapshot_provider: Any
    position_source_provider: Any


def create_live_runtime_risk_state_providers(*, account: Any, position_source: Any) -> LiveRuntimeRiskStateProviders:
    """Expose caller-owned Account/Position providers without synthesizing state."""
    if account is None:
        raise ValueError("LIVE_ACCOUNT_PROVIDER_REQUIRED")
    if position_source is None:
        raise ValueError("LIVE_POSITION_SOURCE_PROVIDER_REQUIRED")

    account_snapshot = getattr(account, "snapshot", None)
    if not callable(account_snapshot):
        raise ValueError("LIVE_ACCOUNT_SNAPSHOT_PROVIDER_REQUIRED")

    position_snapshot = getattr(position_source, "snapshot", None)
    if not callable(position_snapshot):
        raise ValueError("LIVE_POSITION_SOURCE_PROVIDER_REQUIRED")

    return LiveRuntimeRiskStateProviders(
        account_snapshot_provider=account_snapshot,
        position_source_provider=lambda: position_source,
    )


__all__ = [
    "LiveRuntimeRiskStateProviders",
    "create_live_runtime_risk_state_providers",
]
