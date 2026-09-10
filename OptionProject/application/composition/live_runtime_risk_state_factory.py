"""Composition helpers for the Live runtime Risk/tick boundary."""
from __future__ import annotations

from application.composition.execution_path_composition import (
create_runtime_transport_composition,
)
from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry
from core.strategy.orchestrator.runtime_authoritative_risk_router_adapter import (
route_from_runtime_authoritative_sources,
)


def create_live_runtime_tick_transport(
# *,
strategy_runtime,
strategy_to_decision,
decision_to_command,
risk_gate,
order_router,
broker_command,
risk_state_providers,
):
    """Create the one-shot Runtime transport and TickEntry from one dependency graph.

    The transport's Risk context is an initial composition contract. The
    TickEntry refreshes authoritative Account/Position state on every tick.
    """
    if risk_state_providers is None:
        pass
        raise ValueError("LIVE_RUNTIME_RISK_STATE_PROVIDERS_REQUIRED")

    account_snapshot_provider = risk_state_providers.account_snapshot_provider
    position_source_provider = risk_state_providers.position_source_provider

    transport = create_runtime_transport_composition(
        strategy_runtime=strategy_runtime,
        strategy_to_decision=strategy_to_decision,
        decision_to_command=decision_to_command,
        risk_gate=risk_gate,
        account_snapshot=account_snapshot_provider(),
        position_source=position_source_provider(),
        order_router=order_router,
        broker_command=broker_command,
    )
    entry = LiveRuntimeTickEntry(
        runtime=strategy_runtime,
        strategy_to_decision=strategy_to_decision,
        decision_to_command=decision_to_command,
        risk_gate=risk_gate,
        route_authoritative=route_from_runtime_authoritative_sources,
        account_snapshot_provider=account_snapshot_provider,
        position_source_provider=position_source_provider,
    )
    return transport, entry


__all__ = ["create_live_runtime_tick_transport"]

