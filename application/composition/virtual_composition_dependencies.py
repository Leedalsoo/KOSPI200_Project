from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.option.option_master import IOptionContractMaster

from contracts.virtual_contract_resolver import (
OptionContractIdentityRegistry,
VirtualContractMapping,
VirtualContractResolver,
)


@dataclass(frozen=True)
class VirtualCompositionDependencies:
    """Explicit Application-level dependencies for one Virtual composition scope."""

    contract_registry: OptionContractIdentityRegistry
    contract_mappings: Mapping[str, VirtualContractMapping]
    initial_capital: float
    vssf_command_context: Any
    scenario_source: Any | None = None
    replay_source: Any | None = None
    option_master: IOptionContractMaster | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.initial_capital, (int, float)) or self.initial_capital <= 0:
            raise ValueError("VIRTUAL_INITIAL_CAPITAL_REQUIRED")
        if not callable(getattr(self.vssf_command_context, "build_command", None)):
            raise TypeError("VSSF_COMMAND_CONTEXT_REQUIRED")

    def create_contract_resolver(self) -> VirtualContractResolver:
        """Create a resolver sharing this scope's authoritative registry instance."""
        return VirtualContractResolver(
            mappings=self.contract_mappings,
            registry=self.contract_registry,
        )
