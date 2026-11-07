from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from application.composition.track1_runtime_input_provider import Track1RuntimeInputResult
from core.strategy.track1_tail_defense import Track1Input


@dataclass(frozen=True)
class S1ValidationInputEvidence:
    manifest_path: str
    manifest_sha256: str
    dataset_path: str
    dataset_sha256: str
    risk_profile_path: str
    risk_profile_sha256: str
    event_count: int
    scenario_ids: tuple[str, ...]


class S1ValidationOnlyRuntimeInputAdapter:
    """Manifest-bound synthetic input for Strategy 1 signal-only validation."""

    STRATEGY_ID = "TRACK1_TAIL_DEFENSE"
    MANIFEST_SCHEMA = "q25-s1-validation-input-manifest-v1"
    EVENT_SCHEMA = "q25-s1-validation-input-event-v1"

    def __init__(self, *, manifest_path: str | Path, root: str | Path | None = None) -> None:
        self.root = Path(root or Path.cwd()).resolve()
        self.manifest_path = self._within_root(manifest_path)
        manifest_bytes = self.manifest_path.read_bytes()
        self.manifest = json.loads(manifest_bytes)
        m = self.manifest
        if (m.get("schema") != self.MANIFEST_SCHEMA
                or m.get("strategy_id") != self.STRATEGY_ID
                or m.get("provenance") != "DERIVED_SCENARIO"
                or m.get("synthetic") is not True
                or m.get("validation_only") is not True
                or m.get("signal_generation_only") is not True
                or m.get("runtime_eligible") is not False
                or m.get("production_runtime_eligible") is not False
                or m.get("execution_enabled") is not False
                or m.get("allow_kis_api") is not False
                or m.get("allow_live_orders") is not False
                or m.get("allow_real_account") is not False
                or m.get("contract_identity_authority") != "NONE"
                or m.get("expiry_is_authoritative") is not False):
            raise ValueError("S1_VALIDATION_MANIFEST_INVALID")

        self.dataset_path = self._within_root(str(m.get("dataset_path", "")))
        dataset_bytes = self.dataset_path.read_bytes()
        dataset_hash = sha256(dataset_bytes).hexdigest()
        if dataset_hash != str(m.get("dataset_sha256", "")).lower():
            raise ValueError("S1_VALIDATION_DATASET_HASH_MISMATCH")

        self.risk_profile_path = self._within_root(str(m.get("risk_profile_path", "")))
        profile_bytes = self.risk_profile_path.read_bytes()
        profile_hash = sha256(profile_bytes).hexdigest()
        if profile_hash != str(m.get("risk_profile_sha256", "")).lower():
            raise ValueError("S1_VALIDATION_RISK_PROFILE_HASH_MISMATCH")
        self.risk_profile = json.loads(profile_bytes)
        p = self.risk_profile
        limits = p.get("limits") if isinstance(p.get("limits"), dict) else {}
        if (p.get("schema") != "q25-s1-validation-signal-risk-profile-v1"
                or p.get("validation_only") is not True
                or p.get("signal_generation_only") is not True
                or p.get("runtime_eligible") is not False
                or p.get("production_runtime_eligible") is not False
                or p.get("allow_kis_api") is not False
                or p.get("allow_live_orders") is not False
                or p.get("allow_real_account") is not False
                or p.get("execution_enabled") is not False
                or p.get("operational_config_mutated") is not False
                or p.get("contract_identity_authority") != "NONE"
                or p.get("expiry_is_authoritative") is not False
                or limits.get("max_open_short_contracts") != 10
                or limits.get("max_pending_short_contracts") != 10
                or float(limits.get("dte_gate_test_value", 0)) != 10.0
                or limits.get("quantity_per_crossing") != 1):
            raise ValueError("S1_VALIDATION_RISK_PROFILE_INVALID")
        if p.get("dataset_sha256") != dataset_hash:
            raise ValueError("S1_VALIDATION_RISK_DATASET_HASH_MISMATCH")

        self.allowed_scenario_ids = frozenset(str(x) for x in m.get("scenario_ids", ()))
        self.events: dict[str, dict[str, Any]] = {}
        for line in dataset_bytes.decode("utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            self._validate_event(row)
            timestamp = str(row["timestamp"])
            if timestamp in self.events:
                raise ValueError("S1_VALIDATION_DUPLICATE_EVENT_TIMESTAMP")
            self.events[timestamp] = row
        if len(self.events) != int(m.get("event_count", -1)) or not self.events:
            raise ValueError("S1_VALIDATION_EVENT_COUNT_MISMATCH")

        self.evidence = S1ValidationInputEvidence(
            manifest_path=str(self.manifest_path.relative_to(self.root)).replace("\\", "/"),
            manifest_sha256=sha256(manifest_bytes).hexdigest(),
            dataset_path=str(self.dataset_path.relative_to(self.root)).replace("\\", "/"),
            dataset_sha256=dataset_hash,
            risk_profile_path=str(self.risk_profile_path.relative_to(self.root)).replace("\\", "/"),
            risk_profile_sha256=profile_hash,
            event_count=len(self.events),
            scenario_ids=tuple(str(x) for x in m.get("scenario_ids", ())),
        )

    def _within_root(self, value: str | Path) -> Path:
        candidate = (self.root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("S1_VALIDATION_PATH_OUTSIDE_PROJECT_ROOT")
        if not candidate.is_file():
            raise FileNotFoundError(str(candidate))
        return candidate

    def _validate_event(self, row: dict[str, Any]) -> None:
        if (row.get("schema") != self.EVENT_SCHEMA
                or str(row.get("scenario_id", "")) not in self.allowed_scenario_ids
                or row.get("provenance") != "DERIVED_SCENARIO"
                or row.get("synthetic") is not True
                or row.get("validation_only") is not True
                or row.get("runtime_eligible") is not False
                or row.get("production_runtime_eligible") is not False
                or row.get("execution_enabled") is not False
                or row.get("contract_identity") is not None
                or row.get("expiry_yyyymmdd") is not None
                or row.get("contract_multiplier") is not None
                or row.get("quote") is not None):
            raise ValueError("S1_VALIDATION_EVENT_PROVENANCE_INVALID")
        observed = datetime.fromisoformat(str(row.get("timestamp", "")))
        if observed.tzinfo is None:
            raise ValueError("S1_VALIDATION_EVENT_TIMEZONE_REQUIRED")
        if Decimal(str(row.get("underlying_price", 0))) <= 0:
            raise ValueError("S1_VALIDATION_UNDERLYING_PRICE_INVALID")
        if Decimal(str(row.get("reference_point_test_input", 0))) <= 0:
            raise ValueError("S1_VALIDATION_REFERENCE_INPUT_INVALID")
        if row.get("reference_point_basis") != "SCENARIO_INITIAL_REFERENCE_ONLY_NOT_U23_POLICY":
            raise ValueError("S1_VALIDATION_REFERENCE_BASIS_INVALID")
        if row.get("dte_basis") != "SCENARIO_GATE_VALUE_ONLY_NOT_U22_CALENDAR_SEMANTICS":
            raise ValueError("S1_VALIDATION_DTE_BASIS_INVALID")
        dte = float(row.get("days_to_expiry_test_value", 0))
        if dte <= 4:
            raise ValueError("S1_VALIDATION_DTE_GATE_INPUT_MUST_EXCEED_CUTOFF")
        if dte != float(self.risk_profile["limits"]["dte_gate_test_value"]):
            raise ValueError("S1_VALIDATION_DTE_INPUT_PROFILE_MISMATCH")
        for key in ("open_short_quantity", "pending_short_quantity"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("S1_VALIDATION_EXPOSURE_INPUT_INVALID")

    def apply_to_strategy(self, strategy: Any) -> None:
        if getattr(strategy, "strategy_id", None) != self.STRATEGY_ID:
            raise ValueError("S1_VALIDATION_STRATEGY_ID_MISMATCH")
        # These flags are enabled only on this in-memory strategy instance after
        # manifest/profile validation; no operational config is modified.
        strategy.runtime_config_verified = True
        strategy.risk_limits_available = True

    def build(self, *, tick: Any, as_of: datetime) -> Track1RuntimeInputResult:
        raw_timestamp = getattr(tick, "timestamp", None) or getattr(tick, "observed_at", None)
        timestamp = raw_timestamp.isoformat() if isinstance(raw_timestamp, datetime) else str(raw_timestamp or "")
        row = self.events.get(timestamp)
        if row is None:
            return Track1RuntimeInputResult(None, ("s1_validation_scenario_event",))
        observed = datetime.fromisoformat(timestamp)
        if observed != as_of or observed.tzinfo is None:
            return Track1RuntimeInputResult(None, ("s1_validation_event_time",))
        if Decimal(str(getattr(tick, "price", "0"))) != Decimal(str(row["underlying_price"])):
            return Track1RuntimeInputResult(None, ("s1_validation_underlying_price_match",))
        payload = Track1Input(
            momentum_confirmed=False,
            days_to_expiry=float(row["days_to_expiry_test_value"]),
            current_time=as_of,
            active_vol=None,
            base_vol=None,
            reference_point=Decimal(str(row["reference_point_test_input"])),
            reference_point_verified=True,
            open_short_quantity=int(row["open_short_quantity"]),
            pending_short_quantity=int(row["pending_short_quantity"]),
            exposure_snapshot_verified=True,
            dte_basis_verified=True,
        )
        return Track1RuntimeInputResult(payload, ())
