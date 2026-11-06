"""Validation-only Strategy 6 synthetic execution gates.

This module is deliberately separate from production risk configuration and
never grants KIS/Live execution capability. It validates synthetic provenance,
the frozen Strategy 6 risk budget, and per-leg quote freshness for Virtual runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from core.risk.option_hedge_risk_config import DEFAULT_CONFIG_PATH, load_option_hedge_risk_config

STRATEGY_ID = "track6_daily_tail_insurance"
MANIFEST_SCHEMA = "q25-a2-1-s6-syn-evt-manifest-v1"
SYNTHETIC_ID_PREFIX = "SYNTHETIC_CONTRACT:"
DEFAULT_VALIDATION_RISK_PROFILE = Path("config/validation_only/q25_s6_v1/risk_profile.json")


@dataclass(frozen=True)
class Track6SyntheticExecutionEvidence:
    manifest_path: str
    manifest_sha256: str
    dataset_sha256: str
    dataset_rows: int
    config_sha256: str
    risk_profile_path: str
    risk_profile_sha256: str
    scenario_id: str
    configured_capital_krw: int
    max_premium_krw: int
    max_loss_krw: int
    max_concurrent_positions: int
    operational_reference_limit_krw: int
    max_quote_age_seconds: int


class Track6SyntheticExecutionGate:
    """Fail-closed budget and provenance gate for one synthetic S6 entry group."""

    def __init__(self, *, dataset: str | Path, manifest_path: str | Path,
                 config_path: str | Path = DEFAULT_CONFIG_PATH,
                 risk_profile_path: str | Path = DEFAULT_VALIDATION_RISK_PROFILE) -> None:
        self.dataset = Path(dataset).resolve()
        self.manifest_path = Path(manifest_path).resolve()
        self.risk_profile_path = Path(risk_profile_path).resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        m = self.manifest
        if (m.get("schema_version") != MANIFEST_SCHEMA
                or m.get("source_type") != "DERIVED_SCENARIO"
                or m.get("provenance") != "DERIVED_SCENARIO"
                or m.get("synthetic") is not True
                or m.get("validation_only") is not True
                or m.get("production_runtime_eligible") is not False
                or m.get("identity_source_status") != "BLOCKED_IDENTITY_OWNER_UNRESOLVED"):
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_MANIFEST_INVALID")
        output = (Path.cwd() / str(m.get("output_path", ""))).resolve()
        if output != self.dataset / "20261102.jsonl" and output.parent != self.dataset:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_DATASET_PATH_MISMATCH")
        digest = sha256(output.read_bytes()).hexdigest()
        if digest != str(m.get("output_sha256", "")).lower():
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_DATASET_HASH_MISMATCH")
        config = load_option_hedge_risk_config(config_path)
        if config.activation_mode != "DISABLED_UNTIL_RUNTIME_INTEGRATION":
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_OPERATIONAL_CONFIG_MUST_STAY_DISABLED")
        if config.allow_live_orders or config.allow_synthetic_quotes:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_CAPABILITY_MUST_STAY_DISABLED")
        # Operational RiskConfig remains read-only and disabled. The separately
        # approved validation-only profile supplies the synthetic admission cap.
        operational_limit = config.strategies.get(STRATEGY_ID)
        if (operational_limit is None or not operational_limit.enabled or min(
            operational_limit.max_gross_premium_outlay_krw,
            operational_limit.max_loss_krw,
            operational_limit.max_concurrent_positions,
        ) <= 0):
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_OPERATIONAL_REFERENCE_INVALID")

        profile_payload = json.loads(self.risk_profile_path.read_text(encoding="utf-8"))
        if (profile_payload.get("schema_version") != "q25-validation-only-risk-profile-v1"
                or profile_payload.get("validation_only") is not True
                or profile_payload.get("runtime_eligible") is not False
                or profile_payload.get("allow_kis_api") is not False
                or profile_payload.get("allow_live_orders") is not False
                or profile_payload.get("allow_real_account") is not False
                or profile_payload.get("operational_config_mutated") is not False
                or profile_payload.get("operational_config_path") != "config/risk/option-hedge-risk.v1.json"
                or profile_payload.get("risk_checks_enabled") is not True
                or profile_payload.get("enforcement_mode") != "VALIDATION_ONLY_HARD_CAP_WITH_OVERAGE_AUDIT"):
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_RISK_PROFILE_INVALID")
        profile = profile_payload.get("profiles", {}).get(STRATEGY_ID)
        if not isinstance(profile, dict):
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_RISK_PROFILE_MISSING")
        expected_manifest = str(self.manifest_path.relative_to(Path.cwd())).replace("\\", "/")
        configured_manifests = {
            str(value).replace("\\", "/")
            for value in profile.get("dataset_manifests", ())
        }
        if expected_manifest not in configured_manifests:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_RISK_MANIFEST_MISMATCH")
        limits = tuple(int(profile.get(key, 0)) for key in (
            "max_gross_premium_outlay_krw", "max_loss_krw",
            "max_concurrent_groups", "operational_reference_limit_krw",
        ))
        required_audit = {
            "computed_gross_premium_krw", "computed_max_loss_krw",
            "computed_concurrent_exposure_krw", "operational_reference_overage_krw",
            "validation_budget_overage_krw", "run_id", "scenario_id",
            "manifest_sha256", "dataset_sha256",
        }
        if (min(limits) <= 0
                or not required_audit.issubset(set(profile_payload.get("audit_fields_required", ())))
                or limits[3] != operational_limit.max_gross_premium_outlay_krw
                or profile.get("fee_policy") != "ACCOUNT_SEPARATELY; FEES ARE NOT INCLUDED IN THE GROSS PREMIUM CAP"):
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_RISK_LIMITS_OR_AUDIT_INVALID")

        self.max_concurrent_groups = limits[2]
        self.run_id = "UNBOUND"
        self.risk_audit_records: list[dict[str, Any]] = []
        self._group_premium_by_leg: dict[str, dict[str, dict[str, Any]]] = {}
        self.evidence = Track6SyntheticExecutionEvidence(
            manifest_path=str(self.manifest_path),
            manifest_sha256=sha256(self.manifest_path.read_bytes()).hexdigest(),
            dataset_sha256=digest,
            dataset_rows=int(m["rows"]),
            config_sha256=sha256(Path(config_path).read_bytes()).hexdigest(),
            risk_profile_path=str(self.risk_profile_path),
            risk_profile_sha256=sha256(self.risk_profile_path.read_bytes()).hexdigest(),
            scenario_id=str(m.get("scenario_id") or ",".join(m.get("scenario_ids", ())) or self.dataset.name),
            configured_capital_krw=config.configured_capital_krw,
            max_premium_krw=limits[0],
            max_loss_krw=limits[1],
            max_concurrent_positions=limits[2],
            operational_reference_limit_krw=limits[3],
            max_quote_age_seconds=config.max_quote_age_seconds,
        )

    def bind_run_id(self, run_id: str) -> None:
        if not run_id or not str(run_id).strip():
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_RUN_ID_REQUIRED")
        if self.run_id != "UNBOUND" and self.run_id != str(run_id):
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_RUN_ID_ALREADY_BOUND")
        self.run_id = str(run_id)

    def apply_to_strategy(self, strategy: Any, *, synthetic_sources: Any) -> None:
        if getattr(strategy, "strategy_id", None) != STRATEGY_ID:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_STRATEGY_MISMATCH")
        if not str(getattr(synthetic_sources, "source_name", "")).startswith("SYNTHETIC:"):
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_SOURCE_REQUIRED")
        # Instance-local flags only. Constructor defaults and production config stay unchanged.
        strategy.runtime_config_verified = True
        strategy.risk_limits_available = True

    def validate_group(self, plan: Any, prepared: list[tuple]) -> None:
        if getattr(plan, "strategy_id", None) != STRATEGY_ID:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_PLAN_SCOPE_INVALID")
        purpose = str(getattr(plan, "purpose", "") or "")
        exit_purposes = {
            "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_PUT",
            "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_CALL",
            "DAILY_TAIL_INSURANCE_FORCE_CLOSE",
        }
        if purpose in exit_purposes:
            if len(prepared) not in {1, 2}:
                raise ValueError("TRACK6_SYNTHETIC_EXECUTION_EXIT_LEGS_REQUIRED")
            for leg, identity, _client_id, _command, _canonical, bid, ask in prepared:
                instrument_id = str(getattr(identity, "instrument_id", ""))
                if (not instrument_id.startswith(SYNTHETIC_ID_PREFIX)
                        or str(getattr(identity, "identity_source", "")) != "OPTION_MASTER"
                        or str(getattr(leg, "side", "")).upper() != "SELL"
                        or int(getattr(leg, "quantity", 0) or 0) <= 0
                        or str(getattr(identity, "option_type", "")).upper() not in {"PUT", "CALL"}
                        or Decimal(str(getattr(identity, "contract_multiplier", "0"))) <= 0
                        or Decimal(str(bid)) <= 0 or Decimal(str(ask)) < Decimal(str(bid))):
                    raise ValueError("TRACK6_SYNTHETIC_EXECUTION_EXIT_LEG_INVALID")
            return
        if purpose != "DAILY_TAIL_INSURANCE_ENTRY":
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_PLAN_SCOPE_INVALID")
        if len(prepared) not in {1, 2}:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_ONE_OR_TWO_ENTRY_LEGS_REQUIRED")
        group_id = str(getattr(plan, "group_id", "") or "")
        if not group_id:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_GROUP_ID_REQUIRED")
        if (group_id not in self._group_premium_by_leg
                and len(self._group_premium_by_leg) >= self.max_concurrent_groups):
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_CONCURRENT_GROUP_LIMIT_EXCEEDED")
        existing = self._group_premium_by_leg.get(group_id, {})
        updates = {key: dict(value) for key, value in existing.items()}
        seen: set[str] = set()
        for leg, identity, client_id, command, _canonical, bid, ask in prepared:
            leg_id = str(getattr(leg, "leg_id", "")).lower()
            option_type = str(getattr(identity, "option_type", "")).upper()
            instrument_id = str(getattr(identity, "instrument_id", ""))
            checks = {
                "leg_id": leg_id in {"put", "call"} and leg_id not in seen,
                "option_type": option_type == leg_id.upper(),
                "side": str(getattr(leg, "side", "")).upper() == "BUY",
                "quantity": int(getattr(leg, "quantity", 0)) == 1,
                "synthetic_id": instrument_id.startswith(SYNTHETIC_ID_PREFIX),
                "identity_source": str(getattr(identity, "identity_source", "")) == "OPTION_MASTER",
            }
            if not all(checks.values()):
                raise ValueError("TRACK6_SYNTHETIC_EXECUTION_LEG_CONTRACT_INVALID:" + json.dumps({
                    "checks": checks, "leg_id": leg_id, "option_type": option_type,
                    "instrument_id": instrument_id,
                    "identity_source": str(getattr(identity, "identity_source", "")),
                    "side": str(getattr(leg, "side", "")),
                    "quantity": int(getattr(leg, "quantity", 0)),
                }, sort_keys=True))
            seen.add(leg_id)
            price = Decimal(str(getattr(leg, "requested_price", None) or ask))
            multiplier = Decimal(str(getattr(identity, "contract_multiplier", "0")))
            if price <= 0 or multiplier <= 0 or bid <= 0 or ask < bid:
                raise ValueError("TRACK6_SYNTHETIC_EXECUTION_QUOTE_INVALID")
            premium = price * Decimal(str(leg.quantity)) * multiplier
            prior = updates.get(leg_id)
            if prior is not None:
                if (prior.get("client_order_id") != str(client_id)
                        or prior.get("instrument_id") != instrument_id
                        or Decimal(str(prior.get("premium_krw", "0"))) != premium):
                    raise ValueError("TRACK6_SYNTHETIC_EXECUTION_DUPLICATE_LEG_INTENT_MISMATCH")
            else:
                updates[leg_id] = {
                    "client_order_id": str(client_id),
                    "instrument_id": instrument_id,
                    "premium_krw": str(premium),
                }
        total_premium = sum((Decimal(str(item["premium_krw"])) for item in updates.values()), Decimal("0"))
        if len(updates) > 2:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_PUT_CALL_PAIR_REQUIRED")
        operational_overage = max(
            Decimal("0"), total_premium - Decimal(self.evidence.operational_reference_limit_krw),
        )
        validation_overage = max(
            Decimal("0"), total_premium - Decimal(self.evidence.max_premium_krw),
        )
        self.risk_audit_records.append({
            "group_id": group_id,
            "group_leg_count": len(updates),
            "group_pair_complete": set(updates) == {"put", "call"},
            "group_leg_premiums_krw": {key: value["premium_krw"] for key, value in updates.items()},
            "computed_gross_premium_krw": str(total_premium),
            "computed_max_loss_krw": str(total_premium),
            "computed_concurrent_exposure_krw": str(total_premium),
            "operational_reference_overage_krw": str(operational_overage),
            "validation_budget_overage_krw": str(validation_overage),
            "run_id": self.run_id,
            "scenario_id": self.evidence.scenario_id,
            "manifest_sha256": self.evidence.manifest_sha256,
            "dataset_sha256": self.evidence.dataset_sha256,
        })
        if total_premium > Decimal(self.evidence.max_premium_krw):
            raise ValueError(
                f"TRACK6_SYNTHETIC_EXECUTION_PREMIUM_LIMIT_EXCEEDED:"
                f"required_krw={total_premium}:limit_krw={self.evidence.max_premium_krw}"
            )
        if total_premium > Decimal(self.evidence.max_loss_krw):
            raise ValueError(
                f"TRACK6_SYNTHETIC_EXECUTION_MAX_LOSS_EXCEEDED:"
                f"required_krw={total_premium}:limit_krw={self.evidence.max_loss_krw}"
            )
        if self.evidence.max_concurrent_positions < 1:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_CONCURRENT_POSITION_LIMIT_EXCEEDED")
        self._group_premium_by_leg[group_id] = updates

    def sync_group_reservation(self, group_id: str, leg_premiums: dict[str, dict[str, Any]]) -> None:
        group = str(group_id or "")
        if not group:
            raise ValueError("TRACK6_SYNTHETIC_GROUP_RESERVATION_ID_REQUIRED")
        if group not in self._group_premium_by_leg and len(self._group_premium_by_leg) >= self.max_concurrent_groups:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_CONCURRENT_GROUP_LIMIT_EXCEEDED")
        normalized: dict[str, dict[str, Any]] = {}
        for leg, item in leg_premiums.items():
            leg_id = str(leg).lower()
            premium = Decimal(str(item.get("premium_krw", "0")))
            instrument_id = str(item.get("instrument_id", ""))
            client_order_id = str(item.get("client_order_id", ""))
            if (leg_id not in {"put", "call"} or premium <= 0
                    or not instrument_id.startswith(SYNTHETIC_ID_PREFIX) or not client_order_id):
                raise ValueError("TRACK6_SYNTHETIC_RESTORED_GROUP_EVIDENCE_INVALID")
            normalized[leg_id] = {
                "client_order_id": client_order_id,
                "instrument_id": instrument_id,
                "premium_krw": str(premium),
            }
        total = sum((Decimal(item["premium_krw"]) for item in normalized.values()), Decimal("0"))
        if total > Decimal(self.evidence.max_premium_krw) or total > Decimal(self.evidence.max_loss_krw):
            raise ValueError("TRACK6_SYNTHETIC_RESTORED_GROUP_BUDGET_EXCEEDED")
        if normalized:
            self._group_premium_by_leg[group] = normalized

    def release_group(self, group_id: str) -> None:
        self._group_premium_by_leg.pop(str(group_id), None)



class Track6SyntheticFreshnessProvider:
    """Produce validation-only FRESH verdicts from manifest-bound synthetic quotes."""

    def __init__(self, *, option_master: Any, market: Any, max_age_seconds: int, synthetic_sources: Any) -> None:
        self.option_master = option_master
        self.market = market
        self.synthetic_sources = synthetic_sources
        self.max_age = timedelta(seconds=max_age_seconds)

    def __call__(self, plan: Any, leg: Any, identity: Any, command: Any) -> FreshnessVerdict:
        instrument_id = str(getattr(command, "instrument_id", "") or "")
        symbol = str(getattr(command, "broker_symbol", "") or "")
        policy = "Q25-S6-SYNTHETIC-FRESHNESS-v1"
        def verdict(status: FreshnessStatus, reason: str, observed: datetime | None = None, digest: str | None = None):
            return FreshnessVerdict(status=status, reason=reason, policy_version=policy,
                source="SYNTHETIC:DERIVED_SCENARIO", tr_id="Q25_A2_1_S6_MANIFEST",
                environment="SYNTHETIC_VALIDATION_ONLY", instrument_id=instrument_id,
                symbol=symbol, source_instant=observed, received_at=observed, evidence_sha256=digest)
        if getattr(plan, "strategy_id", None) != STRATEGY_ID or not instrument_id.startswith(SYNTHETIC_ID_PREFIX):
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "SYNTHETIC_STRATEGY_OR_IDENTITY_REQUIRED")
        master = self.option_master.get_contract_identity(instrument_id)
        if master is None or str(getattr(master, "shrn_iscd", "")) != instrument_id:
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "SYNTHETIC_OPTION_MASTER_IDENTITY_MISMATCH")
        if (str(getattr(master, "option_type", "")).upper() != str(getattr(identity, "option_type", "")).upper()
                or str(getattr(master, "strike", "")) != str(getattr(identity, "strike", ""))
                or str(getattr(master, "expiry", "")).replace("-", "")[:8] != str(getattr(identity, "expiry", "")).replace("-", "")[:8]
                or str(getattr(master, "contract_multiplier", "")) != str(getattr(identity, "contract_multiplier", ""))):
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "SYNTHETIC_OPTION_MASTER_CONTRACT_MISMATCH")
        quote = getattr(self.market, "option_quotes_by_instrument_id", {}).get(instrument_id)
        if not isinstance(quote, dict) or quote.get("source") != "SYNTHETIC:DERIVED_SCENARIO":
            return verdict(FreshnessStatus.UNKNOWN, "SYNTHETIC_IDENTITY_BOUND_QUOTE_MISSING")
        if (str(quote.get("instrument_id", "")) != instrument_id
                or str(quote.get("option_type", "")).upper() != str(identity.option_type).upper()
                or Decimal(str(quote.get("strike", "0"))) != Decimal(str(identity.strike))
                or str(quote.get("expiry", "")).replace("-", "")[:8] != str(identity.expiry).replace("-", "")[:8]):
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "SYNTHETIC_QUOTE_CONTRACT_IDENTITY_MISMATCH")
        if not isinstance(quote, dict):
            return verdict(FreshnessStatus.UNKNOWN, "SYNTHETIC_QUOTE_MISSING")
        try:
            bid, ask, last = (Decimal(str(quote[k])) for k in ("bid", "ask", "last"))
            observed = datetime.fromisoformat(str(quote["timestamp"]))
            multiplier = Decimal(str(quote["contract_multiplier"]))
        except Exception:
            return verdict(FreshnessStatus.UNKNOWN, "SYNTHETIC_QUOTE_FIELDS_INVALID")
        if (not observed.tzinfo or bid <= 0 or ask < bid or last <= 0
                or multiplier != Decimal(str(identity.contract_multiplier))):
            return verdict(FreshnessStatus.UNKNOWN, "SYNTHETIC_QUOTE_INTEGRITY_INVALID")
        # Compare quote age against the current synthetic replay event time, never wall clock.
        current_tick = getattr(self.synthetic_sources, "_tick", None)
        if current_tick is None:
            return verdict(FreshnessStatus.UNKNOWN, "SYNTHETIC_REPLAY_EVENT_TIME_MISSING")
        try:
            replay_now = datetime.fromisoformat(str(current_tick.timestamp))
        except (TypeError, ValueError):
            return verdict(FreshnessStatus.UNKNOWN, "SYNTHETIC_REPLAY_EVENT_TIME_INVALID")
        if replay_now.tzinfo is None or observed.tzinfo is None or observed > replay_now:
            return verdict(FreshnessStatus.UNKNOWN, "SYNTHETIC_QUOTE_TIME_ORDER_INVALID")
        if replay_now - observed > self.max_age:
            return verdict(FreshnessStatus.STALE, "SYNTHETIC_QUOTE_AGE_EXCEEDED", observed)
        digest = sha256(f"{observed.isoformat()}|{instrument_id}|{symbol}|{bid}|{ask}|{last}".encode()).hexdigest()
        return verdict(FreshnessStatus.FRESH, "SYNTHETIC_MANIFEST_BOUND_QUOTE_VALID", observed, digest)