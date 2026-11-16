from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from contracts.option_expiry import require_exact_option_expiry
from core.risk.track2_synthetic_scenario_profile import load_track2_synthetic_scenario_profile
from core.risk.track2_validation_profile import (
    DEFAULT_TRACK2_VALIDATION_PROFILE,
    load_track2_validation_profile,
)

STRATEGY_ID = "track2_asymmetric_trap"
SYNTHETIC_ID_PREFIX = "SYNTHETIC_CONTRACT:S2:"
EXPECTED_MANIFEST_SCHEMA = "accepted-market-data-runtime-v2"
SCENARIO_ID = "S2_ACCEPTED_MARKET_DATA_RUNTIME_V2"
TRACK2_LEG_ORDER = ("inner_put", "inner_call", "outer_put", "outer_call")


def _track2_preflight_legs_from_long_short(long: dict[str, Any], short: dict[str, Any]) -> tuple[tuple[str, Decimal], ...]:
    """Match the approved execution-plan roles: inner=long, outer=short."""
    return (
        ("PUT", Decimal(str(long["put"]))),
        ("CALL", Decimal(str(long["call"]))),
        ("PUT", Decimal(str(short["put"]))),
        ("CALL", Decimal(str(short["call"]))),
    )


@dataclass(frozen=True)
class Track2SyntheticValidationEvidence:
    manifest_path: str
    manifest_sha256: str
    dataset_sha256: str
    profile_path: str
    profile_sha256: str
    validation_profile_path: str
    validation_profile_sha256: str
    registry_id: str
    rows: int
    trading_dates: tuple[str, ...]


class Track2SyntheticOptionContractSource:
    """Manifest-local contract selection; never claims KIS master authority."""

    def __init__(self, option_master: Any, *, profile: Any, scenario_identity_ids=()) -> None:
        self.option_master = option_master
        self.profile = profile
        self.scenario_identity_ids = frozenset(str(value) for value in scenario_identity_ids)

    def _identities(self, expiry: str | None = None) -> tuple[Any, ...]:
        identities = tuple(self.option_master.list_contract_identities(expiry))
        selected = tuple(
            item for item in identities
            if str(getattr(item, "shrn_iscd", "")).startswith(SYNTHETIC_ID_PREFIX)
            and getattr(item, "stnd_iscd", None) is None
            and str(getattr(item, "instrument_family", "")).upper() == "STANDARD"
            and str(getattr(item, "product_series", "")).upper() == "MONTHLY"
            and getattr(item, "expiry", None)
            and getattr(item, "strike", None) is not None
            and getattr(item, "contract_multiplier", None) is not None
        )
        return selected

    def nearest_expiry(self, *, as_of) -> str:
        expiries = sorted({require_exact_option_expiry(item.expiry) for item in self._identities()})
        candidates = [value for value in expiries if value >= as_of.strftime("%Y%m%d")]
        if not candidates:
            raise ValueError("TRACK2_SYNTHETIC_LISTED_EXPIRY_NOT_FOUND")
        return candidates[0]

    def resolve_identity(self, *, expiry: str, option_type: str, strike: Decimal) -> Any:
        exact = require_exact_option_expiry(expiry)
        kind = str(option_type or "").upper()
        target = Decimal(str(strike))
        matches = [item for item in self._identities(exact)
                   if str(item.option_type).upper() == kind
                   and Decimal(str(item.strike)) == target]
        scenario_matches = [item for item in matches if item.shrn_iscd in self.scenario_identity_ids]
        if scenario_matches:
            matches = scenario_matches
        if len(matches) != 1:
            raise ValueError(
                f"TRACK2_SYNTHETIC_CONTRACT_IDENTITY_NOT_UNIQUE:{exact}:{kind}:{target}:{len(matches)}"
            )
        return matches[0]

    def select(self, *, expiry: str, current_price: Decimal):
        from application.composition.track2_option_contract_source import Track2OptionContractSelection
        exact = require_exact_option_expiry(expiry)
        underlying = Decimal(str(current_price))
        if underlying <= 0:
            raise ValueError("TRACK2_SYNTHETIC_UNDERLYING_PRICE_REQUIRED")
        calls: dict[Decimal, Any] = {}
        puts: dict[Decimal, Any] = {}
        for identity in self._identities(exact):
            kind = str(identity.option_type).upper()
            strike = Decimal(str(identity.strike))
            if kind == "CALL":
                calls[strike] = identity
            elif kind == "PUT":
                puts[strike] = identity
        strikes = sorted(set(calls) & set(puts))
        if not strikes:
            raise ValueError("TRACK2_SYNTHETIC_PAIRED_STRIKES_NOT_FOUND")
        atm = min(strikes, key=lambda strike: (abs(strike - underlying), strike))
        put, call = puts[atm], calls[atm]
        if Decimal(str(put.contract_multiplier)) != Decimal(str(call.contract_multiplier)):
            raise ValueError("TRACK2_SYNTHETIC_MULTIPLIER_MISMATCH")
        return Track2OptionContractSelection(exact, atm, put, call, source="SYNTHETIC:ACCEPTED_MARKET_DATA_RUNTIME_V2")


class Track2ValidationOnlyRuntimeAdapter:
    """Isolated S2 strategy configuration and identity adapter for accepted-data replay."""

    def __init__(self, *, dataset: str | Path, manifest_path: str | Path, profile_path: str | Path,
                 validation_profile_path: str | Path = DEFAULT_TRACK2_VALIDATION_PROFILE,
                 quote_scenario_manifest_path: str | Path | None = None) -> None:
        self.dataset = Path(dataset).resolve()
        self.root = self.dataset
        self.manifest_path = Path(manifest_path).resolve()
        self.profile_path = Path(profile_path).resolve()
        if not self.dataset.is_dir() or not self.manifest_path.is_file():
            raise ValueError("TRACK2_SYNTHETIC_DATASET_OR_MANIFEST_REQUIRED")
        if self.manifest_path.parent != self.dataset:
            raise ValueError("TRACK2_SYNTHETIC_MANIFEST_MUST_BE_DATASET_LOCAL")
        try:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("TRACK2_SYNTHETIC_MANIFEST_INVALID") from exc
        self.validation_profile_path = Path(validation_profile_path).resolve()
        self.validation_profile = load_track2_validation_profile(self.validation_profile_path)
        self.profile = load_track2_synthetic_scenario_profile(self.profile_path)
        if self.validation_profile.strategy_id != self.profile.strategy_id:
            raise ValueError("TRACK2_VALIDATION_AND_SYNTHETIC_PROFILE_STRATEGY_MISMATCH")
        self._validate_manifest_and_dataset()
        self.run_id = "UNBOUND"
        self.preflight_checked = 0
        self.preflight_passed = 0
        self.blocked_entries: list[dict[str, str]] = []
        self.candidate_scenarios: list[dict[str, Any]] = []
        self.quote_scenario_manifest_path = (
            Path(quote_scenario_manifest_path).resolve() if quote_scenario_manifest_path is not None else None
        )
        self.quote_scenario_manifest: dict[str, Any] | None = None
        self.quote_scenario_rows: tuple[dict[str, Any], ...] = ()
        self.quote_scenario_rows_by_timestamp: dict[str, tuple[dict[str, Any], ...]] = {}
        self.quote_scenario_candidate_by_timestamp: dict[str, dict[str, Any]] = {}
        self.quote_scenario_identity_ids: frozenset[str] = frozenset()
        self._active_candidate_role_by_instrument_id: dict[str, str] = {}
        self._active_candidate_timestamp: str | None = None
        if self.quote_scenario_manifest_path is not None:
            self._load_quote_scenario()

    def _validate_manifest_and_dataset(self) -> None:
        manifest = self.manifest
        if (manifest.get("schema_version") != EXPECTED_MANIFEST_SCHEMA
                or manifest.get("acceptance") != "ACCEPTED_FOR_PROJECT_VERIFICATION"
                or manifest.get("registry_id") != "KOSPI200_ACCEPTED_MARKET_DATA_20261114"):
            raise ValueError("TRACK2_ACCEPTED_DATA_MANIFEST_IDENTITY_INVALID")
        days = manifest.get("days")
        if not isinstance(days, list) or not days:
            raise ValueError("TRACK2_ACCEPTED_DATA_MANIFEST_DAYS_REQUIRED")
        total_rows = 0
        dataset_fingerprint = []
        seen_dates: set[str] = set()
        for day in days:
            if not isinstance(day, dict):
                raise ValueError("TRACK2_ACCEPTED_DATA_MANIFEST_DAY_INVALID")
            trading_date = str(day.get("date") or "")
            if len(trading_date) != 8 or not trading_date.isdigit() or trading_date in seen_dates:
                raise ValueError("TRACK2_ACCEPTED_DATA_MANIFEST_DATE_INVALID")
            seen_dates.add(trading_date)
            file_path = self.dataset / f"{trading_date}.jsonl"
            if not file_path.is_file():
                raise ValueError(f"TRACK2_ACCEPTED_DATA_PARTITION_MISSING:{trading_date}")
            digest = sha256(file_path.read_bytes()).hexdigest()
            if digest != str(day.get("sha256") or "").lower():
                raise ValueError(f"TRACK2_ACCEPTED_DATA_PARTITION_HASH_MISMATCH:{trading_date}")
            rows = 0
            with file_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if (record.get("schema") != "reference-canonical-market-tick-v1"
                            or record.get("provenance") != "DERIVED_SCENARIO"
                            or record.get("dataset") != manifest["registry_id"]
                            or record.get("scenario_metadata", {}).get("accepted_for_project_verification") is not True):
                        raise ValueError("TRACK2_ACCEPTED_DATA_RECORD_PROVENANCE_INVALID")
                    rows += 1
            if rows != day.get("rows"):
                raise ValueError(f"TRACK2_ACCEPTED_DATA_PARTITION_ROW_COUNT_MISMATCH:{trading_date}")
            total_rows += rows
            dataset_fingerprint.append(f"{trading_date}:{digest}:{rows}")
        if total_rows != manifest.get("rows_total"):
            raise ValueError("TRACK2_ACCEPTED_DATA_TOTAL_ROW_COUNT_MISMATCH")
        actual_files = {p.stem for p in self.dataset.glob("*.jsonl")}
        if actual_files != seen_dates:
            raise ValueError("TRACK2_ACCEPTED_DATA_PARTITION_SET_MISMATCH")
        self.evidence = Track2SyntheticValidationEvidence(
            manifest_path=str(self.manifest_path),
            manifest_sha256=sha256(self.manifest_path.read_bytes()).hexdigest(),
            dataset_sha256=sha256("\n".join(dataset_fingerprint).encode("utf-8")).hexdigest(),
            profile_path=str(self.profile_path), profile_sha256=self.profile.profile_sha256,
            validation_profile_path=str(self.validation_profile_path),
            validation_profile_sha256=self.validation_profile.profile_sha256,
            registry_id=str(manifest["registry_id"]), rows=total_rows,
            trading_dates=tuple(sorted(seen_dates)),
        )

    @staticmethod
    def _scenario_local_file(root: Path, item: Any, field: str) -> Path:
        if not isinstance(item, dict):
            raise ValueError(f"TRACK2_QUOTE_SCENARIO_{field.upper()}_INVALID")
        name = str(item.get("path") or "").strip()
        if not name or Path(name).name != name:
            raise ValueError(f"TRACK2_QUOTE_SCENARIO_{field.upper()}_PATH_INVALID")
        path = (root / name).resolve()
        if path.parent != root or not path.is_file():
            raise ValueError(f"TRACK2_QUOTE_SCENARIO_{field.upper()}_FILE_REQUIRED")
        digest = sha256(path.read_bytes()).hexdigest()
        if digest != str(item.get("sha256") or "").lower():
            raise ValueError(f"TRACK2_QUOTE_SCENARIO_{field.upper()}_HASH_MISMATCH")
        return path

    def _load_quote_scenario(self) -> None:
        from contracts.kis_option_product_spec import (
            KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER, kis_option_contract_multiplier,
        )
        from verification.track2_synthetic_quote_scenario import (
            IDENTITY_PREFIX, KIS_OPTION_PRODUCT_SPEC_URL, LEG_ORDER, PROVENANCE,
            validate_quote_snapshot,
        )

        manifest_path = self.quote_scenario_manifest_path
        if manifest_path is None or not manifest_path.is_file():
            raise ValueError("TRACK2_QUOTE_SCENARIO_MANIFEST_REQUIRED")
        root = manifest_path.parent
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("TRACK2_QUOTE_SCENARIO_MANIFEST_INVALID") from exc
        scenario_identity = (
            manifest.get("schema_version"), manifest.get("scenario_id"), manifest.get("status"),
        )
        allowed_scenarios = {
            (
                "track2-synthetic-four-leg-scenario-manifest-v2",
                "S2-SYNTHETIC-FOUR-LEG-QUOTES-v2",
                "SYNTHETIC_VALIDATION_ONLY_NOT_MARKET_EVIDENCE",
            ),
            (
                "track2-synthetic-four-leg-scenario-manifest-v3",
                "S2-MARKET-CALIBRATED-FOUR-LEG-QUOTES-v3",
                "SYNTHETIC_VALIDATION_ONLY_MARKET_CALIBRATED_NOT_OBSERVED_QUOTES",
            ),
        }
        if scenario_identity not in allowed_scenarios or manifest.get("strategy_id") != STRATEGY_ID:
            raise ValueError("TRACK2_QUOTE_SCENARIO_MANIFEST_IDENTITY_INVALID")
        if manifest.get("schema_version", "").endswith("v3"):
            calibration = manifest.get("anchor_policy") or {}
            if (manifest.get("price_model") != "BLACK_SCHOLES_ZERO_RATE_EMPIRICAL_IV_V1"
                    or calibration.get("trading_date_scope") != "SAME_DATE_ONLY"
                    or calibration.get("future_option_observations_allowed") is not False
                    or calibration.get("max_source_anchor_age_seconds") != 900
                    or (manifest.get("empirical_spread_reference") or {}).get("not_a_production_u21_approval") is not True):
                raise ValueError("TRACK2_MARKET_CALIBRATION_MANIFEST_POLICY_INVALID")
        if manifest.get("base_manifest_sha256") != self.evidence.manifest_sha256:
            raise ValueError("TRACK2_QUOTE_SCENARIO_BASE_MANIFEST_MISMATCH")
        if manifest.get("base_registry_id") != self.evidence.registry_id:
            raise ValueError("TRACK2_QUOTE_SCENARIO_BASE_REGISTRY_MISMATCH")
        if manifest.get("profile_id") != self.profile.profile_id or manifest.get("profile_sha256") != self.profile.profile_sha256:
            raise ValueError("TRACK2_QUOTE_SCENARIO_PROFILE_MISMATCH")
        specification = manifest.get("contract_specification") or {}
        expected_multiplier = kis_option_contract_multiplier("STANDARD")
        if (expected_multiplier != KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER
                or specification != {
                    "product_family": "STANDARD", "contract_cycle": "MONTHLY",
                    "multiplier": str(expected_multiplier),
                    "multiplier_provenance": "KIS_OFFICIAL_PRODUCT_SPEC",
                    "source_url": KIS_OPTION_PRODUCT_SPEC_URL,
                }):
            raise ValueError("TRACK2_QUOTE_SCENARIO_CONTRACT_SPECIFICATION_INVALID")
        u21 = manifest.get("u21") or {}
        if (str(u21.get("max_age_seconds")) != str(self.profile.u21_quote_policy["max_age_seconds"])
                or str(u21.get("max_spread")) != str(self.profile.u21_quote_policy["max_spread"])
                or str(u21.get("tick_size")) != str(self.profile.u21_quote_policy["tick_size"])):
            raise ValueError("TRACK2_QUOTE_SCENARIO_U21_POLICY_MISMATCH")

        candidate_path = self._scenario_local_file(root, manifest.get("candidate_input_file"), "candidate_input")
        quote_path = self._scenario_local_file(root, manifest.get("quote_file"), "quote_file")
        try:
            candidates = json.loads(candidate_path.read_text(encoding="utf-8"))
            rows = [json.loads(line) for line in quote_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("TRACK2_QUOTE_SCENARIO_CONTENT_INVALID") from exc
        if (not isinstance(candidates, list) or len(candidates) != manifest.get("candidate_count")
                or len(rows) != manifest.get("quote_rows")
                or len(rows) != len(candidates) * 4
                or (manifest.get("quote_file") or {}).get("rows") != len(rows)):
            raise ValueError("TRACK2_QUOTE_SCENARIO_ROW_COUNTS_INVALID")

        candidate_by_timestamp: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError("TRACK2_QUOTE_SCENARIO_CANDIDATE_INVALID")
            timestamp = str(candidate.get("observed_at") or "")
            try:
                observed = datetime.fromisoformat(timestamp)
            except ValueError as exc:
                raise ValueError("TRACK2_QUOTE_SCENARIO_CANDIDATE_TIMESTAMP_INVALID") from exc
            if observed.tzinfo is None or timestamp in candidate_by_timestamp:
                raise ValueError("TRACK2_QUOTE_SCENARIO_CANDIDATE_TIMESTAMP_DUPLICATE_OR_NAIVE")
            candidate_by_timestamp[timestamp] = candidate

        grouped: dict[str, list[dict[str, Any]]] = {}
        identity_rows: dict[str, dict[str, Any]] = {}
        seen_candidate_role: set[tuple[str, str]] = set()
        tick_size = Decimal(str(self.profile.u21_quote_policy["tick_size"]))
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("TRACK2_QUOTE_SCENARIO_QUOTE_ROW_INVALID")
            timestamp = str(row.get("timestamp") or "")
            candidate = candidate_by_timestamp.get(timestamp)
            role = str(row.get("leg_role") or "")
            if candidate is None or role not in TRACK2_LEG_ORDER:
                raise ValueError("TRACK2_QUOTE_SCENARIO_UNMATCHED_CANDIDATE_OR_ROLE")
            pair = (str(row.get("candidate_id") or ""), role)
            if pair in seen_candidate_role:
                raise ValueError("TRACK2_QUOTE_SCENARIO_DUPLICATE_CANDIDATE_LEG")
            seen_candidate_role.add(pair)
            expected_leg = next((leg for leg in candidate.get("legs", []) if leg.get("role") == role), None)
            if (expected_leg is None or str(row.get("expiry")) != str(candidate.get("expiry"))
                    or str(row.get("option_type")).upper() != str(expected_leg.get("option_type")).upper()
                    or Decimal(str(row.get("strike"))) != Decimal(str(expected_leg.get("strike")))):
                raise ValueError("TRACK2_QUOTE_SCENARIO_CANDIDATE_CONTRACT_MISMATCH")
            instrument_id = str(row.get("instrument_id") or "")
            if (not instrument_id.startswith(IDENTITY_PREFIX)
                    or row.get("contract_identity_authority") != "SYNTHETIC_ONLY_NOT_KIS_MASTER"
                    or row.get("source") != PROVENANCE or row.get("provenance") != "SYNTHETIC"
                    or row.get("source_registry_id") != self.evidence.registry_id
                    or row.get("source_manifest_sha256") != self.evidence.manifest_sha256
                    or row.get("scenario_profile_id") != self.profile.profile_id
                    or row.get("scenario_profile_sha256") != self.profile.profile_sha256
                    or row.get("contract_product_family") != "STANDARD"
                    or row.get("contract_cycle") != "MONTHLY"
                    or str(row.get("contract_multiplier")) != str(expected_multiplier)
                    or row.get("contract_multiplier_provenance") != "KIS_OFFICIAL_PRODUCT_SPEC"
                    or row.get("contract_multiplier_source") != KIS_OPTION_PRODUCT_SPEC_URL):
                raise ValueError("TRACK2_QUOTE_SCENARIO_IDENTITY_OR_PROVENANCE_INVALID")
            if instrument_id in identity_rows and identity_rows[instrument_id] != row:
                comparable = ("expiry", "option_type", "strike", "contract_multiplier", "contract_product_family", "contract_cycle")
                if any(identity_rows[instrument_id].get(key) != row.get(key) for key in comparable):
                    raise ValueError("TRACK2_QUOTE_SCENARIO_IDENTITY_CONFLICT")
            identity_rows[instrument_id] = row
            observed = datetime.fromisoformat(timestamp)
            validate_quote_snapshot(
                row, observed_at=observed,
                max_age_seconds=Decimal(str(self.profile.u21_quote_policy["max_age_seconds"])),
                max_spread=Decimal(str(self.profile.u21_quote_policy["max_spread"])),
            )
            if manifest.get("schema_version", "").endswith("v3"):
                calibration = row.get("market_calibration") or {}
                anchor_times = calibration.get("iv_anchor_timestamps", []) + calibration.get("spread_anchor_timestamps", [])
                if (row.get("model") != "BLACK_SCHOLES_ZERO_RATE_EMPIRICAL_IV_V1"
                        or calibration.get("last_price_basis") != "MODEL_FAIR_VALUE_NOT_OBSERVED_TRADE"
                        or calibration.get("target_quote_age_seconds") != 0
                        or not anchor_times
                        or any(datetime.fromisoformat(str(value)) > observed for value in anchor_times)
                        or int(calibration.get("source_anchor_max_age_seconds", 10**9)) > 900):
                    raise ValueError("TRACK2_MARKET_CALIBRATED_QUOTE_PROVENANCE_INVALID")
            for quantity_field in ("volume", "bid_quantity", "ask_quantity"):
                if int(row.get(quantity_field, 0)) <= 0:
                    raise ValueError(f"TRACK2_QUOTE_SCENARIO_{quantity_field.upper()}_INVALID")
            bid, ask = Decimal(str(row["bid"])), Decimal(str(row["ask"]))
            if (bid / tick_size) != (bid / tick_size).to_integral_value() or (ask / tick_size) != (ask / tick_size).to_integral_value():
                raise ValueError("TRACK2_QUOTE_SCENARIO_TICK_SIZE_INVALID")
            grouped.setdefault(timestamp, []).append(row)

        for timestamp, candidate in candidate_by_timestamp.items():
            candidate_rows = grouped.get(timestamp, [])
            if len(candidate_rows) != 4 or {row["leg_role"] for row in candidate_rows} != set(TRACK2_LEG_ORDER):
                raise ValueError("TRACK2_QUOTE_SCENARIO_INCOMPLETE_FOUR_LEG_SNAPSHOT")
            if len({row["candidate_id"] for row in candidate_rows}) != 1:
                raise ValueError("TRACK2_QUOTE_SCENARIO_CANDIDATE_ID_MISMATCH")

        # Every sidecar timestamp must coincide with an event in the accepted base stream.
        available_timestamps: set[str] = set()
        for partition in self.dataset.glob("*.jsonl"):
            with partition.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        record = json.loads(line)
                        available_timestamps.add(str(record.get("tick", {}).get("timestamp") or ""))
        if not set(candidate_by_timestamp).issubset(available_timestamps):
            raise ValueError("TRACK2_QUOTE_SCENARIO_TIMESTAMP_NOT_IN_BASE_STREAM")

        self.quote_scenario_manifest = manifest
        self.quote_scenario_rows = tuple(rows)
        self.quote_scenario_rows_by_timestamp = {key: tuple(value) for key, value in grouped.items()}
        self.quote_scenario_candidate_by_timestamp = candidate_by_timestamp
        self.quote_scenario_identity_ids = frozenset(identity_rows)

    def register_quote_scenario_contracts(self, option_master: Any) -> int:
        if not self.quote_scenario_rows:
            return 0
        from core.option.option_master import KisOptionContractIdentity
        from contracts.option_expiry import require_exact_option_expiry
        from contracts.kis_option_product_spec import kis_option_contract_multiplier
        registered = 0
        identities: dict[str, Any] = {}
        for row in self.quote_scenario_rows:
            instrument_id = str(row["instrument_id"])
            identity = KisOptionContractIdentity(
                shrn_iscd=instrument_id, stnd_iscd=None,
                expiry=require_exact_option_expiry(str(row["expiry"])),
                option_type=str(row["option_type"]).upper(),
                strike=Decimal(str(row["strike"])), info_type="SYNTHETIC",
                contract_multiplier=kis_option_contract_multiplier("STANDARD"),
                instrument_family="STANDARD", product_series="MONTHLY",
            )
            existing = identities.get(instrument_id)
            if existing is not None and existing != identity:
                raise ValueError("TRACK2_QUOTE_SCENARIO_OPTION_MASTER_IDENTITY_CONFLICT")
            identities[instrument_id] = identity
        for instrument_id, identity in identities.items():
            existing = option_master.get_contract_identity(instrument_id)
            if existing is not None and existing != identity:
                raise ValueError("TRACK2_QUOTE_SCENARIO_OPTION_MASTER_PREEXISTING_CONFLICT")
            if existing is None:
                option_master.register_contract_identity(identity)
                registered += 1
        return registered

    def quote_scenario_ticks(self) -> tuple[Any, ...]:
        from types import SimpleNamespace
        return tuple(SimpleNamespace(
            timestamp=str(row["timestamp"]),
            instrument_id=str(row["instrument_id"]),
            synthetic_contract_id=str(row["instrument_id"]),
            symbol=str(row["instrument_id"]),
            source_instrument_code=str(row["instrument_id"]),
            instrument_identity_status="SYNTHETIC_IDENTITY_ONLY",
            expiry=str(row["expiry"]), option_type=str(row["option_type"]).upper(),
            strike_price=float(Decimal(str(row["strike"]))),
            contract_multiplier=float(Decimal(str(row["contract_multiplier"]))),
            bid_price=float(Decimal(str(row["bid"]))),
            ask_price=float(Decimal(str(row["ask"]))),
            last_price=float(Decimal(str(row["last"]))),
            volume=int(row.get("volume", 1)),
            bid_quantity=int(row.get("bid_quantity", 1)),
            ask_quantity=int(row.get("ask_quantity", 1)),
        ) for row in self.quote_scenario_rows)

    def validate_candidate_scenario(self, candidate: dict[str, Any]) -> None:
        timestamp = str(candidate.get("observed_at") or "")
        expected = self.quote_scenario_candidate_by_timestamp.get(timestamp)
        if expected is None:
            raise ValueError("TRACK2_QUOTE_SCENARIO_CANDIDATE_NOT_FOUND")
        if (str(candidate.get("expiry")) != str(expected.get("expiry"))
                or Decimal(str(candidate.get("underlying_price"))) != Decimal(str(expected.get("underlying_price")))):
            raise ValueError("TRACK2_QUOTE_SCENARIO_CANDIDATE_INPUT_MISMATCH")
        actual_legs = {str(item.get("role")): item for item in candidate.get("legs", [])}
        expected_legs = {str(item.get("role")): item for item in expected.get("legs", [])}
        if set(actual_legs) != set(TRACK2_LEG_ORDER) or set(expected_legs) != set(TRACK2_LEG_ORDER):
            raise ValueError("TRACK2_QUOTE_SCENARIO_CANDIDATE_LEGS_INVALID")
        for role in TRACK2_LEG_ORDER:
            if (str(actual_legs[role].get("option_type")).upper() != str(expected_legs[role].get("option_type")).upper()
                    or Decimal(str(actual_legs[role].get("strike"))) != Decimal(str(expected_legs[role].get("strike")))):
                raise ValueError(f"TRACK2_QUOTE_SCENARIO_CANDIDATE_LEG_MISMATCH:{role}")
        rows = self.quote_scenario_rows_by_timestamp.get(timestamp, ())
        role_by_identity = {str(row.get("instrument_id")): str(row.get("leg_role")) for row in rows}
        if len(rows) != 4 or len(role_by_identity) != 4:
            raise ValueError("TRACK2_QUOTE_SCENARIO_CANDIDATE_IDENTITY_ROLE_MAP_INVALID")
        self._active_candidate_timestamp = timestamp
        self._active_candidate_role_by_instrument_id = role_by_identity

    def bind_run_id(self, run_id: str) -> None:
        value = str(run_id or "").strip()
        if not value:
            raise ValueError("TRACK2_SYNTHETIC_RUN_ID_REQUIRED")
        if self.run_id != "UNBOUND" and self.run_id != value:
            raise ValueError("TRACK2_SYNTHETIC_RUN_ID_ALREADY_BOUND")
        self.run_id = value

    def adapt_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict) or record.get("provenance") != "DERIVED_SCENARIO":
            raise ValueError("TRACK2_SYNTHETIC_RECORD_PROVENANCE_REQUIRED")
        if record.get("dataset") != self.evidence.registry_id or record.get("schema") != "reference-canonical-market-tick-v1":
            raise ValueError("TRACK2_SYNTHETIC_RECORD_DATASET_MISMATCH")
        tick = record.get("tick")
        metadata = record.get("scenario_metadata")
        if not isinstance(tick, dict) or not isinstance(metadata, dict):
            raise ValueError("TRACK2_SYNTHETIC_RECORD_TICK_AND_METADATA_REQUIRED")
        source_code = str(tick.get("source_instrument_code") or tick.get("instrument_id") or "").strip()
        if not source_code or str(tick.get("instrument_id") or "") != source_code:
            raise ValueError("TRACK2_SYNTHETIC_SOURCE_INSTRUMENT_CODE_MISMATCH")
        expiry = require_exact_option_expiry(str(tick.get("expiry") or ""))
        option_type = str(tick.get("option_type") or "").upper()
        strike = Decimal(str(tick.get("strike_price") or "0"))
        multiplier = Decimal(str(tick.get("contract_multiplier") or "0"))
        if option_type not in {"CALL", "PUT"} or strike <= 0 or multiplier <= 0:
            raise ValueError("TRACK2_SYNTHETIC_CONTRACT_FIELDS_INVALID")
        if str(tick.get("contract_class") or "").lower() != "monthly":
            raise ValueError("TRACK2_SYNTHETIC_MONTHLY_CONTRACT_REQUIRED")
        identity_key = "|".join((self.evidence.registry_id, source_code, expiry, option_type, str(strike)))
        synthetic_id = SYNTHETIC_ID_PREFIX + sha256(identity_key.encode("utf-8")).hexdigest()[:32]
        adapted = dict(record)
        adapted_tick = dict(tick)
        observed_date = datetime.fromisoformat(str(tick["timestamp"])).date()
        expiry_date = datetime.strptime(expiry, "%Y%m%d").date()
        if expiry_date < observed_date:
            raise ValueError("TRACK2_SYNTHETIC_EXPIRY_BEFORE_OBSERVATION")
        dte_trading_days = sum(
            1 for day_offset in range(1, (expiry_date - observed_date).days + 1)
            if (observed_date.fromordinal(observed_date.toordinal() + day_offset)).weekday() < 5
        )
        orderbook = metadata.get("synthetic_order_book_top")
        if not isinstance(orderbook, dict):
            raise ValueError("TRACK2_SYNTHETIC_ORDERBOOK_PROVENANCE_REQUIRED")
        bid_quantity = int(orderbook.get("bid_quantity") or 0)
        ask_quantity = int(orderbook.get("ask_quantity") or 0)
        if bid_quantity <= 0 or ask_quantity <= 0:
            raise ValueError("TRACK2_SYNTHETIC_ORDERBOOK_QUANTITIES_INVALID")
        adapted_tick.update({
            "bid_quantity": bid_quantity,
            "ask_quantity": ask_quantity,
            "synthetic_contract_id": synthetic_id,
            "instrument_id": synthetic_id,
            "symbol": synthetic_id,
            "source_instrument_code": source_code,
            "instrument_identity_status": "SYNTHETIC_IDENTITY_ONLY",
            "validation_only": True,
            "scenario_id": SCENARIO_ID,
            "scenario_group_id": str(metadata.get("trading_date") or ""),
            "scenario_regime": "ACCEPTED_MARKET_DATA_DERIVED",
            "dte_trading_days": dte_trading_days,
        })
        adapted_metadata = dict(metadata)
        adapted_metadata.update({
            "validation_only": True,
            "scenario_id": SCENARIO_ID,
            "contract_identity_authority": "SYNTHETIC_ONLY",
            "identity_source_status": "SYNTHETIC_IDENTITY_ONLY",
            "synthetic_identity_namespace": SYNTHETIC_ID_PREFIX,
            "source_instrument_code_preserved": source_code,
            "instrument_family": "STANDARD",
            "product_series": "MONTHLY",
            "dte_provenance": "SYNTHETIC_WEEKDAY_CALENDAR_ONLY_NOT_EXCHANGE_CALENDAR_EVIDENCE",
            "dte_trading_days": dte_trading_days,
        })
        adapted["tick"] = adapted_tick
        adapted["scenario_metadata"] = adapted_metadata
        return adapted

    def apply_to_strategy(self, strategy: Any, *, synthetic_sources: Any) -> None:
        if getattr(strategy, "strategy_id", None) != STRATEGY_ID:
            raise ValueError("TRACK2_SYNTHETIC_STRATEGY_MISMATCH")
        if not str(getattr(synthetic_sources, "source_name", "")).startswith("SYNTHETIC:"):
            raise ValueError("TRACK2_SYNTHETIC_RUNTIME_SOURCE_REQUIRED")
        if getattr(strategy, "runtime_config_verified", None) is not False:
            raise ValueError("TRACK2_OPERATIONAL_RUNTIME_DEFAULT_CHANGED")
        if getattr(strategy, "risk_limits_available", None) is not False:
            raise ValueError("TRACK2_OPERATIONAL_RISK_DEFAULT_CHANGED")
        # Instance-local validation gates; production registry defaults remain fail-closed.
        strategy.runtime_config_verified = True
        strategy.risk_limits_available = True
        strategy.STOP_LOSS_RATIO = Decimal(str(self.profile.u18_exit_policy["stop_loss_ratio"]))
        strategy.TRAILING_ACTIVATION_RATIO = Decimal(str(self.profile.u18_exit_policy["trailing_activation_ratio"]))
        strategy.TRAILING_PULLBACK_RATIO = Decimal(str(self.profile.u18_exit_policy["trailing_pullback_ratio"]))

    def pnl_evidence(self, *, snapshot: Any, reports: Any, is_entry: bool,
                     market: Any, synthetic_sources: Any) -> dict[str, Any]:
        """Return explicitly synthetic-only U18 evidence; never used outside this adapter."""
        from decimal import Decimal

        cost_model = self.profile.synthetic_cost_models
        fee_per_leg = Decimal(str(cost_model["fee_krw_per_leg"]))
        slippage_ticks = Decimal(str(cost_model["slippage_ticks_per_leg"]))
        tick_size = Decimal(str(cost_model["tick_size"]))
        leg_by_id = {str(leg.leg_id): leg for leg in tuple(snapshot.legs)}
        filled_reports = [item for item in tuple(reports or ())
                          if int(getattr(item, "filled_quantity", 0) or 0) > 0]
        modeled_fee = Decimal("0")
        modeled_slippage = Decimal("0")
        for report in filled_reports:
            leg = leg_by_id.get(str(getattr(report, "leg_id", "") or ""))
            if leg is None:
                return {"fees": None, "slippage": None, "net_pnl": None,
                        "quote_freshness_verified": None}
            quantity = Decimal(str(getattr(report, "filled_quantity", 0)))
            modeled_fee += fee_per_leg
            modeled_slippage += (slippage_ticks * tick_size
                                 * Decimal(str(leg.contract_multiplier)) * quantity)
        if is_entry:
            fees = modeled_fee
            slippage = modeled_slippage
        else:
            fees = (Decimal(str(snapshot.fees)) + modeled_fee
                    if snapshot.fees is not None else None)
            slippage = (Decimal(str(snapshot.slippage)) + modeled_slippage
                        if snapshot.slippage is not None else None)
        current_tick = getattr(synthetic_sources, "_tick", None)
        try:
            current_instant = datetime.fromisoformat(str(current_tick.timestamp))
        except (AttributeError, TypeError, ValueError):
            current_instant = None
        max_age = float(self.profile.u21_quote_policy["max_age_seconds"])
        max_spread = Decimal(str(self.profile.u21_quote_policy["max_spread"]))
        freshness = bool(snapshot.complete and len(snapshot.legs) == 4
                         and current_instant is not None and current_instant.tzinfo is not None)
        for leg in tuple(snapshot.legs):
            if int(getattr(leg, "quantity", 0) or 0) <= 0:
                freshness = False
                break
            quote = getattr(market, "option_quotes_by_instrument_id", {}).get(leg.instrument_id)
            if not isinstance(quote, dict) or quote.get("source") != "SYNTHETIC:DERIVED_SCENARIO":
                freshness = False
                break
            try:
                instant = datetime.fromisoformat(str(leg.quote_observed_at))
                bid = Decimal(str(leg.quote_bid))
                ask = Decimal(str(leg.quote_ask))
                quote_instant = datetime.fromisoformat(str(quote["timestamp"]))
            except (KeyError, TypeError, ValueError):
                freshness = False
                break
            age = (current_instant - instant).total_seconds()
            if (leg.mark_source != "BID_ASK_MID" or instant.tzinfo is None
                    or quote_instant != instant or age < 0 or age > max_age
                    or bid <= 0 or ask < bid or ask - bid > max_spread
                    or leg.instrument_id not in self.quote_scenario_identity_ids):
                freshness = False
                break
        net_pnl = None
        if fees is not None and slippage is not None:
            net_pnl = (Decimal(str(snapshot.realized_pnl))
                       + Decimal(str(snapshot.unrealized_pnl)) - fees - slippage)
        return {
            "fees": float(fees) if fees is not None else None,
            "slippage": float(slippage) if slippage is not None else None,
            "net_pnl": float(net_pnl) if net_pnl is not None else None,
            "quote_freshness_verified": True if freshness else None,
        }

    def validate_execution_identity(self, plan: Any, stored_identity: Any, master_identity: Any) -> bool:
        """Allow only identities present in the loaded synthetic quote sidecar."""
        if not self.quote_scenario_rows or getattr(plan, "strategy_id", None) != STRATEGY_ID:
            return False
        from contracts.kis_option_product_spec import kis_option_contract_multiplier
        from verification.track2_synthetic_quote_scenario import KIS_OPTION_PRODUCT_SPEC_URL
        standard_multiplier = kis_option_contract_multiplier("STANDARD")
        instrument_id = str(getattr(stored_identity, "instrument_id", "") or "")
        if instrument_id not in self.quote_scenario_identity_ids:
            return False
        if (getattr(stored_identity, "identity_source", None) != "SYNTHETIC:DERIVED_SCENARIO"
                or master_identity is None
                or str(getattr(master_identity, "shrn_iscd", "")) != instrument_id
                or getattr(master_identity, "stnd_iscd", None) is not None
                or str(getattr(master_identity, "instrument_family", "")).upper() != "STANDARD"
                or str(getattr(master_identity, "product_series", "")).upper() != "MONTHLY"
                or str(getattr(master_identity, "expiry", "")) != str(getattr(stored_identity, "expiry", ""))
                or str(getattr(master_identity, "option_type", "")).upper() != str(getattr(stored_identity, "option_type", "")).upper()
                or Decimal(str(getattr(master_identity, "strike", "0"))) != Decimal(str(getattr(stored_identity, "strike", "-1")))
                or Decimal(str(getattr(master_identity, "contract_multiplier", "0"))) != standard_multiplier
                or Decimal(str(getattr(stored_identity, "contract_multiplier", "0"))) != standard_multiplier):
            return False
        matching_quote_rows = [
            row for row in self.quote_scenario_rows
            if str(row.get("instrument_id")) == instrument_id
            and str(row.get("contract_multiplier_provenance")) == "KIS_OFFICIAL_PRODUCT_SPEC"
            and str(row.get("contract_multiplier_source")) == KIS_OPTION_PRODUCT_SPEC_URL
        ]
        if not matching_quote_rows:
            return False
        if str(getattr(plan, "purpose", "") or "").upper() in {
            "ASYMMETRIC_TRAP_WIDE", "ASYMMETRIC_TRAP_NARROW",
        }:
            matching_plan_legs = [
                leg for leg in tuple(getattr(plan, "legs", ()) or ())
                if str(getattr(leg, "option_type", "")).upper()
                    == str(getattr(stored_identity, "option_type", "")).upper()
                and Decimal(str(getattr(leg, "strike", "-1")))
                    == Decimal(str(getattr(stored_identity, "strike", "-2")))
            ]
            if len(matching_plan_legs) != 1:
                return False
            plan_role = str(getattr(matching_plan_legs[0], "leg_id", "") or "")
            if self._active_candidate_role_by_instrument_id.get(instrument_id) != plan_role:
                return False
        return True

    def create_option_contract_source(self, option_master: Any) -> Track2SyntheticOptionContractSource:
        return Track2SyntheticOptionContractSource(
            option_master, profile=self.profile, scenario_identity_ids=self.quote_scenario_identity_ids,
        )

    def bind_entry_plan_preflight(self, *, strategy: Any, contract_source: Track2SyntheticOptionContractSource, market: Any) -> None:
        if getattr(strategy, "strategy_id", None) != STRATEGY_ID:
            raise ValueError("TRACK2_SYNTHETIC_PREFLIGHT_STRATEGY_MISMATCH")

        def preflight(*, current_price: Decimal, active_vol: float, base_vol: float, observed_at: datetime) -> bool:
            self.preflight_checked += 1
            expiry = contract_source.nearest_expiry(as_of=observed_at.date())
            try:
                selection = contract_source.select(expiry=expiry, current_price=current_price)
                trap = strategy.build_asymmetric_trap(selection.atm_strike, active_vol, base_vol)
                short = trap["signals"][0]["strikes"]
                long = trap["signals"][1]["strikes"]
                # The execution-plan contract defines inner legs as the long legs
                # and outer legs as the short legs (core/oms/multi_leg_plan.py).
                requested = _track2_preflight_legs_from_long_short(long, short)
                leg_roles = ("inner_put", "inner_call", "outer_put", "outer_call")
                candidate = {
                    "candidate_id": f"S2-CANDIDATE-{len(self.candidate_scenarios) + 1:03d}",
                    "observed_at": observed_at.isoformat(),
                    "expiry": expiry,
                    "underlying_price": str(current_price),
                    "source_observation_id": f"accepted-runtime-v2-event:{observed_at.isoformat()}",
                    "legs": [
                        {"role": role, "option_type": option_type, "strike": str(strike)}
                        for role, (option_type, strike) in zip(leg_roles, requested, strict=True)
                    ],
                }
                self.candidate_scenarios.append(candidate)
                if self.quote_scenario_rows:
                    self.validate_candidate_scenario(candidate)
                quotes = getattr(market, "option_quotes_by_instrument_id", {})
                for option_type, strike in requested:
                    identity = contract_source.resolve_identity(
                        expiry=expiry, option_type=option_type, strike=strike,
                    )
                    quote = quotes.get(identity.shrn_iscd)
                    if not isinstance(quote, dict):
                        raise ValueError(f"CURRENT_SYNTHETIC_QUOTE_MISSING:{option_type}:{strike}")
                    if quote.get("source") != "SYNTHETIC:DERIVED_SCENARIO":
                        raise ValueError(f"CURRENT_SYNTHETIC_QUOTE_SOURCE_INVALID:{option_type}:{strike}")
                    quote_at = datetime.fromisoformat(str(quote.get("timestamp") or ""))
                    age_seconds = (observed_at - quote_at).total_seconds()
                    max_age = float(self.profile.u21_quote_policy["max_age_seconds"])
                    max_spread = Decimal(str(self.profile.u21_quote_policy["max_spread"]))
                    bid = Decimal(str(quote.get("bid")))
                    ask = Decimal(str(quote.get("ask")))
                    if age_seconds < 0 or age_seconds > max_age:
                        raise ValueError(f"SYNTHETIC_QUOTE_AGE_EXCEEDED:{option_type}:{strike}:{age_seconds:.3f}s")
                    if bid <= 0 or ask < bid or ask - bid > max_spread:
                        raise ValueError(f"SYNTHETIC_QUOTE_SPREAD_EXCEEDED:{option_type}:{strike}:{ask-bid}")
            except (ValueError, KeyError, TypeError) as exc:
                if len(self.blocked_entries) < 250:
                    self.blocked_entries.append({
                        "timestamp": observed_at.isoformat(),
                        "reason": str(exc),
                    })
                return False
            self.preflight_passed += 1
            return True

        strategy.validation_only_entry_plan_preflight = preflight

    def freshness_verdict(self, *, plan: Any, leg: Any, identity: Any, command: Any,
                          option_master: Any, market: Any, synthetic_sources: Any) -> FreshnessVerdict:
        instrument_id = str(getattr(command, "instrument_id", "") or "")
        symbol = str(getattr(command, "broker_symbol", "") or instrument_id)
        policy_version = "S2-ACCEPTED-DATA-SYNTHETIC-FRESHNESS-v1"

        def verdict(status: FreshnessStatus, reason: str, instant=None, digest=None):
            return FreshnessVerdict(
                status=status, reason=reason, policy_version=policy_version,
                source="SYNTHETIC:ACCEPTED_MARKET_DATA_RUNTIME_V2", tr_id="S2_ACCEPTED_DATA_MANIFEST",
                environment="SYNTHETIC_VALIDATION_ONLY", instrument_id=instrument_id,
                symbol=symbol, source_instant=instant, received_at=instant, evidence_sha256=digest,
            )

        if (getattr(plan, "strategy_id", None) != STRATEGY_ID
                or not instrument_id.startswith(SYNTHETIC_ID_PREFIX)
                or getattr(identity, "instrument_id", None) != instrument_id):
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "S2_SYNTHETIC_IDENTITY_REQUIRED")
        quote = getattr(market, "option_quotes_by_instrument_id", {}).get(instrument_id)
        if not isinstance(quote, dict) or quote.get("source") != "SYNTHETIC:DERIVED_SCENARIO":
            return verdict(FreshnessStatus.UNKNOWN, "S2_SYNTHETIC_QUOTE_MISSING")
        try:
            bid = Decimal(str(quote["bid"]))
            ask = Decimal(str(quote["ask"]))
            last = Decimal(str(quote["last"]))
            instant = datetime.fromisoformat(str(quote["timestamp"]))
        except (KeyError, TypeError, ValueError):
            return verdict(FreshnessStatus.UNKNOWN, "S2_SYNTHETIC_QUOTE_FIELDS_INVALID")
        current_tick = getattr(synthetic_sources, "_tick", None)
        current_instant = datetime.fromisoformat(str(current_tick.timestamp)) if current_tick is not None else None
        max_age = float(self.profile.u21_quote_policy["max_age_seconds"])
        max_spread = Decimal(str(self.profile.u21_quote_policy["max_spread"]))
        if (instant.tzinfo is None or current_instant is None or current_instant.tzinfo is None
                or bid <= 0 or ask < bid or last <= 0):
            return verdict(FreshnessStatus.UNKNOWN, "S2_SYNTHETIC_QUOTE_FIELDS_INVALID", instant)
        age_seconds = (current_instant - instant).total_seconds()
        if age_seconds < 0 or age_seconds > max_age:
            return verdict(FreshnessStatus.STALE, "S2_SYNTHETIC_QUOTE_AGE_EXCEEDED", instant)
        if ask - bid > max_spread:
            return verdict(FreshnessStatus.UNKNOWN, "S2_SYNTHETIC_QUOTE_SPREAD_EXCEEDED", instant)
        digest_payload = "|".join((
            self.evidence.manifest_sha256, self.evidence.dataset_sha256, instant.isoformat(),
            instrument_id, str(bid), str(ask), str(last),
        ))
        digest = sha256(digest_payload.encode("utf-8")).hexdigest()
        return verdict(FreshnessStatus.FRESH, "S2_MANIFEST_BOUND_SYNTHETIC_QUOTE", instant, digest)


__all__ = (
    "SYNTHETIC_ID_PREFIX", "Track2SyntheticOptionContractSource",
    "Track2ValidationOnlyRuntimeAdapter",
)
