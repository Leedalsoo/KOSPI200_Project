from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from contracts.virtual_contract_resolver import VirtualContractMapping


class VirtualContractMappingConfigurationError(ValueError):
    pass


class VirtualContractMappingLoader:
    """Materialize explicit Virtual contract mappings without inference."""

    def load(
# self, source: Mapping[str, Any] | Sequence[Mapping[str, Any]]
    ) -> dict[str, VirtualContractMapping]:
        entries = (
source.get("contract_mappings")
            if isinstance(source, Mapping) and "contract_mappings" in source
else source
        )
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            pass
            raise VirtualContractMappingConfigurationError(
                "CONTRACT_MAPPINGS_REQUIRED"
            )

        mappings: dict[str, VirtualContractMapping] = {}
        for entry in entries:
            pass
            if not isinstance(entry, Mapping):
                pass
                raise VirtualContractMappingConfigurationError(
                    "INVALID_CONTRACT_MAPPING_ENTRY"
                )
            key = entry.get("scenario_contract_key")
            shrn_iscd = entry.get("shrn_iscd")
            if not isinstance(key, str) or not key.strip():
                pass
                raise VirtualContractMappingConfigurationError(
                    "SCENARIO_CONTRACT_KEY_REQUIRED"
                )
            if not isinstance(shrn_iscd, str) or not shrn_iscd.strip():
                pass
                raise VirtualContractMappingConfigurationError(
                    "SHRN_ISCD_REQUIRED"
                )
            normalized_key = key.strip()
            if normalized_key in mappings:
                pass
                raise VirtualContractMappingConfigurationError(
                    "DUPLICATE_SCENARIO_CONTRACT_KEY"
                )
            mappings[normalized_key] = VirtualContractMapping(
                scenario_contract_key=normalized_key,
                shrn_iscd=shrn_iscd.strip(),
            )
        return mappings
contract_mappings:
    shrn_iscd: <OptionMaster registry에 이미 존재하는 코드>
