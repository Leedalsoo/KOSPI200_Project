"""Versioned, auditable Strategy definitions loaded outside strategy code."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


_ALLOWED_EXECUTION_CONTRACTS = {
    "SINGLE_ORDER",
    "MULTI_LEG_REQUIRED",
    "CONDITIONAL_MULTI_LEG",
}


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    code_version: str
    config_version: str
    enabled: bool
    execution_contract: str
    required_sources: tuple[str, ...]
    required_analytics: tuple[str, ...]
    required_execution_tags: tuple[str, ...]
    required_execution_directions: tuple[str, ...]
    supported_exit_modes: tuple[str, ...]
    parameters: Mapping[str, Any]
    manifest_version: str
    config_hash: str

    def __post_init__(self) -> None:
        for name in ("strategy_id", "code_version", "config_version", "manifest_version"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"STRATEGY_DEFINITION_{name.upper()}_REQUIRED")
        if self.execution_contract not in _ALLOWED_EXECUTION_CONTRACTS:
            raise ValueError(f"STRATEGY_EXECUTION_CONTRACT_UNSUPPORTED:{self.execution_contract}")
        if len(set(self.required_sources)) != len(self.required_sources):
            raise ValueError(f"STRATEGY_REQUIRED_SOURCE_DUPLICATE:{self.strategy_id}")
        if len(set(self.required_analytics)) != len(self.required_analytics):
            raise ValueError(f"STRATEGY_REQUIRED_ANALYTICS_DUPLICATE:{self.strategy_id}")
        if not self.config_hash or len(self.config_hash) != 64:
            raise ValueError(f"STRATEGY_CONFIG_HASH_INVALID:{self.strategy_id}")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))

    def requires_multi_leg(self, signal: object) -> bool:
        """Return whether this particular execution proposal must resolve to a plan."""
        proposal = getattr(signal, "execution_proposal", None)
        if proposal is None:
            return False
        if self.execution_contract == "MULTI_LEG_REQUIRED":
            return True
        if self.execution_contract != "CONDITIONAL_MULTI_LEG":
            return False
        tag_id = str(getattr(proposal, "tag_id", "") or "").strip()
        direction = str(getattr(signal, "direction", "") or "").strip()
        return (
            "*" in self.required_execution_tags
            or tag_id in self.required_execution_tags
            or direction in self.required_execution_directions
        )


@dataclass(frozen=True)
class StrategyManifest:
    path: Path
    manifest_version: str
    sha256: str
    definitions: tuple[StrategyDefinition, ...]

    def by_id(self) -> dict[str, StrategyDefinition]:
        return {item.strategy_id: item for item in self.definitions}


def default_strategy_manifest_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "strategies" / "strategy-manifest.v1.json"


def load_strategy_manifest(
    path: str | Path | None = None,
    *,
    expected_sha256: str | None = None,
) -> StrategyManifest:
    manifest_path = Path(path) if path is not None else default_strategy_manifest_path()
    raw = manifest_path.read_bytes()
    digest = sha256(raw).hexdigest()
    if expected_sha256 is not None and digest.lower() != expected_sha256.lower():
        raise ValueError("STRATEGY_MANIFEST_SHA256_MISMATCH")
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("STRATEGY_MANIFEST_SCHEMA_VERSION_UNSUPPORTED")
    manifest_version = str(payload.get("manifest_version", "")).strip()
    if not manifest_version:
        raise ValueError("STRATEGY_MANIFEST_VERSION_REQUIRED")
    rows = payload.get("strategies")
    if not isinstance(rows, list) or not rows:
        raise ValueError("STRATEGY_MANIFEST_ENTRIES_REQUIRED")

    definitions: list[StrategyDefinition] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("STRATEGY_MANIFEST_ENTRY_INVALID")
        strategy_id = str(row.get("strategy_id", "")).strip()
        if not strategy_id:
            raise ValueError("STRATEGY_ID_REQUIRED")
        if strategy_id in seen:
            raise ValueError(f"STRATEGY_MANIFEST_DUPLICATE_ID:{strategy_id}")
        seen.add(strategy_id)
        for field in ("required_sources", "required_analytics", "required_execution_tags",
                      "required_execution_directions", "supported_exit_modes"):
            value = row.get(field, [])
            if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"STRATEGY_MANIFEST_FIELD_INVALID:{strategy_id}:{field}")
        parameters = row.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError(f"STRATEGY_PARAMETERS_INVALID:{strategy_id}")
        definitions.append(StrategyDefinition(
            strategy_id=strategy_id,
            code_version=str(row.get("code_version", "")),
            config_version=str(row.get("config_version", "")),
            enabled=bool(row.get("enabled", True)),
            execution_contract=str(row.get("execution_contract", "")),
            required_sources=tuple(row.get("required_sources", [])),
            required_analytics=tuple(row.get("required_analytics", [])),
            required_execution_tags=tuple(row.get("required_execution_tags", [])),
            required_execution_directions=tuple(row.get("required_execution_directions", [])),
            supported_exit_modes=tuple(row.get("supported_exit_modes", [])),
            parameters=parameters,
            manifest_version=manifest_version,
            config_hash=digest,
        ))
    return StrategyManifest(manifest_path.resolve(), manifest_version, digest, tuple(definitions))
