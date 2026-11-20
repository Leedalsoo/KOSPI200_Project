from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

from contracts.types import OptionInstrumentIdentity
from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
from contracts.market_data_freshness import (
    FreshnessEvidence,
    FreshnessPolicy,
    evaluate_freshness,
)
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExpectedGroupManifest,
    U19Position,
)
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick


@dataclass(frozen=True)
class ValidationOnlyS2CandidateTick(ReferenceCanonicalMarketTick):
    candidate_id: str = ""
    leg_role: str = ""
    u21_quote_side: str = ""


@dataclass(frozen=True)
class ValidationOnlyS2IdentityEvidence:
    candidate_id: str
    leg_role: str
    identity: OptionInstrumentIdentity
    contract_identity_authority: str
    contract_multiplier_provenance: str
    accepted_manifest_sha256: str
    scenario_manifest_sha256: str
    quote_sidecar_sha256: str
    profile_sha256: str
    derived_identity_digest: str


class ValidationOnlyS2ScenarioAlternativeProvider:
    """Independent synthetic broker/freshness alternative for the S2 replay fixture.

    It reads the accepted Runtime v2 manifest and the derived four-leg sidecar.
    Its broker positions are generated from the scenario role map and explicit
    scenario quantity, never copied from VSSF account or execution-ledger state.
    This provider is an alternative-path validation fixture, not a Live provider.
    """

    VERSION = "Q25-A8-T7-S2-SYNTHETIC-ALTERNATIVE-v1"
    ROLE_SIDE: ClassVar[dict[str, str]] = {
        "inner_put": "BUY",
        "inner_call": "BUY",
        "outer_put": "SELL",
        "outer_call": "SELL",
    }

    def __init__(
        self,
        *,
        project_root: str | Path,
        run_id: str,
        vssf_adapter: Any,
        candidate_id: str = "S2-CANDIDATE-001",
        scenario_quantity: int = 1,
        position_phase: str = "PRE_ENTRY",
    ) -> None:
        if not str(run_id).strip():
            raise ValueError("T7_RUN_ID_REQUIRED")
        if not candidate_id.strip():
            raise ValueError("T7_CANDIDATE_ID_REQUIRED")
        if not isinstance(scenario_quantity, int) or scenario_quantity <= 0:
            raise ValueError("T7_SCENARIO_QUANTITY_MUST_BE_POSITIVE")
        self.root = Path(project_root).resolve()
        self.run_id = str(run_id)
        self.vssf_adapter = vssf_adapter
        self.candidate_id = candidate_id
        phase = str(position_phase).strip().upper()
        if phase not in {"PRE_ENTRY", "POST_ENTRY"}:
            raise ValueError("T7_POSITION_PHASE_INVALID")
        self.scenario_quantity = scenario_quantity
        self.position_phase = phase
        self.last_diagnostic = "NOT_EVALUATED"
        self.scenario_dir = (
            self.root / "data" / "derived_scenario"
            / "q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
        )
        self.accepted_manifest_path = (
            self.root / "data" / "accepted_market_data" / "runtime_v2" / "manifest.json"
        )
        self.profile_path = (
            self.root / "config" / "validation_only" / "track2"
            / "synthetic_scenario_profile.market_calibrated.v2.json"
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _hash_json(value: Any) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _aware(value: Any, code: str) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(code)
        return value

    def _load_verified_sources(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, str]]:
        manifest_path = self.scenario_dir / "manifest.json"
        quotes_path = self.scenario_dir / "four_leg_quotes.jsonl"
        candidates_path = self.scenario_dir / "candidate_inputs.json"
        if not all(path.is_file() for path in (
            manifest_path, quotes_path, candidates_path,
            self.accepted_manifest_path, self.profile_path,
        )):
            raise FileNotFoundError("T7_ACCEPTED_OR_SCENARIO_SOURCE_FILE_MISSING")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        accepted_manifest = json.loads(self.accepted_manifest_path.read_text(encoding="utf-8"))
        profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        expected_hashes = {
            "accepted_manifest": "7657c90f13a81a7f98a8ccd075a259c8ec9795477a2a0541366094cd87e0360f",
            "scenario_manifest": "13580e010c34c74a1787bffb6b6b72adebdc4964f848937c0894bfa0fd4918b7",
            "quotes": "466c796c536d48a91fd548e6c61c597da4bde558bd56a079cc8956a9f882786e",
            "candidate_inputs": "d2d96b35d0402c1bdf8a6b07e771e9bdc593772985610dc68d3fd74f615b5a32",
            "profile": "c0607c405abba4d2500bd8d5572db0270a9bdc61ab7e4943b1fd3c73d6181b18",
        }
        paths = {
            "accepted_manifest": self.accepted_manifest_path,
            "scenario_manifest": manifest_path,
            "quotes": quotes_path,
            "candidate_inputs": candidates_path,
            "profile": self.profile_path,
        }
        actual_hashes = {key: self._sha256(path) for key, path in paths.items()}
        if actual_hashes != expected_hashes:
            raise ValueError("T7_ACCEPTED_OR_SCENARIO_SOURCE_HASH_MISMATCH")
        if manifest.get("base_manifest_sha256") != actual_hashes["accepted_manifest"]:
            raise ValueError("T7_SCENARIO_BASE_MANIFEST_CROSSWALK_MISMATCH")
        if accepted_manifest.get("registry_id") != manifest.get("base_registry_id"):
            raise ValueError("T7_ACCEPTED_REGISTRY_ID_MISMATCH")
        if not str(manifest.get("status", "")).startswith("SYNTHETIC_VALIDATION_ONLY"):
            raise ValueError("T7_SCENARIO_STATUS_NOT_VALIDATION_ONLY")
        recovery_policy = profile.get("U19_recovery_policy", {})
        if recovery_policy.get("broker_position_source") != "VALIDATION_ONLY:BROKER_EXCHANGE" or recovery_policy.get("ledger_source") != "VALIDATION_ONLY:EXECUTION_LEDGER":
            raise ValueError("T7_U19_SYNTHETIC_SOURCE_POLICY_MISMATCH")
        if (
            manifest.get("execution_enabled") is not False
            or manifest.get("order_submission_enabled") is not False
            or manifest.get("live_api_enabled") is not False
            or manifest.get("real_vts_api_enabled") is not False
            or profile.get("profile_type") != "SYNTHETIC_SCENARIO_ONLY"
        ):
            raise ValueError("T7_SCENARIO_VALIDATION_ONLY_BOUNDARY_INVALID")

        for partition in manifest.get("base_data_partitions", ()):
            day = str(partition.get("date") or "")
            partition_path = self.accepted_manifest_path.parent / f"{day}.jsonl"
            if not partition_path.is_file() or self._sha256(partition_path) != partition.get("sha256"):
                raise ValueError(f"T7_ACCEPTED_PARTITION_HASH_MISMATCH:{day}")

        candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
        candidate = next(
            (row for row in candidates if row.get("candidate_id") == self.candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError(f"T7_SCENARIO_CANDIDATE_NOT_FOUND:{self.candidate_id}")
        quotes = [
            json.loads(line)
            for line in quotes_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        selected_quotes = [row for row in quotes if row.get("candidate_id") == self.candidate_id]
        if len(selected_quotes) != 4:
            raise ValueError("T7_SCENARIO_MUST_HAVE_EXACTLY_FOUR_QUOTES")
        return manifest, candidate, profile, selected_quotes, actual_hashes

    def build_option_identity_evidence(self) -> tuple[ValidationOnlyS2IdentityEvidence, ...]:
        """Rehydrate exact validation-only option identities from the hash-verified sidecar."""
        _manifest, candidate, _profile, quotes, hashes = self._load_verified_sources()
        expected_legs = {
            str(leg.get("role")): leg
            for leg in candidate.get("legs", ())
            if isinstance(leg, dict) and leg.get("role")
        }
        rows_by_role = {str(row.get("leg_role")): row for row in quotes}
        if (
            set(expected_legs) != set(self.ROLE_SIDE)
            or len(rows_by_role) != 4
            or set(rows_by_role) != set(self.ROLE_SIDE)
            or len({str(row.get("instrument_id")) for row in quotes}) != 4
        ):
            raise ValueError("T7_S2_IDENTITY_ROLE_OR_INSTRUMENT_SET_MISMATCH")

        evidence: list[ValidationOnlyS2IdentityEvidence] = []
        for role in self.ROLE_SIDE:
            row = rows_by_role[role]
            expected_leg = expected_legs[role]
            authority = str(row.get("contract_identity_authority") or "")
            source = str(row.get("source") or "")
            provenance = str(row.get("provenance") or "")
            if (
                authority != "SYNTHETIC_ONLY_NOT_KIS_MASTER"
                or source != "SYNTHETIC:DERIVED_SCENARIO"
                or provenance != "SYNTHETIC"
            ):
                raise ValueError(f"T7_S2_IDENTITY_AUTHORITY_NOT_VALIDATION_ONLY:{role}")
            instrument_id = str(row.get("instrument_id") or "").strip()
            option_type = str(row.get("option_type") or "").upper()
            expiry = str(row.get("expiry") or "")
            try:
                exact_expiry = require_exact_option_expiry(expiry)
            except CanonicalOptionExpiryError as exc:
                raise ValueError(f"T7_S2_IDENTITY_EXPIRY_INVALID:{role}") from exc
            strike = Decimal(str(row.get("strike")))
            multiplier = Decimal(str(row.get("contract_multiplier")))
            if (
                not instrument_id.startswith("SYNTHETIC_CONTRACT:")
                or option_type not in {"CALL", "PUT"}
                or option_type != str(expected_leg.get("option_type") or "").upper()
                or strike <= 0
                or strike != Decimal(str(expected_leg.get("strike")))
                or exact_expiry != str(candidate.get("expiry"))
                or multiplier <= 0
            ):
                raise ValueError(f"T7_S2_IDENTITY_CONTRACT_FIELDS_MISMATCH:{role}")
            identity = OptionInstrumentIdentity(
                instrument_id=instrument_id,
                symbol=instrument_id,
                expiry=exact_expiry,
                option_type=option_type,
                strike=strike,
                contract_multiplier=multiplier,
                identity_source="SYNTHETIC:DERIVED_SCENARIO",
            )
            identity_payload = {
                "candidate_id": self.candidate_id,
                "leg_role": role,
                "identity": {
                    "instrument_id": identity.instrument_id,
                    "symbol": identity.symbol,
                    "expiry": identity.expiry,
                    "option_type": identity.option_type,
                    "strike": str(identity.strike),
                    "contract_multiplier": str(identity.contract_multiplier),
                    "identity_source": identity.identity_source,
                },
                "source_hashes": hashes,
                "contract_identity_authority": authority,
                "contract_multiplier_provenance": str(row.get("contract_multiplier_provenance") or ""),
            }
            evidence.append(ValidationOnlyS2IdentityEvidence(
                candidate_id=self.candidate_id,
                leg_role=role,
                identity=identity,
                contract_identity_authority=authority,
                contract_multiplier_provenance=str(row.get("contract_multiplier_provenance") or ""),
                accepted_manifest_sha256=hashes["accepted_manifest"],
                scenario_manifest_sha256=hashes["scenario_manifest"],
                quote_sidecar_sha256=hashes["quotes"],
                profile_sha256=hashes["profile"],
                derived_identity_digest=self._hash_json(identity_payload),
            ))
        return tuple(evidence)

    def is_applicable(self, tick: Any) -> bool:
        explicit_id = str(getattr(tick, "candidate_id", "") or "").strip()
        if explicit_id:
            return explicit_id == self.candidate_id
        timestamp = getattr(tick, "timestamp", None)
        underlying = getattr(tick, "underlying_price", None)
        if timestamp is None or underlying is None:
            return False
        try:
            tick_time = self._aware(timestamp, "T7_TICK_TIMESTAMP_INVALID")
            tick_underlying = Decimal(str(underlying))
        except (TypeError, ValueError, ArithmeticError):
            return False
        candidates_path = self.scenario_dir / "candidate_inputs.json"
        if not candidates_path.is_file():
            return False
        candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
        candidate = next((row for row in candidates if row.get("candidate_id") == self.candidate_id), None)
        if candidate is None:
            return False
        try:
            candidate_time = self._aware(candidate.get("observed_at"), "T7_SCENARIO_TIMESTAMP_INVALID")
            candidate_underlying = Decimal(str(candidate.get("underlying_price")))
        except (TypeError, ValueError, ArithmeticError):
            return False
        return tick_time == candidate_time and tick_underlying == candidate_underlying


    def option_quotes_at(self, observed_at: datetime) -> dict[tuple[str, float, str], dict[str, Any]]:
        """Return the exact four synthetic sidecar quotes only at the scenario instant."""
        _manifest, candidate, _profile, quotes, _hashes = self._load_verified_sources()
        scenario_time = self._aware(candidate.get("observed_at"), "T7_SCENARIO_TIMESTAMP_INVALID")
        if self._aware(observed_at, "T7_QUOTE_PROVIDER_TIMESTAMP_INVALID") != scenario_time:
            return {}
        payload: dict[tuple[str, float, str], dict[str, Any]] = {}
        for row in quotes:
            option_type = str(row["option_type"]).upper()
            strike = float(Decimal(str(row["strike"])))
            expiry = str(row["expiry"])
            instrument_id = str(row["instrument_id"])
            payload[(option_type, strike, expiry)] = {
                "instrument_id": instrument_id,
                "option_type": option_type,
                "strike": strike,
                "expiry": expiry,
                "bid": float(Decimal(str(row["bid"]))),
                "ask": float(Decimal(str(row["ask"]))),
                "last": float(Decimal(str(row["last"]))),
                "timestamp": str(row["timestamp"]),
                "contract_multiplier": float(Decimal(str(row["contract_multiplier"]))),
                "source": "SYNTHETIC:DERIVED_SCENARIO",
                "validation_only": True,
                "contract_identity_authority": "SYNTHETIC_ONLY_NOT_KIS_MASTER",
            }
        if len(payload) != 4:
            raise ValueError("T10_S2_MARKET_QUOTE_PROVIDER_REQUIRES_FOUR_UNIQUE_LEGS")
        return payload

    def build_quote_only_ticks(self, *, seq_id: int = 1) -> tuple[ReferenceCanonicalMarketTick, ...]:
        """Build one no-trade quote event for each manifest-bound synthetic S2 leg."""
        _manifest, candidate, _profile, quotes, _hashes = self._load_verified_sources()
        observed_at = self._aware(candidate.get("observed_at"), "T7_SCENARIO_TIMESTAMP_INVALID")
        expected_legs = {
            str(leg.get("role")): leg
            for leg in candidate.get("legs", ())
            if isinstance(leg, dict) and leg.get("role")
        }
        if set(expected_legs) != set(self.ROLE_SIDE):
            raise ValueError("T10_S2_CANDIDATE_ROLE_SET_MISMATCH")
        rows_by_role = {str(row.get("leg_role")): row for row in quotes}
        if (
            len(rows_by_role) != 4
            or set(rows_by_role) != set(self.ROLE_SIDE)
            or len({str(row.get("instrument_id")) for row in quotes}) != 4
        ):
            raise ValueError("T10_S2_QUOTE_ROLE_OR_INSTRUMENT_SET_MISMATCH")
        ticks = []
        for offset, role in enumerate(self.ROLE_SIDE):
            row = rows_by_role[role]
            expected_leg = expected_legs[role]
            if (
                str(row.get("option_type", "")).upper() != str(expected_leg.get("option_type", "")).upper()
                or Decimal(str(row.get("strike"))) != Decimal(str(expected_leg.get("strike")))
                or str(row.get("expiry")) != str(candidate.get("expiry"))
            ):
                raise ValueError(f"T10_S2_QUOTE_ROLE_CONTRACT_MISMATCH:{role}")
            instrument_id = str(row["instrument_id"])
            ticks.append(ValidationOnlyS2CandidateTick(
                timestamp=observed_at.isoformat(),
                underlying_price=float(Decimal(str(candidate["underlying_price"]))),
                underlying_symbol="KOSPI200",
                underlying_source="SYNTHETIC:ACCEPTED_RUNTIME_V2_SCENARIO_INPUT",
                strike_price=float(Decimal(str(row["strike"]))),
                option_type=str(row["option_type"]).upper(),
                contract_multiplier=float(Decimal(str(row["contract_multiplier"]))),
                bid_price=float(Decimal(str(row["bid"]))),
                ask_price=float(Decimal(str(row["ask"]))),
                last_price=None,
                volume=None,
                bid_quantity=int(row["bid_quantity"]),
                ask_quantity=int(row["ask_quantity"]),
                seq_id=seq_id + offset,
                expiry=str(row["expiry"]),
                symbol=instrument_id,
                option_observed_hour=observed_at.strftime("%H"),
                option_source="SYNTHETIC:DERIVED_SCENARIO",
                instrument_id=instrument_id,
                synthetic_contract_id=instrument_id,
                instrument_identity_status="SYNTHETIC_VALIDATION_ONLY",
                contract_class="synthetic_validation",
                validation_only=True,
                scenario_id=str(candidate.get("scenario_id") or self.candidate_id),
                scenario_group_id=str(candidate.get("scenario_group_id") or self.candidate_id),
                scenario_regime=str(candidate.get("scenario_regime") or "S2_VALIDATION_ONLY"),
                candidate_id=self.candidate_id,
                leg_role=role,
                u21_quote_side=self.ROLE_SIDE[role],
            ))
        return tuple(ticks)

    def build_quote_only_tick(self, *, seq_id: int = 1) -> ReferenceCanonicalMarketTick:
        """Backward-compatible first-leg accessor; full replay uses all four ticks."""
        return self.build_quote_only_ticks(seq_id=seq_id)[0]

    def __call__(self, tick: Any, attempts: tuple[str, ...] = ()):
        del attempts  # The alternative is deterministic and does not alter its source selection.
        self.last_diagnostic = "IN_PROGRESS"
        if not self.is_applicable(tick):
            self.last_diagnostic = "TICK_OUTSIDE_EVIDENCE_SCOPE"
            return None
        manifest, candidate, profile, quotes, hashes = self._load_verified_sources()
        scenario_time = self._aware(candidate.get("observed_at"), "T7_SCENARIO_TIMESTAMP_INVALID")
        as_of = self._aware(getattr(tick, "timestamp", None), "T7_TICK_TIMESTAMP_INVALID")
        if as_of < scenario_time:
            self.last_diagnostic = "T7_TICK_PRECEDES_SYNTHETIC_SCENARIO"
            raise ValueError(self.last_diagnostic)
        tick_underlying_value = getattr(tick, "underlying_price", None)
        if as_of == scenario_time and tick_underlying_value is not None:
            tick_underlying = Decimal(str(tick_underlying_value))
            candidate_underlying = Decimal(str(candidate.get("underlying_price")))
            if tick_underlying != candidate_underlying:
                self.last_diagnostic = "T7_TICK_UNDERLYING_ANCHOR_MISMATCH"
                raise ValueError(self.last_diagnostic)

        expected_legs = {
            str(leg["role"]): (str(leg["option_type"]).upper(), str(leg["strike"]))
            for leg in candidate.get("legs", ())
        }
        if set(expected_legs) != set(self.ROLE_SIDE):
            raise ValueError("T7_SCENARIO_ROLE_MAPPING_INVALID")
        role_contract = manifest.get("candidate_role_mapping_contract", {})
        if role_contract.get("candidate_role_mapping_provenance") != "ALIGNED_TO_EXECUTION_PLAN":
            raise ValueError("T7_SCENARIO_ROLE_MAPPING_PROVENANCE_MISSING")
        if any(role_contract.get(key) != value for key, value in {
            "inner_call": "LONG_CALL", "inner_put": "LONG_PUT",
            "outer_call": "SHORT_CALL", "outer_put": "SHORT_PUT",
        }.items()):
            raise ValueError("T7_SCENARIO_ROLE_SIDE_CROSSWALK_MISMATCH")

        seen_roles: set[str] = set()
        instruments: set[str] = set()
        anchors: list[datetime] = []
        anchor_refs: set[str] = {str(candidate.get("source_observation_id") or "")}
        positions: list[U19Position] = []
        for row in quotes:
            role = str(row.get("leg_role") or "")
            if role not in self.ROLE_SIDE or role in seen_roles:
                raise ValueError("T7_SCENARIO_ROLE_DUPLICATE_OR_UNKNOWN")
            seen_roles.add(role)
            if (
                str(row.get("option_type") or "").upper() != expected_legs[role][0]
                or str(row.get("strike")) != expected_legs[role][1]
                or str(row.get("expiry")) != str(candidate.get("expiry"))
            ):
                raise ValueError(f"T7_SCENARIO_CONTRACT_CROSSWALK_MISMATCH:{role}")
            instrument_id = str(row.get("instrument_id") or "")
            if not instrument_id.startswith("SYNTHETIC_CONTRACT:") or instrument_id in instruments:
                raise ValueError("T7_SYNTHETIC_CONTRACT_ID_INVALID_OR_DUPLICATE")
            instruments.add(instrument_id)
            if row.get("source_manifest_sha256") != hashes["accepted_manifest"]:
                raise ValueError("T7_QUOTE_BASE_MANIFEST_HASH_MISMATCH")
            if row.get("source") != "SYNTHETIC:DERIVED_SCENARIO" or row.get("provenance") != "SYNTHETIC":
                raise ValueError("T7_SCENARIO_SOURCE_NAMESPACE_INVALID")
            if row.get("contract_identity_authority") != "SYNTHETIC_ONLY_NOT_KIS_MASTER":
                raise ValueError("T7_SYNTHETIC_IDENTITY_AUTHORITY_BOUNDARY_INVALID")
            row_time = self._aware(row.get("timestamp"), "T7_QUOTE_TIMESTAMP_INVALID")
            if row_time != scenario_time:
                raise ValueError("T7_SYNTHETIC_QUOTES_NOT_SCENARIO_SYNCHRONIZED")
            calibration = row.get("market_calibration") or {}
            if int(calibration.get("target_quote_age_seconds", -1)) < 0:
                raise ValueError("T7_SYNTHETIC_TARGET_AGE_INVALID")
            if int(calibration.get("target_quote_age_seconds", 10**9)) > int(profile["U21_quote_policy"]["max_age_seconds"]):
                raise ValueError("T7_SYNTHETIC_TARGET_AGE_EXCEEDS_PROFILE")
            anchor_times = tuple(calibration.get("iv_anchor_timestamps", ())) + tuple(calibration.get("spread_anchor_timestamps", ()))
            if not anchor_times:
                raise ValueError(f"T7_SOURCE_ANCHOR_TIMESTAMPS_MISSING:{role}")
            iv_anchor_ids = tuple(calibration.get("iv_anchor_observation_ids", ()))
            spread_anchor_ids = tuple(calibration.get("spread_anchor_observation_ids", ()))
            if len(iv_anchor_ids) != len(tuple(calibration.get("iv_anchor_timestamps", ()))) or len(spread_anchor_ids) != len(tuple(calibration.get("spread_anchor_timestamps", ()))):
                raise ValueError(f"T7_SOURCE_ANCHOR_REFERENCE_COUNT_MISMATCH:{role}")
            anchor_refs.update(str(value) for value in (*iv_anchor_ids, *spread_anchor_ids))
            parsed_anchors = [self._aware(value, "T7_SOURCE_ANCHOR_TIMESTAMP_INVALID") for value in anchor_times]
            if any(value > scenario_time for value in parsed_anchors):
                raise ValueError(f"T7_FUTURE_SOURCE_ANCHOR_REJECTED:{role}")
            max_age = max((scenario_time - value).total_seconds() for value in parsed_anchors)
            if max_age > float(manifest["anchor_policy"]["max_source_anchor_age_seconds"]):
                raise ValueError(f"T7_SOURCE_ANCHOR_AGE_EXCEEDS_MANIFEST:{role}")
            anchors.extend(parsed_anchors)
            multiplier = Decimal(str(row.get("contract_multiplier")))
            if multiplier <= 0:
                raise ValueError("T7_SYNTHETIC_MULTIPLIER_INVALID")
            if self.position_phase == "POST_ENTRY":
                side = self.ROLE_SIDE[role]
                positions.append(U19Position(
                    instrument_id,
                    Decimal(self.scenario_quantity if side == "BUY" else -self.scenario_quantity),
                ))
        if seen_roles != set(self.ROLE_SIDE):
            raise ValueError("T7_SCENARIO_FOUR_LEG_COVERAGE_INCOMPLETE")

        source_anchor_as_of = min(anchors)
        if source_anchor_as_of > scenario_time:
            raise ValueError("T7_SOURCE_ANCHOR_AFTER_SCENARIO")
        group_id = f"VALIDATION_ONLY:RUN:{self.run_id}"
        broker_payload = {
            "version": self.VERSION,
            "candidate_id": self.candidate_id,
            "scenario_timestamp": scenario_time.isoformat(),
            "as_of": as_of.isoformat(),
            "positions": [
                {"instrument_id": row.instrument_id, "signed_quantity": str(row.signed_quantity)}
                for row in sorted(positions, key=lambda value: value.instrument_id)
            ],
            "source_manifest_sha256": hashes["scenario_manifest"],
            "role_mapping": self.ROLE_SIDE,
            "scenario_quantity_per_leg": self.scenario_quantity if self.position_phase == "POST_ENTRY" else 0,
            "position_phase": self.position_phase,
            "validation_only": True,
        }
        manifest_leg_ids = tuple(sorted(str(row["instrument_id"]) for row in quotes))
        manifest_positions = tuple(sorted(
            (
                U19Position(
                    str(row["instrument_id"]),
                    Decimal(self.scenario_quantity if self.ROLE_SIDE[str(row["leg_role"])] == "BUY" else -self.scenario_quantity),
                )
                for row in quotes
            ) if self.position_phase == "POST_ENTRY" else (),
            key=lambda item: item.instrument_id,
        ))
        expected_manifest_id = f"{self.candidate_id}:{self.position_phase}:{scenario_time.isoformat()}"
        expected_manifest_source = "VALIDATION_ONLY:EXPECTED_GROUP_MANIFEST"
        expected_manifest_provenance = (
            f"VALIDATION_ONLY:{self.VERSION}:ACCEPTED={hashes['accepted_manifest']}:SCENARIO={hashes['scenario_manifest']}"
        )
        expected_manifest_payload = {
            "group_id": group_id,
            "manifest_id": expected_manifest_id,
            "source": expected_manifest_source,
            "provenance": expected_manifest_provenance,
            "leg_instrument_ids": list(manifest_leg_ids),
            "expected_positions": [
                {"instrument_id": item.instrument_id, "signed_quantity": str(item.signed_quantity)}
                for item in manifest_positions
            ],
        }
        expected_group_manifest = U19ExpectedGroupManifest(
            group_id=group_id,
            manifest_id=expected_manifest_id,
            source=expected_manifest_source,
            provenance=expected_manifest_provenance,
            leg_instrument_ids=manifest_leg_ids,
            expected_positions=manifest_positions,
            payload_sha256=self._hash_json(expected_manifest_payload),
        )
        broker_snapshot = U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id=f"{self.candidate_id}:{as_of.isoformat()}",
            as_of=as_of,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=tuple(sorted(positions, key=lambda value: value.instrument_id)),
            complete=True,
            capability_verified=True,
            payload_sha256=self._hash_json(broker_payload),
        )

        if str(manifest.get("u21", {}).get("max_age_seconds")) != str(profile["U21_quote_policy"]["max_age_seconds"]):
            raise ValueError("T7_SYNTHETIC_FRESHNESS_POLICY_CROSSWALK_MISMATCH")
        synthetic_policy = FreshnessPolicy(
            version="S2_SYNTHETIC_QUOTE_AGE_5S_V1",
            source_age_enabled=True,
            max_age=timedelta(seconds=int(profile["U21_quote_policy"]["max_age_seconds"])),
            max_future_skew=timedelta(0),
        )
        freshness_evidence = FreshnessEvidence(
            source="SYNTHETIC:DERIVED_SCENARIO",
            endpoint="local-validation-sidecar",
            tr_id="VALIDATION_ONLY:S2_MARKET_CALIBRATED",
            environment="VIRTUAL",
            instrument_id=f"SYNTHETIC_CONTRACT:GROUP:{self.candidate_id}",
            symbol=self.candidate_id,
            raw_source_time=scenario_time.isoformat(),
            source_instant=scenario_time,
            received_at=as_of,
            raw_payload_sha256=hashes["quotes"],
            source_time_semantics_verified=True,
            capability_verified=True,
            candidate_policy_version=synthetic_policy.version,
            metadata={
                "candidate_id": self.candidate_id,
                "profile_id": str(profile["profile_id"]),
                "scenario_manifest_sha256": hashes["scenario_manifest"],
                "accepted_manifest_sha256": hashes["accepted_manifest"],
                "source_anchor_as_of": source_anchor_as_of.isoformat(),
                "validation_only": "true",
            },
        )
        freshness_verdict = evaluate_freshness(
            freshness_evidence,
            policy=synthetic_policy,
            expected_instrument_id=f"SYNTHETIC_CONTRACT:GROUP:{self.candidate_id}",
            expected_symbol=self.candidate_id,
            expected_environment="VIRTUAL",
        )

        candidate_result = self.vssf_adapter.build_candidate(
            as_of=as_of,
            broker_snapshot=broker_snapshot,
            expected_group_manifest=expected_group_manifest,
            freshness_verdict=freshness_verdict,
            source_namespace="SYNTHETIC:DERIVED_SCENARIO",
            deterministic_rule_id=self.VERSION,
            source_manifest_sha256=hashes["scenario_manifest"],
            source_anchor_refs=(
                f"accepted_runtime_v2_manifest#sha256={hashes['accepted_manifest']}",
                f"s2_scenario_manifest#sha256={hashes['scenario_manifest']}",
                *(f"source_anchor:{value}" for value in sorted({anchor.isoformat() for anchor in anchors})),
                *(f"source_observation:{value}" for value in sorted(anchor_refs) if value),
            ),
            source_anchor_as_of=source_anchor_as_of,
            scenario_timestamp=scenario_time,
            evidence_refs=(
                f"s2_four_leg_quotes.jsonl#sha256={hashes['quotes']}",
                f"s2_candidate_inputs.json#sha256={hashes['candidate_inputs']}",
                f"synthetic_profile.json#sha256={hashes['profile']}",
            ),
        )
        self.last_diagnostic = "SYNTHETIC_CANDIDATE_BUILT"
        return candidate_result
