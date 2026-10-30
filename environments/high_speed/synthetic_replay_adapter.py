"""Fail-closed adapter for validation-only DERIVED_SCENARIO Replay.

Synthetic contract IDs are runtime-local routing keys only. They are never Standard
instrument identifiers and this adapter must not be used for REAL_VTS or Live data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SYNTHETIC_ID_PREFIX = "SYNTHETIC_CONTRACT:"
EXPECTED_PROVENANCE = "DERIVED_SCENARIO"
EXPECTED_IDENTITY_STATUS = "BLOCKED_IDENTITY_OWNER_UNRESOLVED"
EXPECTED_SCHEMA = "reference-canonical-market-tick-v1"


class SyntheticReplayAdapter:
    """Validate a P5 dataset and adapt its synthetic ID only for validation replay."""

    def __init__(self, dataset: str | Path) -> None:
        self.root = Path(dataset)
        manifest_path = self.root / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("SYNTHETIC_REPLAY_MANIFEST_REQUIRED")
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self._validate_manifest()

    def _validate_manifest(self) -> None:
        manifest = self.manifest
        if manifest.get("schema") != EXPECTED_SCHEMA:
            raise ValueError("SYNTHETIC_REPLAY_SCHEMA_MISMATCH")
        if manifest.get("synthetic") is not True:
            raise ValueError("SYNTHETIC_REPLAY_SYNTHETIC_FLAG_REQUIRED")
        if manifest.get("provenance") != EXPECTED_PROVENANCE:
            raise ValueError("SYNTHETIC_REPLAY_PROVENANCE_REQUIRED")
        if manifest.get("validation_only") is not True:
            raise ValueError("SYNTHETIC_REPLAY_VALIDATION_ONLY_REQUIRED")
        if manifest.get("production_runtime_eligible") is not False:
            raise ValueError("SYNTHETIC_REPLAY_PRODUCTION_ELIGIBILITY_MUST_BE_FALSE")
        if manifest.get("identity_source_status") != EXPECTED_IDENTITY_STATUS:
            raise ValueError("SYNTHETIC_REPLAY_IDENTITY_STATUS_BLOCKED_REQUIRED")
        policy = manifest.get("identity_policy")
        if not isinstance(policy, dict):
            raise ValueError("SYNTHETIC_REPLAY_IDENTITY_POLICY_REQUIRED")
        if policy.get("mode") != "SYNTHETIC_ONLY":
            raise ValueError("SYNTHETIC_REPLAY_SYNTHETIC_ONLY_POLICY_REQUIRED")
        if policy.get("synthetic_contract_id_namespace") != SYNTHETIC_ID_PREFIX:
            raise ValueError("SYNTHETIC_REPLAY_ID_NAMESPACE_MISMATCH")
        if policy.get("production_standard_instrument_id_assigned") is not False:
            raise ValueError("SYNTHETIC_REPLAY_STANDARD_ID_ASSIGNMENT_FORBIDDEN")

    def adapt_tick(self, tick: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(tick, dict):
            raise ValueError("SYNTHETIC_REPLAY_TICK_OBJECT_REQUIRED")
        adapted = dict(tick)
        synthetic_id = adapted.get("synthetic_contract_id")
        if not isinstance(synthetic_id, str) or not synthetic_id.startswith(SYNTHETIC_ID_PREFIX):
            raise ValueError("SYNTHETIC_REPLAY_CONTRACT_ID_REQUIRED")
        if adapted.get("instrument_identity_status") != EXPECTED_IDENTITY_STATUS:
            raise ValueError("SYNTHETIC_REPLAY_TICK_IDENTITY_STATUS_REQUIRED")
        source_code = adapted.get("source_instrument_code")
        if not isinstance(source_code, str) or not source_code.strip():
            raise ValueError("SYNTHETIC_REPLAY_SOURCE_CODE_REQUIRED")
        existing_id = adapted.get("instrument_id")
        if existing_id not in (None, "", synthetic_id):
            raise ValueError("SYNTHETIC_REPLAY_PRODUCTION_ID_FIELD_FORBIDDEN")
        # This field is a namespaced, validation-only routing key, not a Standard ID.
        adapted["instrument_id"] = synthetic_id
        return adapted

    def adapt_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("SYNTHETIC_REPLAY_RECORD_OBJECT_REQUIRED")
        if record.get("schema") != EXPECTED_SCHEMA:
            raise ValueError("UNSUPPORTED_SYNTHETIC_DATASET_SCHEMA")
        if record.get("synthetic") is not True:
            raise ValueError("SYNTHETIC_REPLAY_RECORD_FLAG_REQUIRED")
        if record.get("provenance") != EXPECTED_PROVENANCE:
            raise ValueError("SYNTHETIC_DATASET_PROVENANCE_REQUIRED")
        adapted = dict(record)
        adapted["tick"] = self.adapt_tick(record.get("tick"))
        return adapted
