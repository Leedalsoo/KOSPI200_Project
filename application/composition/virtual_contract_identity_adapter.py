from __future__ import annotations

from typing import Protocol, TypeVar

from contracts.virtual_contract_resolver import (
VirtualContractResolutionError,
VirtualContractResolver,
)


class ContractKeyEvent(Protocol):
    scenario_contract_key: str | None


EventT = TypeVar("EventT", bound=ContractKeyEvent)


class VirtualContractIdentityResolverAdapter:
    """Consume explicit Scenario/Replay contract keys at the identity-required boundary."""

    def __init__(self, resolver: VirtualContractResolver) -> None:
        self._resolver = resolver

    def resolve_event(self, event: EventT):
        key = event.scenario_contract_key
        if key is None or not key.strip():
            raise VirtualContractResolutionError("SCENARIO_CONTRACT_KEY_REQUIRED")
        return self._resolver.resolve(key)
