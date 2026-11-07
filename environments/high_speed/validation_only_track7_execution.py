"""Manifest-bound validation-only Strategy 7 synthetic execution gate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from environments.high_speed.validation_only_option_fee_model import calculate_option_fee

STRATEGY_ID = "track7_volatility_skew_weekly_insurance"
SYNTHETIC_ID_PREFIX = "SYNTHETIC_CONTRACT:"


@dataclass(frozen=True)
class S7ValidationEvidence:
    manifest_path: str
    manifest_sha256: str
    dataset_sha256: str
    risk_profile_path: str
    risk_profile_sha256: str
    scenario_id: str
    max_gross_premium_krw: int
    max_group_gross_premium_krw: int
    max_loss_krw: int
    max_concurrent_groups: int
    operational_reference_limit_krw: int


class S7ValidationOnlyRuntimeAdapter:
    """Instance-local S7 readiness, risk, identity and freshness boundary."""

    def __init__(self, *, dataset: str | Path, manifest_path: str | Path,
                 risk_profile_path: str | Path) -> None:
        self.dataset = Path(dataset).resolve()
        self.manifest_path = Path(manifest_path).resolve()
        self.risk_profile_path = Path(risk_profile_path).resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        profile_payload = json.loads(self.risk_profile_path.read_text(encoding="utf-8"))
        m = self.manifest
        if (m.get("schema_version") != "q25-a2-1-s6-syn-evt-manifest-v1"
                or m.get("source_type") != "DERIVED_SCENARIO"
                or m.get("provenance") != "DERIVED_SCENARIO"
                or m.get("synthetic") is not True
                or m.get("validation_only") is not True
                or m.get("runtime_eligible") is not False
                or m.get("production_runtime_eligible") is not False
                or m.get("identity_source_status") != "BLOCKED_IDENTITY_OWNER_UNRESOLVED"
                or m.get("contract_identity_authority") != "SYNTHETIC_ONLY"
                or m.get("expiry_is_authoritative") is not False
                or m.get("strategy_id") != "strategy7_weekly"):
            raise ValueError("S7_VALIDATION_MANIFEST_INVALID")
        output = (Path.cwd() / str(m.get("output_path", ""))).resolve()
        if (output != self.dataset and output.parent != self.dataset) or not output.is_file():
            raise ValueError("S7_VALIDATION_DATASET_PATH_MISMATCH")
        dataset_hash = sha256(output.read_bytes()).hexdigest()
        manifest_hash = sha256(self.manifest_path.read_bytes()).hexdigest()
        if (dataset_hash != str(m.get("dataset_sha256", "")).lower()
                or dataset_hash != str(m.get("output_sha256", "")).lower()):
            raise ValueError("S7_VALIDATION_DATASET_HASH_MISMATCH")
        if (profile_payload.get("validation_only") is not True
                or profile_payload.get("runtime_eligible") is not False
                or profile_payload.get("production_runtime_eligible") is not False
                or profile_payload.get("allow_kis_api") is not False
                or profile_payload.get("allow_live_orders") is not False
                or profile_payload.get("allow_real_account") is not False
                or profile_payload.get("operational_config_mutated") is not False
                or profile_payload.get("risk_checks_enabled") is not True
                or profile_payload.get("enforcement_mode") != "VALIDATION_ONLY_ALLOW_WITH_OVERAGE_AUDIT"
                or profile_payload.get("contract_identity_authority") != "SYNTHETIC_ONLY"
                or profile_payload.get("expiry_is_authoritative") is not False):
            raise ValueError("S7_VALIDATION_RISK_PROFILE_INVALID")
        expected_manifest = str(self.manifest_path.relative_to(Path.cwd())).replace("\\", "/")
        if str(profile_payload.get("dataset_manifest", "")).replace("\\", "/") != expected_manifest:
            raise ValueError("S7_VALIDATION_RISK_MANIFEST_MISMATCH")
        if (profile_payload.get("dataset_sha256") != dataset_hash
                or profile_payload.get("manifest_sha256") != manifest_hash):
            raise ValueError("S7_VALIDATION_RISK_HASH_MISMATCH")
        profile = profile_payload.get("profiles", {}).get("track7_weekly_insurance")
        if not isinstance(profile, dict):
            raise ValueError("S7_VALIDATION_RISK_PROFILE_MISSING")
        limits = (
            int(profile.get("max_gross_premium_outlay_krw", 0)),
            int(profile_payload.get("max_group_gross_premium_krw", 0)),
            int(profile.get("max_loss_krw", 0)),
            int(profile.get("max_concurrent_groups", 0)),
            int(profile.get("operational_reference_limit_krw", 0)),
        )
        if min(limits) <= 0 or limits[3] != 2:
            raise ValueError("S7_VALIDATION_RISK_LIMITS_INVALID")
        required_audit = set(profile_payload.get("audit_fields_required", ()))
        expected_audit = {
            "computed_gross_premium_krw", "computed_max_loss_krw",
            "computed_concurrent_exposure_krw", "operational_reference_overage_krw",
            "validation_budget_overage_krw", "run_id", "scenario_id",
            "manifest_sha256", "dataset_sha256",
        }
        if not expected_audit.issubset(required_audit):
            raise ValueError("S7_VALIDATION_RISK_AUDIT_FIELDS_INVALID")
        self.profile = profile
        self.evidence = S7ValidationEvidence(
            manifest_path=str(self.manifest_path), manifest_sha256=manifest_hash,
            dataset_sha256=dataset_hash, risk_profile_path=str(self.risk_profile_path),
            risk_profile_sha256=sha256(self.risk_profile_path.read_bytes()).hexdigest(),
            scenario_id=str(m["scenario_id"]), max_gross_premium_krw=limits[0],
            max_group_gross_premium_krw=limits[1], max_loss_krw=limits[2],
            max_concurrent_groups=limits[3], operational_reference_limit_krw=limits[4],
        )
        self.run_id = "UNBOUND"
        self._reserved: dict[str, dict[str, Decimal]] = {}
        self._reserved_entry_fees: dict[str, dict[str, Decimal]] = {}
        self._group_expiry_by_id: dict[str, str] = {}
        self.risk_audit_records: list[dict[str, Any]] = []

    def bind_run_id(self, run_id: str) -> None:
        if not run_id or not str(run_id).strip():
            raise ValueError("S7_VALIDATION_RUN_ID_REQUIRED")
        if self.run_id != "UNBOUND" and self.run_id != str(run_id):
            raise ValueError("S7_VALIDATION_RUN_ID_ALREADY_BOUND")
        self.run_id = str(run_id)

    def apply_to_strategy(self, strategy: Any, *, synthetic_sources: Any) -> None:
        if getattr(strategy, "strategy_id", None) != STRATEGY_ID:
            raise ValueError("S7_VALIDATION_STRATEGY_MISMATCH")
        if not str(getattr(synthetic_sources, "source_name", "")).startswith("SYNTHETIC:"):
            raise ValueError("S7_VALIDATION_SYNTHETIC_SOURCE_REQUIRED")
        if getattr(strategy, "runtime_config_verified", None) is not False:
            raise ValueError("S7_OPERATIONAL_READINESS_DEFAULT_CHANGED")
        if getattr(strategy, "risk_limits_available", None) is not False:
            raise ValueError("S7_OPERATIONAL_RISK_DEFAULT_CHANGED")
        # Validation-only instance-local override. Constructor and operational defaults stay false.
        strategy.runtime_config_verified = True
        strategy.risk_limits_available = True

    def release_group(self, group_id: str) -> None:
        self._reserved.pop(str(group_id), None)
        self._reserved_entry_fees.pop(str(group_id), None)
        self._group_expiry_by_id.pop(str(group_id), None)

    def release_all_groups(self) -> None:
        self._reserved.clear()
        self._reserved_entry_fees.clear()
        self._group_expiry_by_id.clear()

    def validate_group(self, plan: Any, prepared: list[tuple]) -> None:
        if getattr(plan, "strategy_id", None) != STRATEGY_ID:
            raise ValueError("S7_VALIDATION_ORDER_SCOPE_INVALID")
        purpose = str(getattr(plan, "purpose", "") or "")
        group_id = str(getattr(plan, "group_id", "") or "")
        if not group_id:
            raise ValueError("S7_VALIDATION_GROUP_ID_REQUIRED")
        if purpose in {"WEEKLY_INSURANCE_CLOSE_PUT", "WEEKLY_INSURANCE_CLOSE_CALL", "WEEKLY_INSURANCE_CLOSE"}:
            if not prepared or len(prepared) not in {1, 2}:
                raise ValueError("S7_VALIDATION_CLOSE_LEG_COUNT_INVALID")
            for leg, identity, _client, _command, _canonical, bid, ask in prepared:
                if (str(getattr(leg, "side", "")).upper() != "SELL"
                        or not str(getattr(identity, "instrument_id", "")).startswith(SYNTHETIC_ID_PREFIX)
                        or Decimal(str(bid)) <= 0 or Decimal(str(ask)) < Decimal(str(bid))):
                    raise ValueError("S7_VALIDATION_CLOSE_IDENTITY_OR_QUOTE_INVALID")
            return

        sequential_leg = {
            "WEEKLY_INSURANCE_ENTRY_PUT": "put",
            "WEEKLY_INSURANCE_ENTRY_CALL": "call",
        }.get(purpose)
        if purpose not in {"WEEKLY_INSURANCE_ENTRY", *{
            "WEEKLY_INSURANCE_ENTRY_PUT", "WEEKLY_INSURANCE_ENTRY_CALL"
        }}:
            raise ValueError("S7_VALIDATION_ENTRY_PURPOSE_INVALID")
        expected_count = 1 if sequential_leg else 2
        if len(prepared) != expected_count:
            raise ValueError("S7_VALIDATION_ENTRY_LEG_COUNT_INVALID")

        legs: dict[str, Decimal] = {}
        leg_fee_reserves: dict[str, Decimal] = {}
        expiry_values: set[str] = set()
        for leg, identity, _client, _command, _canonical, bid, ask in prepared:
            leg_id = str(getattr(leg, "leg_id", "")).lower()
            option_type = str(getattr(identity, "option_type", "")).upper()
            instrument_id = str(getattr(identity, "instrument_id", ""))
            if (leg_id not in {"put", "call"} or option_type != leg_id.upper()
                    or str(getattr(leg, "side", "")).upper() != "BUY"
                    or int(getattr(leg, "quantity", 0)) != 1
                    or not instrument_id.startswith(SYNTHETIC_ID_PREFIX)
                    or str(getattr(identity, "identity_source", "")) != "OPTION_MASTER"
                    or getattr(identity, "contract_multiplier", None) is None
                    or (sequential_leg is not None and leg_id != sequential_leg)):
                raise ValueError("S7_VALIDATION_ENTRY_IDENTITY_INVALID")
            bid_d, ask_d = Decimal(str(bid)), Decimal(str(ask))
            multiplier = Decimal(str(identity.contract_multiplier))
            if bid_d <= 0 or ask_d <= bid_d or multiplier <= 0:
                raise ValueError("S7_VALIDATION_ENTRY_QUOTE_INVALID")
            expiry = str(identity.expiry).replace("-", "")[:8]
            expiry_values.add(expiry)
            legs[leg_id] = ask_d * multiplier
            fee_result = calculate_option_fee(ask_d, multiplier, int(getattr(leg, "quantity", 1)))
            leg_fee_reserves[leg_id] = Decimal(int(fee_result["total_fee_krw"]))
        if len(expiry_values) != 1:
            raise ValueError("S7_VALIDATION_ENTRY_EXPIRY_MISMATCH")
        expiry = next(iter(expiry_values))

        existing = dict(self._reserved.get(group_id, {}))
        existing_fee_reserves = dict(self._reserved_entry_fees.get(group_id, {}))
        prior_expiry = self._group_expiry_by_id.get(group_id)
        if prior_expiry is not None and prior_expiry != expiry:
            raise ValueError("S7_VALIDATION_GROUP_EXPIRY_CHANGED")
        if sequential_leg == "put" and "put" in existing:
            raise ValueError("S7_VALIDATION_PUT_ENTRY_DUPLICATE")
        if sequential_leg == "call" and "put" not in existing:
            raise ValueError("S7_VALIDATION_CALL_REQUIRES_FILLED_PUT_RESERVATION")
        if sequential_leg == "call" and "call" in existing:
            raise ValueError("S7_VALIDATION_CALL_ENTRY_DUPLICATE")
        if group_id not in self._reserved and len(self._reserved) >= self.evidence.max_concurrent_groups:
            raise ValueError("S7_VALIDATION_CONCURRENT_GROUP_LIMIT_EXCEEDED")

        candidate = dict(existing)
        candidate_fee_reserves = dict(existing_fee_reserves)
        for leg_id, amount in legs.items():
            candidate[leg_id] = max(candidate.get(leg_id, Decimal("0")), amount)
            candidate_fee_reserves[leg_id] = leg_fee_reserves[leg_id]
        group_gross = sum(candidate.values(), Decimal("0"))
        group_fee_reserve = sum(candidate_fee_reserves.values(), Decimal("0"))
        concurrent_gross = sum(
            (sum(candidate_group.values(), Decimal("0")) if key == group_id
             else sum(candidate_group.values(), Decimal("0"))
             for key, candidate_group in self._reserved.items()),
            Decimal("0"),
        )
        if group_id not in self._reserved:
            concurrent_gross += group_gross
        else:
            concurrent_gross = sum(
                (sum(candidate.values(), Decimal("0")) if key == group_id
                 else sum(value.values(), Decimal("0")))
                for key, value in self._reserved.items()
            )
        concurrent_fee_reserve = group_fee_reserve + sum(
            sum(value.values(), Decimal("0"))
            for key, value in self._reserved_entry_fees.items()
            if key != group_id
        )
        audit = {
            "run_id": self.run_id, "scenario_id": self.evidence.scenario_id,
            "manifest_sha256": self.evidence.manifest_sha256,
            "dataset_sha256": self.evidence.dataset_sha256, "group_id": group_id,
            "expiry": expiry, "entry_leg": sequential_leg or "PUT_CALL_PAIR",
            "computed_gross_premium_krw": str(group_gross),
            "computed_max_loss_krw": str(group_gross + group_fee_reserve),
            "computed_entry_fee_reserve_krw": str(group_fee_reserve),
            "computed_concurrent_exposure_krw": str(concurrent_gross),
            "computed_concurrent_exposure_including_entry_fees_krw": str(concurrent_gross + concurrent_fee_reserve),
            "operational_reference_overage_krw": str(max(Decimal("0"), group_gross - Decimal(self.evidence.operational_reference_limit_krw))),
            "validation_budget_overage_krw": str(max(Decimal("0"), concurrent_gross - Decimal(self.evidence.max_gross_premium_krw))),
            "validation_budget_overage_including_entry_fees_krw": str(max(Decimal("0"), concurrent_gross + concurrent_fee_reserve - Decimal(self.evidence.max_gross_premium_krw))),
            "status": "ALLOW",
        }
        if group_gross > Decimal(self.evidence.max_group_gross_premium_krw):
            audit["status"] = "BLOCKED_VALIDATION_GROUP_PREMIUM_LIMIT"
            self.risk_audit_records.append(audit)
            raise ValueError("S7_VALIDATION_GROUP_PREMIUM_LIMIT_EXCEEDED")
        if (concurrent_gross > Decimal(self.evidence.max_gross_premium_krw)
                or group_gross + group_fee_reserve > Decimal(self.evidence.max_loss_krw)
                or concurrent_gross + concurrent_fee_reserve > Decimal(self.evidence.max_loss_krw)):
            audit["status"] = "BLOCKED_VALIDATION_CONCURRENT_PREMIUM_LIMIT"
            self.risk_audit_records.append(audit)
            raise ValueError("S7_VALIDATION_CONCURRENT_PREMIUM_LIMIT_EXCEEDED")
        self._reserved[group_id] = candidate
        self._reserved_entry_fees[group_id] = candidate_fee_reserves
        self._group_expiry_by_id[group_id] = expiry
        self.risk_audit_records.append(audit)

    def freshness_verdict(self, *, plan: Any, identity: Any, command: Any,
                          option_master: Any, market: Any, synthetic_sources: Any) -> FreshnessVerdict:
        instrument_id = str(getattr(command, "instrument_id", "") or "")
        symbol = str(getattr(command, "broker_symbol", "") or "")
        policy = "Q25-S7-SYNTHETIC-FRESHNESS-v1"

        def verdict(status: FreshnessStatus, reason: str, observed=None, digest=None):
            return FreshnessVerdict(
                status=status, reason=reason, policy_version=policy,
                source="SYNTHETIC:DERIVED_SCENARIO", tr_id="Q25_S7_MANIFEST",
                environment="SYNTHETIC_VALIDATION_ONLY", instrument_id=instrument_id,
                symbol=symbol, source_instant=observed, received_at=observed,
                evidence_sha256=digest,
            )

        if getattr(plan, "strategy_id", None) != STRATEGY_ID or not instrument_id.startswith(SYNTHETIC_ID_PREFIX):
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "S7_SYNTHETIC_IDENTITY_REQUIRED")
        master = option_master.get_contract_identity(symbol)
        if (master is None or str(getattr(master, "shrn_iscd", "")) != instrument_id
                or getattr(master, "stnd_iscd", None) is not None
                or str(getattr(master, "option_type", "")).upper() != str(getattr(identity, "option_type", "")).upper()
                or Decimal(str(getattr(master, "strike", "0"))) != Decimal(str(getattr(identity, "strike", "0")))
                or str(getattr(master, "expiry", "")).replace("-", "")[:8] != str(getattr(identity, "expiry", "")).replace("-", "")[:8]
                or Decimal(str(getattr(master, "contract_multiplier", "0"))) != Decimal(str(getattr(identity, "contract_multiplier", "0")))):
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "S7_OPTION_MASTER_IDENTITY_MISMATCH")
        quote = next((value for key, value in getattr(market, "option_quotes", {}).items()
            if isinstance(key, tuple) and len(key) == 3
            and str(key[0]).upper() == str(identity.option_type).upper()
            and Decimal(str(key[1])) == Decimal(str(identity.strike))
            and str(key[2]).replace("-", "")[:8] == str(identity.expiry).replace("-", "")[:8]), None)
        if not isinstance(quote, dict):
            return verdict(FreshnessStatus.UNKNOWN, "S7_SYNTHETIC_QUOTE_MISSING")
        try:
            bid, ask, last = (Decimal(str(quote[k])) for k in ("bid", "ask", "last"))
            observed = datetime.fromisoformat(str(quote["timestamp"]))
            replay_now = datetime.fromisoformat(str(synthetic_sources._tick.timestamp))
        except Exception:
            return verdict(FreshnessStatus.UNKNOWN, "S7_SYNTHETIC_QUOTE_FIELDS_INVALID")
        if (not observed.tzinfo or not replay_now.tzinfo or observed != replay_now
                or bid <= 0 or ask <= bid or last <= 0):
            return verdict(FreshnessStatus.STALE, "S7_QUOTE_MUST_MATCH_CURRENT_REPLAY_INSTANT", observed)
        digest = sha256(
            f"{self.evidence.manifest_sha256}|{self.evidence.dataset_sha256}|{observed.isoformat()}|{instrument_id}|{bid}|{ask}|{last}".encode()
        ).hexdigest()
        return verdict(FreshnessStatus.FRESH, "S7_MANIFEST_BOUND_SYNTHETIC_QUOTE", observed, digest)
