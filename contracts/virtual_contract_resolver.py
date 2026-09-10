from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


class VirtualContractResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class VirtualContractMapping:
    scenario_contract_key: str
    shrn_iscd: str


class OptionContractIdentityRegistry(Protocol):
    def get_contract_identity(self, shrn_iscd: str): ...


class VirtualContractResolver:
    """Resolve Scenario keys only through explicit mapping and authoritative registry."""

    def __init__(
        self,
        mappings: Mapping[str, VirtualContractMapping],
        registry: OptionContractIdentityRegistry,
    ) -> None:
        self._mappings = dict(mappings)
        self._registry = registry
        self._validate_mappings()

    def resolve(self, scenario_contract_key: str):
        key = scenario_contract_key.strip()
        if not key:
            raise VirtualContractResolutionError("SCENARIO_CONTRACT_KEY_REQUIRED")

        mapping = self._mappings.get(key)
        if mapping is None:
            raise VirtualContractResolutionError("SCENARIO_CONTRACT_MAPPING_NOT_FOUND")

        shrn_iscd = mapping.shrn_iscd.strip()
        if not shrn_iscd:
            raise VirtualContractResolutionError("SHRN_ISCD_REQUIRED")

        identity = self._registry.get_contract_identity(shrn_iscd)
        if identity is None:
            raise VirtualContractResolutionError("AUTHORITATIVE_CONTRACT_IDENTITY_NOT_FOUND")
        return identity

    def _validate_mappings(self) -> None:
        for key, mapping in self._mappings.items():
            if not key.strip() or mapping.scenario_contract_key != key:
                raise VirtualContractResolutionError("INVALID_SCENARIO_CONTRACT_MAPPING")
            if not mapping.shrn_iscd.strip():
                raise VirtualContractResolutionError("SHRN_ISCD_REQUIRED")
