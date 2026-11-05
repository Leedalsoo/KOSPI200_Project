"""Fail-closed configuration gates for Strategy 6 synthetic signal observation only.

This module validates configured limits but does not admit orders or activate the
operational option-hedge risk configuration. Its evidence may only be applied to
an explicitly synthetic, validation-only Strategy 6 instance whose loop blocks
Decision/Risk/OMS/Execution after signal observation.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from core.risk.option_hedge_risk_config import (
    DEFAULT_CONFIG_PATH,
    load_option_hedge_risk_config,
)


TRACK6_STRATEGY_ID = "track6_daily_tail_insurance"


@dataclass(frozen=True)
class Track6ValidationGateEvidence:
    config_path: str
    config_sha256: str
    config_schema_version: str
    strategy_max_gross_premium_outlay_krw: int
    strategy_max_loss_krw: int
    strategy_max_concurrent_positions: int
    max_quote_age_seconds: int


def load_track6_validation_gate_evidence(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> Track6ValidationGateEvidence:
    """Validate the existing S6 risk limits without enabling operational risk."""
    path = Path(config_path).resolve()
    config = load_option_hedge_risk_config(path)

    # This gate is intentionally limited to the currently disabled operational
    # configuration. An ENFORCED config requires a separate runtime integration.
    if config.activation_mode != "DISABLED_UNTIL_RUNTIME_INTEGRATION":
        raise ValueError("TRACK6_VALIDATION_REQUIRES_OPERATIONAL_RISK_CONFIG_DISABLED")
    if config.allow_live_orders or config.allow_synthetic_quotes:
        raise ValueError("TRACK6_VALIDATION_FORBIDDEN_EXECUTION_CAPABILITY_ENABLED")
    if not config.fail_closed_on_missing_identity_quote_or_risk_calculation:
        raise ValueError("TRACK6_VALIDATION_FAIL_CLOSED_REQUIRED")
    if not all((
        config.require_authoritative_option_master,
        config.require_exact_expiry_yyyymmdd,
        config.require_fresh_authoritative_quote,
        config.require_contract_multiplier_match,
    )):
        raise ValueError("TRACK6_VALIDATION_AUTHORITATIVE_CONSTRAINTS_REQUIRED")

    limit = config.strategies.get(TRACK6_STRATEGY_ID)
    if limit is None or not limit.enabled:
        raise ValueError("TRACK6_VALIDATION_STRATEGY_LIMIT_UNAVAILABLE")
    if min(
        limit.max_gross_premium_outlay_krw,
        limit.max_loss_krw,
        limit.max_concurrent_positions,
    ) <= 0:
        raise ValueError("TRACK6_VALIDATION_STRATEGY_LIMIT_INVALID")
    if limit.max_gross_premium_outlay_krw > config.max_gross_premium_outlay_krw:
        raise ValueError("TRACK6_VALIDATION_PREMIUM_LIMIT_EXCEEDS_ACCOUNT_LIMIT")
    if limit.max_loss_krw > config.max_total_loss_krw:
        raise ValueError("TRACK6_VALIDATION_LOSS_LIMIT_EXCEEDS_ACCOUNT_LIMIT")
    if limit.max_gross_premium_outlay_krw > config.max_concurrent_risk_budget_krw:
        raise ValueError("TRACK6_VALIDATION_PREMIUM_EXCEEDS_CONCURRENT_RISK_BUDGET")

    return Track6ValidationGateEvidence(
        config_path=str(path),
        config_sha256=sha256(path.read_bytes()).hexdigest(),
        config_schema_version=config.schema_version,
        strategy_max_gross_premium_outlay_krw=limit.max_gross_premium_outlay_krw,
        strategy_max_loss_krw=limit.max_loss_krw,
        strategy_max_concurrent_positions=limit.max_concurrent_positions,
        max_quote_age_seconds=config.max_quote_age_seconds,
    )


def apply_track6_validation_gates(
    strategy: object,
    *,
    validation_only_synthetic: bool,
    synthetic_runtime_sources: object | None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> Track6ValidationGateEvidence:
    """Set S6's two preconditions only for synthetic signal-only validation."""
    if not validation_only_synthetic:
        raise ValueError("TRACK6_VALIDATION_ONLY_SYNTHETIC_MODE_REQUIRED")
    source_name = str(getattr(synthetic_runtime_sources, "source_name", ""))
    if not source_name.startswith("SYNTHETIC:"):
        raise ValueError("TRACK6_VALIDATION_SYNTHETIC_SOURCE_REQUIRED")
    if getattr(strategy, "strategy_id", None) != TRACK6_STRATEGY_ID:
        raise ValueError("TRACK6_VALIDATION_STRATEGY_ID_MISMATCH")

    evidence = load_track6_validation_gate_evidence(config_path)
    # These booleans mean config/limit availability for signal observation only.
    # They do not mean quote-based risk admission; the caller must block all
    # Decision/Risk/OMS/Execution stages for this validation mode.
    setattr(strategy, "runtime_config_verified", True)
    setattr(strategy, "risk_limits_available", True)
    return evidence
