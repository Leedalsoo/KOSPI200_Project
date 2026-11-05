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


@dataclass(frozen=True)
class Track6SyntheticExecutionEvidence:
    manifest_path: str
    manifest_sha256: str
    dataset_sha256: str
    dataset_rows: int
    config_sha256: str
    configured_capital_krw: int
    max_premium_krw: int
    max_loss_krw: int
    max_concurrent_positions: int
    max_quote_age_seconds: int


class Track6SyntheticExecutionGate:
    """Fail-closed budget and provenance gate for one synthetic S6 entry group."""

    def __init__(self, *, dataset: str | Path, manifest_path: str | Path,
                 config_path: str | Path = DEFAULT_CONFIG_PATH) -> None:
        self.dataset = Path(dataset).resolve()
        self.manifest_path = Path(manifest_path).resolve()
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
        limit = config.strategies.get(STRATEGY_ID)
        if limit is None or not limit.enabled or min(
            limit.max_gross_premium_outlay_krw, limit.max_loss_krw,
            limit.max_concurrent_positions,
        ) <= 0:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_RISK_LIMITS_INVALID")
        self.evidence = Track6SyntheticExecutionEvidence(
            manifest_path=str(self.manifest_path),
            manifest_sha256=sha256(self.manifest_path.read_bytes()).hexdigest(),
            dataset_sha256=digest,
            dataset_rows=int(m["rows"]),
            config_sha256=sha256(Path(config_path).read_bytes()).hexdigest(),
            configured_capital_krw=config.configured_capital_krw,
            max_premium_krw=limit.max_gross_premium_outlay_krw,
            max_loss_krw=limit.max_loss_krw,
            max_concurrent_positions=limit.max_concurrent_positions,
            max_quote_age_seconds=config.max_quote_age_seconds,
        )

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
        if len(prepared) != 2:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_TWO_LEGS_REQUIRED")
        seen: set[str] = set()
        total_premium = Decimal("0")
        for leg, identity, _client_id, command, _canonical, bid, ask in prepared:
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
            total_premium += price * Decimal(str(leg.quantity)) * multiplier
        if seen != {"put", "call"}:
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_PUT_CALL_PAIR_REQUIRED")
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
