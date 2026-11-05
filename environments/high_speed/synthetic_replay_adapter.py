"""Fail-closed adapter for validation-only DERIVED_SCENARIO Replay.

Synthetic contract IDs are runtime-local routing keys only. They are never Standard
instrument identifiers and this adapter must not be used for REAL_VTS or Live data.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
from typing import Any

SYNTHETIC_ID_PREFIX = "SYNTHETIC_CONTRACT:"
EXPECTED_PROVENANCE = "DERIVED_SCENARIO"
EXPECTED_IDENTITY_STATUS = "BLOCKED_IDENTITY_OWNER_UNRESOLVED"
EXPECTED_SCHEMA = "reference-canonical-market-tick-v1"
EXPECTED_EXTERNAL_MANIFEST_SCHEMA = "q25-a2-1-s6-syn-evt-manifest-v1"


class SyntheticReplayAdapter:
    """Validate a synthetic dataset and adapt its ID only for validation replay."""

    def __init__(
        self,
        dataset: str | Path,
        *,
        manifest_path: str | Path | None = None,
    ) -> None:
        self.root = Path(dataset).resolve()
        self._external_manifest = manifest_path is not None
        self.manifest_path = (
            Path(manifest_path).resolve()
            if manifest_path is not None
            else self.root / "manifest.json"
        )
        if not self.manifest_path.is_file():
            raise ValueError("SYNTHETIC_REPLAY_MANIFEST_REQUIRED")
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self._validate_manifest()

    def _validate_manifest(self) -> None:
        manifest = self.manifest
        if self._external_manifest:
            self._validate_external_manifest()
            return
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

    def _validate_external_manifest(self) -> None:
        manifest = self.manifest
        if manifest.get("schema_version") != EXPECTED_EXTERNAL_MANIFEST_SCHEMA:
            raise ValueError("SYNTHETIC_REPLAY_EXTERNAL_MANIFEST_SCHEMA_MISMATCH")
        if manifest.get("source_type") != EXPECTED_PROVENANCE or manifest.get("provenance") != EXPECTED_PROVENANCE:
            raise ValueError("SYNTHETIC_REPLAY_PROVENANCE_REQUIRED")
        if manifest.get("synthetic") is not True:
            raise ValueError("SYNTHETIC_REPLAY_SYNTHETIC_FLAG_REQUIRED")
        if manifest.get("validation_only") is not True:
            raise ValueError("SYNTHETIC_REPLAY_VALIDATION_ONLY_REQUIRED")
        if manifest.get("production_runtime_eligible") is not False:
            raise ValueError("SYNTHETIC_REPLAY_PRODUCTION_ELIGIBILITY_MUST_BE_FALSE")
        if manifest.get("identity_source_status") != EXPECTED_IDENTITY_STATUS:
            raise ValueError("SYNTHETIC_REPLAY_IDENTITY_STATUS_BLOCKED_REQUIRED")

        output_path = manifest.get("output_path")
        expected_sha256 = manifest.get("output_sha256")
        expected_bytes = manifest.get("output_bytes")
        expected_rows = manifest.get("rows")
        if not isinstance(output_path, str) or not output_path.strip():
            raise ValueError("SYNTHETIC_REPLAY_MANIFEST_OUTPUT_PATH_REQUIRED")
        if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
            raise ValueError("SYNTHETIC_REPLAY_MANIFEST_OUTPUT_SHA256_REQUIRED")
        if not isinstance(expected_bytes, int) or expected_bytes < 0:
            raise ValueError("SYNTHETIC_REPLAY_MANIFEST_OUTPUT_BYTES_REQUIRED")
        if not isinstance(expected_rows, int) or expected_rows < 0:
            raise ValueError("SYNTHETIC_REPLAY_MANIFEST_ROWS_REQUIRED")
        scenario_ids = manifest.get("scenario_ids")
        if scenario_ids is not None:
            if (not isinstance(scenario_ids, list) or not scenario_ids
                    or any(not isinstance(item, str) or not item.strip() for item in scenario_ids)
                    or len(set(scenario_ids)) != len(scenario_ids)):
                raise ValueError("SYNTHETIC_REPLAY_MANIFEST_SCENARIO_IDS_INVALID")
            scenario_count = manifest.get("scenario_count")
            if scenario_count is not None and scenario_count != len(scenario_ids):
                raise ValueError("SYNTHETIC_REPLAY_MANIFEST_SCENARIO_COUNT_MISMATCH")
        scenario_regimes = manifest.get("scenario_regimes")
        if scenario_regimes is not None:
            if (not isinstance(scenario_regimes, dict)
                    or any(key not in (scenario_ids or []) for key in scenario_regimes)
                    or any(str(value).upper() not in {"NORMAL", "HIGH_VOL"} for value in scenario_regimes.values())):
                raise ValueError("SYNTHETIC_REPLAY_MANIFEST_SCENARIO_REGIMES_INVALID")

        normalized_path = output_path.replace("\\\\", "\\")
        output_file = (Path.cwd() / normalized_path).resolve()
        if (output_file != self.root and output_file.parent != self.root) or not output_file.is_file():
            raise ValueError("SYNTHETIC_REPLAY_MANIFEST_DATASET_PATH_MISMATCH")
        if output_file.stat().st_size != expected_bytes:
            raise ValueError("SYNTHETIC_REPLAY_MANIFEST_OUTPUT_BYTES_MISMATCH")

        digest = hashlib.sha256()
        with output_file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256.lower():
            raise ValueError("SYNTHETIC_REPLAY_MANIFEST_OUTPUT_SHA256_MISMATCH")

        row_count = 0
        with output_file.open("rb") as handle:
            for line in handle:
                if line.strip():
                    row_count += 1
        if row_count != expected_rows:
            raise ValueError("SYNTHETIC_REPLAY_MANIFEST_ROWS_MISMATCH")

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

    def _derive_validation_only_dte(self, tick: dict[str, Any]) -> tuple[int, str]:
        try:
            observed_date = datetime.fromisoformat(str(tick["timestamp"])).date()
            expiry_text = require_exact_option_expiry(tick.get("expiry"))
            expiry_date = date(int(expiry_text[:4]), int(expiry_text[4:6]), int(expiry_text[6:8]))
        except (KeyError, TypeError, ValueError, CanonicalOptionExpiryError) as exc:
            raise ValueError("SYNTHETIC_REPLAY_TRADING_DAY_DTE_REQUIRED") from exc

        schedule = self.manifest.get("trading_calendar")
        if isinstance(schedule, dict):
            if (schedule.get("source_type") != "SYNTHETIC"
                    or schedule.get("authoritative") is not False
                    or schedule.get("timezone") != "Asia/Seoul"):
                raise ValueError("SYNTHETIC_REPLAY_DTE_CALENDAR_AUTHORITY_INVALID")
            try:
                days = tuple(date.fromisoformat(str(item)) for item in schedule["trading_days"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("SYNTHETIC_REPLAY_DTE_CALENDAR_INVALID") from exc
            if not days or days != tuple(sorted(set(days))) or any(day.weekday() >= 5 for day in days):
                raise ValueError("SYNTHETIC_REPLAY_DTE_CALENDAR_INVALID")
            if observed_date not in days or expiry_date not in days:
                raise ValueError("SYNTHETIC_REPLAY_DTE_CALENDAR_RANGE_MISSING")
            dte = days.index(expiry_date) - days.index(observed_date)
            if dte < 0:
                raise ValueError("SYNTHETIC_REPLAY_TRADING_DAY_DTE_INVALID")
            return dte, "DERIVED_SYNTHETIC_VALIDATION_CALENDAR"

        if expiry_date == observed_date:
            return 0, "DERIVED_EXACT_SAME_DAY_EXPIRY"
        raise ValueError("SYNTHETIC_REPLAY_TRADING_DAY_DTE_REQUIRED")

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
        tick = self.adapt_tick(record.get("tick"))
        metadata = record.get("scenario_metadata")
        if metadata is not None:
            if not isinstance(metadata, dict) or metadata.get("validation_only") is not True:
                raise ValueError("SYNTHETIC_REPLAY_SCENARIO_METADATA_INVALID")
            scenario_id = str(metadata.get("scenario_id") or "")
            manifest_scenario_id = self.manifest.get("scenario_id")
            manifest_scenario_ids = self.manifest.get("scenario_ids")
            if isinstance(manifest_scenario_ids, list):
                scenario_match = scenario_id in manifest_scenario_ids
            elif manifest_scenario_id is not None:
                scenario_match = scenario_id == str(manifest_scenario_id)
            else:
                scenario_match = False
            if not scenario_id or not scenario_match:
                raise ValueError("SYNTHETIC_REPLAY_SCENARIO_ID_MISMATCH")
            metadata = dict(metadata)
            dte = metadata.get("dte_trading_days")
            if dte is None:
                dte, dte_provenance = self._derive_validation_only_dte(tick)
                metadata["dte_trading_days"] = dte
                metadata["dte_provenance"] = dte_provenance
                adapted["scenario_metadata"] = metadata
            if isinstance(dte, bool) or not isinstance(dte, int) or dte < 0:
                raise ValueError("SYNTHETIC_REPLAY_TRADING_DAY_DTE_REQUIRED")
            regime = str(metadata.get("regime") or "").upper()
            if not regime:
                regime = str((self.manifest.get("scenario_regimes") or {}).get(scenario_id, "")).upper()
                if regime:
                    metadata["regime"] = regime
                    metadata["regime_provenance"] = "DERIVED_FROM_MANIFEST_SCENARIO_REGIME"
                    adapted["scenario_metadata"] = metadata
            if regime not in {"NORMAL", "HIGH_VOL"}:
                raise ValueError("SYNTHETIC_REPLAY_SCENARIO_REGIME_INVALID")
            identity_authority = str(metadata.get("contract_identity_authority") or "")
            if not identity_authority:
                if (metadata.get("identity_source_status") == EXPECTED_IDENTITY_STATUS
                        and self.manifest.get("identity_source_status") == EXPECTED_IDENTITY_STATUS):
                    identity_authority = "SYNTHETIC_ONLY"
                    metadata["contract_identity_authority"] = identity_authority
                    metadata["identity_authority_provenance"] = "DERIVED_FROM_BLOCKED_IDENTITY_STATUS"
                    adapted["scenario_metadata"] = metadata
            if identity_authority != "SYNTHETIC_ONLY":
                raise ValueError("SYNTHETIC_REPLAY_SCENARIO_IDENTITY_AUTHORITY_INVALID")
            namespace = str(self.manifest.get("validation_identity_namespace") or "")
            synthetic_id = str(tick.get("synthetic_contract_id") or "")
            if namespace and not synthetic_id.startswith(namespace):
                raise ValueError("SYNTHETIC_REPLAY_SCENARIO_IDENTITY_NAMESPACE_MISMATCH")
            tick["validation_only"] = True
            tick["scenario_id"] = scenario_id
            tick["scenario_group_id"] = str(metadata.get("group_id") or "")
            tick["scenario_regime"] = regime
            tick["dte_trading_days"] = dte
        adapted["tick"] = tick
        return adapted
