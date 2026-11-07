"""Validation-only Strategy 8 Runtime readiness, risk and freshness boundary.

This adapter is bound to one DERIVED_SCENARIO manifest and one frozen validation
risk profile. It never mutates operational RiskConfig or grants KIS/Live access.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict

STRATEGY_ID = "track8_macro_regime_monthly_strangle"
SYNTHETIC_ID_PREFIX = "SYNTHETIC_CONTRACT:"


@dataclass(frozen=True)
class S8ValidationEvidence:
    manifest_path: str
    manifest_sha256: str
    dataset_sha256: str
    risk_profile_path: str
    risk_profile_sha256: str
    scenario_id: str
    max_gross_premium_krw: int
    max_loss_krw: int
    max_concurrent_groups: int
    operational_reference_limit_krw: int


class S8ValidationOnlyRuntimeAdapter:
    """Manifest-bound S8 readiness and per-group synthetic premium risk gate."""

    def __init__(self, *, dataset: str | Path, manifest_path: str | Path,
                 risk_profile_path: str | Path) -> None:
        self.dataset = Path(dataset).resolve()
        self.manifest_path = Path(manifest_path).resolve()
        self.risk_profile_path = Path(risk_profile_path).resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        profile_payload = json.loads(self.risk_profile_path.read_text(encoding="utf-8"))
        m = self.manifest
        policy = m.get("strategy_policy_inputs")
        if not isinstance(policy, dict) or policy.get("strategy8_min_entry_dte_trading_days") != 10:
            raise ValueError("S8_VALIDATION_DTE_POLICY_MUST_MATCH_NO1169")
        if (m.get("schema_version") != "q25-a2-1-s6-syn-evt-manifest-v1"
                or m.get("source_type") != "DERIVED_SCENARIO"
                or m.get("provenance") != "DERIVED_SCENARIO"
                or m.get("synthetic") is not True
                or m.get("validation_only") is not True
                or m.get("runtime_eligible") is not False
                or m.get("production_runtime_eligible") is not False
                or m.get("identity_source_status") != "BLOCKED_IDENTITY_OWNER_UNRESOLVED"
                or m.get("expiry_is_authoritative") is not False
                or m.get("strategy_id") != "strategy8_monthly"):
            raise ValueError("S8_VALIDATION_MANIFEST_INVALID")
        output = (Path.cwd() / str(m.get("output_path", ""))).resolve()
        if output.parent != self.dataset or not output.is_file():
            raise ValueError("S8_VALIDATION_DATASET_PATH_MISMATCH")
        digest = sha256(output.read_bytes()).hexdigest()
        if digest != str(m.get("output_sha256", "")).lower() or digest != str(m.get("dataset_sha256", "")).lower():
            raise ValueError("S8_VALIDATION_DATASET_HASH_MISMATCH")
        if (profile_payload.get("validation_only") is not True
                or profile_payload.get("runtime_eligible") is not False
                or profile_payload.get("allow_kis_api") is not False
                or profile_payload.get("allow_live_orders") is not False
                or profile_payload.get("allow_real_account") is not False
                or profile_payload.get("operational_config_mutated") is not False
                or profile_payload.get("risk_checks_enabled") is not True
                or profile_payload.get("enforcement_mode") != "VALIDATION_ONLY_ALLOW_WITH_OVERAGE_AUDIT"):
            raise ValueError("S8_VALIDATION_RISK_PROFILE_INVALID")
        profile = profile_payload.get("profiles", {}).get("track8_monthly_strangle")
        if not isinstance(profile, dict):
            raise ValueError("S8_VALIDATION_RISK_PROFILE_MISSING")
        expected_manifest = str(self.manifest_path.relative_to(Path.cwd())).replace("\\", "/")
        configured_manifest = str(profile.get("dataset_manifest", "")).replace("\\", "/")
        if configured_manifest != expected_manifest:
            raise ValueError("S8_VALIDATION_RISK_MANIFEST_MISMATCH")
        limits = tuple(int(profile.get(key, 0)) for key in (
            "max_gross_premium_outlay_krw", "max_loss_krw", "max_concurrent_groups",
            "operational_reference_limit_krw",
        ))
        required_audit = set(profile_payload.get("audit_fields_required", ()))
        expected_audit = {
            "computed_gross_premium_krw", "computed_max_loss_krw",
            "computed_concurrent_exposure_krw", "operational_reference_overage_krw",
            "validation_budget_overage_krw", "run_id", "scenario_id",
            "manifest_sha256", "dataset_sha256",
        }
        if min(limits) <= 0 or not expected_audit.issubset(required_audit):
            raise ValueError("S8_VALIDATION_RISK_LIMITS_OR_AUDIT_FIELDS_INVALID")
        self.profile = profile
        self._reserved: dict[str, dict[str, Decimal]] = {}
        self.evidence = S8ValidationEvidence(
            manifest_path=str(self.manifest_path),
            manifest_sha256=sha256(self.manifest_path.read_bytes()).hexdigest(),
            dataset_sha256=digest,
            risk_profile_path=str(self.risk_profile_path),
            risk_profile_sha256=sha256(self.risk_profile_path.read_bytes()).hexdigest(),
            scenario_id=str(m["scenario_id"]),
            max_gross_premium_krw=limits[0],
            max_loss_krw=limits[1],
            max_concurrent_groups=limits[2],
            operational_reference_limit_krw=limits[3],
        )
        self.run_id = "UNBOUND"
        self.risk_audit_records: list[dict[str, Any]] = []

    def bind_run_id(self, run_id: str) -> None:
        if not run_id or not str(run_id).strip():
            raise ValueError("S8_VALIDATION_RUN_ID_REQUIRED")
        if self.run_id != "UNBOUND" and self.run_id != str(run_id):
            raise ValueError("S8_VALIDATION_RUN_ID_ALREADY_BOUND")
        self.run_id = str(run_id)

    def apply_to_strategy(self, strategy: Any, *, synthetic_sources: Any) -> None:
        if getattr(strategy, "strategy_id", None) != STRATEGY_ID:
            raise ValueError("S8_VALIDATION_STRATEGY_MISMATCH")
        if not str(getattr(synthetic_sources, "source_name", "")).startswith("SYNTHETIC:"):
            raise ValueError("S8_VALIDATION_SYNTHETIC_SOURCE_REQUIRED")
        if getattr(strategy, "runtime_config_verified", None) is not False:
            raise ValueError("S8_OPERATIONAL_READINESS_DEFAULT_CHANGED")
        if getattr(strategy, "risk_limits_available", None) is not False:
            raise ValueError("S8_OPERATIONAL_RISK_DEFAULT_CHANGED")
        # Instance-local flags only. Strategy constructor defaults remain fail-closed.
        strategy.runtime_config_verified = True
        strategy.risk_limits_available = True
        # Apply the manifest-declared No.1169 threshold to this strategy instance only;
        # never change the registry/production configurable default.
        strategy.DTE_ENTRY = Decimal(str(self.manifest["strategy_policy_inputs"]["strategy8_min_entry_dte_trading_days"]))

    def release_all_groups(self) -> None:
        """Release validation-only reservations after the strategy is confirmed flat."""
        self._reserved.clear()

    def pair_quotes_ready(self, selection: Any, *, market: Any, tick: Any) -> bool:
        if selection is None or tick is None:
            return False
        expiry = str(getattr(selection, "expiry", "")).replace("-", "")[:8]
        current_timestamp = str(getattr(tick, "timestamp", ""))
        quotes = getattr(market, "option_quotes", {})
        for identity in (getattr(selection, "call", None), getattr(selection, "put", None)):
            if identity is None:
                return False
            key = next((key for key in quotes if isinstance(key, tuple) and len(key) == 3
                and str(key[0]).upper() == str(getattr(identity, "option_type", "")).upper()
                and Decimal(str(key[1])) == Decimal(str(getattr(identity, "strike", "0")))
                and str(key[2]).replace("-", "")[:8] == expiry), None)
            quote = quotes.get(key) if key is not None else None
            if not isinstance(quote, dict) or str(quote.get("timestamp", "")) != current_timestamp:
                return False
            try:
                bid, ask = Decimal(str(quote["bid"])), Decimal(str(quote["ask"]))
                multiplier = Decimal(str(quote["contract_multiplier"]))
            except Exception:
                return False
            if bid <= 0 or ask <= bid or multiplier != Decimal(str(identity.contract_multiplier)):
                return False
        return True

    def option_mark_prices(self, selection: Any, *, market: Any, tick: Any) -> dict[str, Decimal] | None:
        """Return exact-instant last-price marks from this manifest-bound synthetic scenario."""
        if selection is None or tick is None:
            return None
        quotes = getattr(market, "option_quotes_by_instrument_id", {})
        if not isinstance(quotes, dict):
            return None
        current_timestamp = str(getattr(tick, "timestamp", ""))
        expiry = str(getattr(selection, "expiry", "")).replace("-", "")[:8]
        result: dict[str, Decimal] = {}
        for leg_id, identity in (("call", getattr(selection, "call", None)),
                                 ("put", getattr(selection, "put", None))):
            if identity is None:
                return None
            instrument_id = str(getattr(identity, "shrn_iscd", "") or
                                getattr(identity, "instrument_id", ""))
            identity_expiry = str(getattr(identity, "expiry", "")).replace("-", "")[:8]
            identity_type = str(getattr(identity, "option_type", "")).upper()
            try:
                identity_strike = Decimal(str(getattr(identity, "strike", "0")))
                id_parts = instrument_id.split(":")
                id_strike = Decimal(id_parts[-1]) if len(id_parts) >= 6 else Decimal("0")
            except Exception:
                return None
            if (
                identity_expiry != expiry
                or len(id_parts) < 6
                or id_parts[-3] != identity_expiry
                or id_parts[-2].upper() != identity_type
                or id_strike != identity_strike
            ):
                return None
            quote = quotes.get(instrument_id)
            if not isinstance(quote, dict):
                return None
            try:
                observed = str(quote["timestamp"])
                option_type = str(quote["option_type"]).upper()
                strike = Decimal(str(quote["strike"]))
                quote_expiry = str(quote["expiry"]).replace("-", "")[:8]
                multiplier = Decimal(str(quote["contract_multiplier"]))
                bid = Decimal(str(quote["bid"]))
                ask = Decimal(str(quote["ask"]))
                last = Decimal(str(quote["last"]))
            except (KeyError, TypeError, ValueError):
                return None
            if (
                quote.get("source") != "SYNTHETIC:DERIVED_SCENARIO"
                or str(quote.get("instrument_id", "")) != instrument_id
                or observed != current_timestamp
                or option_type != identity_type
                or strike != identity_strike
                or quote_expiry != identity_expiry
                or multiplier != Decimal(str(getattr(identity, "contract_multiplier", "0")))
                or bid <= 0 or ask <= bid or last <= 0
            ):
                return None
            result[leg_id] = last
        return result if set(result) == {"call", "put"} else None

    def validate_group(self, plan: Any, prepared: list[tuple]) -> None:
        purpose = str(getattr(plan, "purpose", "") or "")
        if getattr(plan, "strategy_id", None) != STRATEGY_ID:
            raise ValueError("S8_VALIDATION_ORDER_SCOPE_INVALID")

        expected_expiry = str(
            self.manifest.get("date_end")
            or self.manifest.get("scenario_expectations", {}).get("expiry")
            or ""
        ).replace("-", "")[:8]
        expected_multiplier_value = (
            self.manifest.get("scenario_reference_only", {}).get("contract_multiplier")
            or self.manifest.get("contract_multiplier")
        )
        expected_multiplier = (
            Decimal(str(expected_multiplier_value)) if expected_multiplier_value is not None else None
        )

        def valid_close_identity(close_leg: Any, identity: Any, expected_type: str) -> bool:
            instrument_id = str(getattr(identity, "instrument_id", ""))
            identity_expiry = str(getattr(identity, "expiry", "")).replace("-", "")[:8]
            identity_type = str(getattr(identity, "option_type", "")).upper()
            try:
                identity_strike = Decimal(str(getattr(identity, "strike", "0")))
                leg_strike = Decimal(str(getattr(close_leg, "strike", "0")))
                multiplier = Decimal(str(getattr(identity, "contract_multiplier", "0")))
                id_strike = Decimal(instrument_id.split(":")[-1])
            except Exception:
                return False
            id_parts = instrument_id.split(":")
            return (
                instrument_id.startswith(SYNTHETIC_ID_PREFIX)
                and len(id_parts) >= 6
                and identity_expiry
                and id_parts[-3] == identity_expiry
                and (not expected_expiry or identity_expiry == expected_expiry)
                and id_parts[-2].upper() == expected_type
                and identity_type == expected_type
                and id_strike == identity_strike == leg_strike
                and multiplier > 0
                and (expected_multiplier is None or multiplier == expected_multiplier)
                and int(getattr(close_leg, "quantity", 0)) > 0
                and str(getattr(close_leg, "side", "")).upper() == "SELL"
                and str(getattr(close_leg, "option_type", expected_type)).upper() == expected_type
            )

        if purpose in {"MONTHLY_STRANGLE_CLOSE_CALL", "MONTHLY_STRANGLE_CLOSE_PUT"}:
            expected_option_type = "CALL" if purpose.endswith("_CALL") else "PUT"
            if len(prepared) != 1:
                raise ValueError("S8_VALIDATION_CLOSE_SINGLE_LEG_REQUIRED")
            close_leg, close_identity, _client_id, _command, _canonical, close_bid, close_ask = prepared[0]
            if (
                not valid_close_identity(close_leg, close_identity, expected_option_type)
                or Decimal(str(close_bid)) <= 0
                or Decimal(str(close_ask)) < Decimal(str(close_bid))
            ):
                raise ValueError("S8_VALIDATION_CLOSE_REDUCTION_IDENTITY_INVALID")
            return
        if purpose == "MONTHLY_STRANGLE_CLOSE":
            if len(prepared) != 2:
                raise ValueError("S8_VALIDATION_EXPIRY_CLOSE_PAIR_REQUIRED")
            seen: set[str] = set()
            for close_leg, close_identity, _client_id, _command, _canonical, close_bid, close_ask in prepared:
                option_type = str(getattr(close_identity, "option_type", "")).upper()
                if (
                    option_type not in {"CALL", "PUT"} or option_type in seen
                    or not valid_close_identity(close_leg, close_identity, option_type)
                    or Decimal(str(close_bid)) <= 0
                    or Decimal(str(close_ask)) < Decimal(str(close_bid))
                ):
                    raise ValueError("S8_VALIDATION_EXPIRY_CLOSE_REDUCTION_IDENTITY_INVALID")
                seen.add(option_type)
            if seen != {"CALL", "PUT"}:
                raise ValueError("S8_VALIDATION_EXPIRY_CLOSE_PAIR_REQUIRED")
            return
        if purpose not in {"MONTHLY_STRANGLE_ENTRY_CALL", "MONTHLY_STRANGLE_ENTRY_PUT"}:
            raise ValueError("S8_VALIDATION_ORDER_SCOPE_INVALID")
        if len(prepared) != 1:
            raise ValueError("S8_VALIDATION_SEQUENTIAL_SINGLE_LEG_REQUIRED")
        leg, identity, _client_id, _command, _canonical, bid, ask = prepared[0]
        leg_id = str(getattr(leg, "leg_id", "")).lower()
        option_type = str(getattr(identity, "option_type", "")).upper()
        instrument_id = str(getattr(identity, "instrument_id", ""))
        if (leg_id not in {"call", "put"} or option_type != leg_id.upper()
                or str(getattr(leg, "side", "")).upper() != "BUY"
                or int(getattr(leg, "quantity", 0)) != 1
                or not instrument_id.startswith(SYNTHETIC_ID_PREFIX)
                or str(getattr(identity, "identity_source", "")) != "OPTION_MASTER"):
            raise ValueError("S8_VALIDATION_LEG_IDENTITY_INVALID")
        bid_d, ask_d = Decimal(str(bid)), Decimal(str(ask))
        multiplier = Decimal(str(getattr(identity, "contract_multiplier", "0")))
        if bid_d <= 0 or ask_d < bid_d or multiplier <= 0:
            raise ValueError("S8_VALIDATION_QUOTE_OR_MULTIPLIER_INVALID")
        group_id = str(getattr(plan, "group_id", "") or "")
        if not group_id:
            raise ValueError("S8_VALIDATION_GROUP_ID_REQUIRED")
        if group_id not in self._reserved and len(self._reserved) >= self.evidence.max_concurrent_groups:
            raise ValueError("S8_VALIDATION_CONCURRENT_GROUP_LIMIT_EXCEEDED")
        # Use ask as conservative premium; retries replace the same leg reservation
        # rather than double-counting an attempt.
        amount = ask_d * Decimal(str(leg.quantity)) * multiplier
        reservation = self._reserved.setdefault(group_id, {})
        reservation[leg_id] = max(reservation.get(leg_id, Decimal("0")), amount)
        gross = sum(reservation.values(), Decimal("0"))
        operational_limit = Decimal(self.evidence.operational_reference_limit_krw)
        validation_limit = Decimal(self.evidence.max_gross_premium_krw)
        max_loss_limit = Decimal(self.evidence.max_loss_krw)
        audit = {
            "run_id": self.run_id,
            "scenario_id": self.evidence.scenario_id,
            "manifest_sha256": self.evidence.manifest_sha256,
            "dataset_sha256": self.evidence.dataset_sha256,
            "group_id": group_id,
            "leg_id": leg_id,
            "computed_gross_premium_krw": str(gross),
            "computed_max_loss_krw": str(gross),
            "computed_concurrent_exposure_krw": str(gross),
            "operational_reference_overage_krw": str(max(Decimal("0"), gross - operational_limit)),
            "validation_budget_overage_krw": str(max(Decimal("0"), gross - validation_limit)),
            "status": "ALLOW",
        }
        if gross > validation_limit:
            audit["status"] = "BLOCKED_VALIDATION_PREMIUM_LIMIT"
            self.risk_audit_records.append(audit)
            raise ValueError(f"S8_VALIDATION_PREMIUM_LIMIT_EXCEEDED:{gross}")
        if gross > max_loss_limit:
            audit["status"] = "BLOCKED_VALIDATION_MAX_LOSS_LIMIT"
            self.risk_audit_records.append(audit)
            raise ValueError(f"S8_VALIDATION_MAX_LOSS_LIMIT_EXCEEDED:{gross}")
        self.risk_audit_records.append(audit)

    def freshness_verdict(self, *, plan: Any, identity: Any, command: Any,
                          option_master: Any, market: Any, synthetic_sources: Any) -> FreshnessVerdict:
        instrument_id = str(getattr(command, "instrument_id", "") or "")
        symbol = str(getattr(command, "broker_symbol", "") or "")
        policy = "Q25-S8-SYNTHETIC-FRESHNESS-v1"

        def verdict(status: FreshnessStatus, reason: str, observed=None, digest=None):
            return FreshnessVerdict(
                status=status, reason=reason, policy_version=policy,
                source="SYNTHETIC:DERIVED_SCENARIO", tr_id="Q25_S8_MANIFEST",
                environment="SYNTHETIC_VALIDATION_ONLY", instrument_id=instrument_id,
                symbol=symbol, source_instant=observed, received_at=observed,
                evidence_sha256=digest,
            )

        if getattr(plan, "strategy_id", None) != STRATEGY_ID or not instrument_id.startswith(SYNTHETIC_ID_PREFIX):
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "S8_SYNTHETIC_IDENTITY_REQUIRED")
        master = option_master.get_contract_identity(symbol)
        if (master is None or str(getattr(master, "shrn_iscd", "")) != instrument_id
                or str(getattr(master, "option_type", "")).upper() != str(getattr(identity, "option_type", "")).upper()
                or Decimal(str(getattr(master, "strike", "0"))) != Decimal(str(getattr(identity, "strike", "0")))
                or str(getattr(master, "expiry", "")).replace("-", "")[:8] != str(getattr(identity, "expiry", "")).replace("-", "")[:8]
                or Decimal(str(getattr(master, "contract_multiplier", "0"))) != Decimal(str(getattr(identity, "contract_multiplier", "0")))):
            return verdict(FreshnessStatus.IDENTITY_CONFLICT, "S8_OPTION_MASTER_IDENTITY_MISMATCH")
        quote = next((value for key, value in getattr(market, "option_quotes", {}).items()
            if isinstance(key, tuple) and len(key) == 3
            and str(key[0]).upper() == str(identity.option_type).upper()
            and Decimal(str(key[1])) == Decimal(str(identity.strike))
            and str(key[2]).replace("-", "")[:8] == str(identity.expiry).replace("-", "")[:8]), None)
        if not isinstance(quote, dict):
            return verdict(FreshnessStatus.UNKNOWN, "S8_SYNTHETIC_QUOTE_MISSING")
        try:
            bid, ask, last = (Decimal(str(quote[k])) for k in ("bid", "ask", "last"))
            observed = datetime.fromisoformat(str(quote["timestamp"]))
            replay_now = datetime.fromisoformat(str(synthetic_sources._tick.timestamp))
        except Exception:
            return verdict(FreshnessStatus.UNKNOWN, "S8_SYNTHETIC_QUOTE_FIELDS_INVALID")
        if (not observed.tzinfo or not replay_now.tzinfo or observed != replay_now
                or bid <= 0 or ask <= bid or last <= 0):
            return verdict(FreshnessStatus.STALE, "S8_QUOTE_MUST_MATCH_CURRENT_REPLAY_INSTANT", observed)
        digest = sha256(
            f"{self.evidence.manifest_sha256}|{self.evidence.dataset_sha256}|{observed.isoformat()}|{instrument_id}|{bid}|{ask}|{last}".encode()
        ).hexdigest()
        return verdict(FreshnessStatus.FRESH, "S8_MANIFEST_BOUND_SYNTHETIC_QUOTE", observed, digest)
