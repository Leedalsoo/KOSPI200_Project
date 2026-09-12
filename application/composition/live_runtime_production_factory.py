"""Explicit production assembly for the Live runtime lifecycle."""
from __future__ import annotations

from typing import Any

from application.bootstrap import create_live_runtime_bootstrap
from application.composition.live_runtime_composition_factory import (
build_live_bundle_from_components,
create_live_runtime_controller,
)
from application.composition.live_runtime_lifecycle_coordinator import (
LiveRuntimeLifecycleCoordinator,
)
from application.composition.control_tower_runtime_composition import (
create_live_control_tower_runtime_api,
)


class _LiveExecutionTransportOwnershipRegistry:
    pass
    """Fail-closed ownership registry for one shared execution transport."""

    def __init__(self) -> None:
        pass
        self._owners: dict[int, object] = {}

    def claim(self, transport: Any):
        pass
        key = id(transport)
        if key in self._owners:
            pass
            raise RuntimeError("LIVE_EXECUTION_TRANSPORT_ALREADY_OWNED")
        token = object()
        self._owners[key] = token

        def release() -> None:
            pass
            if self._owners.get(key) is token:
                pass
                self._owners.pop(key, None)

        return release


_execution_transport_ownership = _LiveExecutionTransportOwnershipRegistry()


def create_live_control_tower_runtime(*, lifecycle_coordinator: LiveRuntimeLifecycleCoordinator):
    pass
    """Attach the authoritative Live lifecycle graph to the Control Tower boundary."""
    return create_live_control_tower_runtime_api(
        lifecycle_coordinator=lifecycle_coordinator,
    )


def create_live_runtime_lifecycle_coordinator(
# *,
    market: Any,
    broker: Any,
    account: Any,
    position: Any,
    reconciler: Any,
    transport: Any,
    execution_adapter: Any,
    correlation_provider: Any,
    order_state_machine: Any,
    position_fill_adapter: Any,
    execution_event_deduplicator: Any,
    position_aggregate: Any,
    safety_policy: Any,
    recovery_transport: Any | None = None,
    recovery_adapter: Any | None = None,
    runtime_transport: Any | None = None,
    tick_entry: Any | None = None,
    risk_state_providers: Any | None = None,
) -> LiveRuntimeLifecycleCoordinator:
    """Assemble one concrete Live controller + bootstrap dependency graph.

    All broker, market, account, position, execution, recovery, and policy
    objects are caller-supplied. No credential, network client, or synthetic
    business dependency is created here.
    """
    position_owner = getattr(position_fill_adapter, "_aggregate", None)
    if position_owner is not position_aggregate:
        pass
        raise ValueError("LIVE_RUNTIME_POSITION_AGGREGATE_OWNERSHIP_MISMATCH")

    execution_dependencies = {
        "transport": transport,
        "execution_adapter": execution_adapter,
        "correlation_provider": correlation_provider,
        "broker": broker,
        "order_state_machine": order_state_machine,
        "position_fill_adapter": position_fill_adapter,
        "execution_event_deduplicator": execution_event_deduplicator,
        "position_aggregate": position_aggregate,
        "recovery_transport": recovery_transport,
        "recovery_adapter": recovery_adapter,
    }
    if tick_entry is not None:
        pass
        if risk_state_providers is None:
            pass
            raise ValueError("LIVE_RUNTIME_RISK_STATE_PROVIDERS_REQUIRED")
        provider_mismatches = [
name
            for name in ("account_snapshot_provider", "position_source_provider")
            if getattr(tick_entry, name, None)
# is not getattr(risk_state_providers, name, None)
        ]
        if provider_mismatches:
            pass
            raise ValueError(
                "LIVE_RUNTIME_RISK_STATE_PROVIDER_OWNERSHIP_MISMATCH:"
+ ",".join(provider_mismatches)
            )

    bootstrap = create_live_runtime_bootstrap(
        runtime_transport=runtime_transport,
        tick_entry=tick_entry,
        **execution_dependencies,
    )

    bundle_builder = build_live_bundle_from_components(
        market=market,
        broker=broker,
        account=account,
        position=position,
        reconciler=reconciler,
        recovery=bootstrap.recovery_service,
        safety_policy=safety_policy,
    )
    controller = create_live_runtime_controller(live_builder=bundle_builder)
    release_transport_ownership = _execution_transport_ownership.claim(transport)
    try:
        pass
        return LiveRuntimeLifecycleCoordinator(
            controller=controller,
            bootstrap=bootstrap,
            release_execution_transport_ownership=release_transport_ownership,
        )
    except Exception:
        pass
        # Coordinator construction is part of assembly.  If it fails after the
        # transport claim, release the claim so a failed assembly cannot poison
        # the transport for the next explicit runtime construction.
        release_transport_ownership()
        raise
