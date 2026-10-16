"""Validated loader for the versioned, editable option-hedge risk settings."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "risk"
    / "option-hedge-risk.v1.json"
)


class OptionHedgeRiskConfigError(ValueError):
    """Raised when option-hedge risk settings are missing or invalid."""


def _decimal(value: Any, field: str, *, allow_zero: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise OptionHedgeRiskConfigError(f"{field}_DECIMAL_REQUIRED")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise OptionHedgeRiskConfigError(f"{field}_DECIMAL_INVALID") from exc
    if not parsed.is_finite() or (parsed < 0 if allow_zero else parsed <= 0):
        raise OptionHedgeRiskConfigError(f"{field}_DECIMAL_OUT_OF_RANGE")
    return parsed


def _integer(value: Any, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OptionHedgeRiskConfigError(f"{field}_INTEGER_REQUIRED")
    if (value < 0 if allow_zero else value <= 0):
        raise OptionHedgeRiskConfigError(f"{field}_INTEGER_OUT_OF_RANGE")
    return value


@dataclass(frozen=True)
class StrategyOptionRiskLimit:
    enabled: bool
    max_gross_premium_outlay_krw: int
    max_loss_krw: int
    max_concurrent_positions: int


@dataclass(frozen=True)
class OptionHedgeRiskConfig:
    schema_version: str
    currency: str
    activation_mode: str
    configured_capital_krw: int
    max_gross_premium_outlay_krw: int
    max_total_loss_krw: int
    max_margin_utilization_ratio: Decimal
    max_concurrent_risk_budget_krw: int
    strategy_defaults: StrategyOptionRiskLimit
    strategies: Mapping[str, StrategyOptionRiskLimit]
    max_bid_ask_spread_ratio: Decimal
    max_quote_age_seconds: int
    estimated_slippage_ticks_per_leg: int
    require_authoritative_option_master: bool
    require_exact_expiry_yyyymmdd: bool
    require_fresh_authoritative_quote: bool
    require_contract_multiplier_match: bool
    fail_closed_on_missing_identity_quote_or_risk_calculation: bool
    allow_synthetic_quotes: bool
    allow_live_orders: bool


def _limit(raw: Mapping[str, Any], field: str, *, default_enabled: bool = False) -> StrategyOptionRiskLimit:
    enabled = raw.get("enabled", default_enabled)
    if not isinstance(enabled, bool):
        raise OptionHedgeRiskConfigError(f"{field}_ENABLED_BOOL_REQUIRED")
    return StrategyOptionRiskLimit(
        enabled=enabled,
        max_gross_premium_outlay_krw=_integer(
            raw.get("max_gross_premium_outlay_krw"), f"{field}_MAX_PREMIUM", allow_zero=True
        ),
        max_loss_krw=_integer(raw.get("max_loss_krw"), f"{field}_MAX_LOSS", allow_zero=True),
        max_concurrent_positions=_integer(
            raw.get("max_concurrent_positions"), f"{field}_MAX_CONCURRENT", allow_zero=True
        ),
    )


def load_option_hedge_risk_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
) -> OptionHedgeRiskConfig:
    """Load settings strictly; missing or invalid config never falls back silently."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OptionHedgeRiskConfigError("OPTION_HEDGE_RISK_CONFIG_UNAVAILABLE_OR_INVALID") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0.0":
        raise OptionHedgeRiskConfigError("OPTION_HEDGE_RISK_CONFIG_VERSION_UNSUPPORTED")
    if raw.get("currency") != "KRW":
        raise OptionHedgeRiskConfigError("OPTION_HEDGE_RISK_CONFIG_CURRENCY_UNSUPPORTED")
    mode = raw.get("activation_mode")
    if mode not in {"DISABLED_UNTIL_RUNTIME_INTEGRATION", "ENFORCED"}:
        raise OptionHedgeRiskConfigError("OPTION_HEDGE_RISK_CONFIG_ACTIVATION_MODE_INVALID")

    account = raw.get("account")
    defaults = raw.get("strategy_defaults")
    strategy_raw = raw.get("strategies")
    constraints = raw.get("execution_constraints")
    if not all(isinstance(section, dict) for section in (account, defaults, strategy_raw, constraints)):
        raise OptionHedgeRiskConfigError("OPTION_HEDGE_RISK_CONFIG_SECTIONS_REQUIRED")

    capital = _integer(account.get("configured_capital_krw"), "ACCOUNT_CAPITAL")
    premium = _integer(account.get("max_gross_premium_outlay_krw"), "ACCOUNT_MAX_PREMIUM")
    max_loss = _integer(account.get("max_total_loss_krw"), "ACCOUNT_MAX_LOSS")
    risk_budget = _integer(account.get("max_concurrent_risk_budget_krw"), "ACCOUNT_RISK_BUDGET")
    margin_ratio = _decimal(account.get("max_margin_utilization_ratio"), "ACCOUNT_MARGIN_UTILIZATION")
    spread_ratio = _decimal(
        constraints.get("max_bid_ask_spread_ratio"), "MAX_BID_ASK_SPREAD", allow_zero=True
    )
    if max(margin_ratio, spread_ratio) > 1:
        raise OptionHedgeRiskConfigError("OPTION_HEDGE_RISK_RATIO_MUST_NOT_EXCEED_ONE")
    if max(premium, max_loss, risk_budget) > capital:
        raise OptionHedgeRiskConfigError("OPTION_HEDGE_RISK_BUDGET_EXCEEDS_CAPITAL")

    default_limit = _limit(defaults, "STRATEGY_DEFAULTS", default_enabled=True)
    strategies = {
        str(key): _limit(value, f"STRATEGY_{str(key).upper()}")
        for key, value in strategy_raw.items()
        if isinstance(value, dict)
    }
    if not strategies or len(strategies) != len(strategy_raw):
        raise OptionHedgeRiskConfigError("OPTION_HEDGE_STRATEGY_LIMITS_INVALID")

    for field in (
        "require_authoritative_option_master",
        "require_exact_expiry_yyyymmdd",
        "require_fresh_authoritative_quote",
        "require_contract_multiplier_match",
        "fail_closed_on_missing_identity_quote_or_risk_calculation",
        "allow_synthetic_quotes",
        "allow_live_orders",
    ):
        if not isinstance(constraints.get(field), bool):
            raise OptionHedgeRiskConfigError(f"{field.upper()}_BOOL_REQUIRED")
    if constraints["allow_synthetic_quotes"] or constraints["allow_live_orders"]:
        raise OptionHedgeRiskConfigError("SYNTHETIC_QUOTES_AND_LIVE_ORDERS_MUST_REMAIN_DISABLED")
    for field in (
        "require_authoritative_option_master",
        "require_exact_expiry_yyyymmdd",
        "require_fresh_authoritative_quote",
        "require_contract_multiplier_match",
    ):
        if constraints[field] is not True:
            raise OptionHedgeRiskConfigError(f"{field.upper()}_MUST_REMAIN_ENABLED")
    if constraints["fail_closed_on_missing_identity_quote_or_risk_calculation"] is not True:
        raise OptionHedgeRiskConfigError("FAIL_CLOSED_MUST_REMAIN_ENABLED")

    return OptionHedgeRiskConfig(
        schema_version=raw["schema_version"],
        currency=raw["currency"],
        activation_mode=mode,
        configured_capital_krw=capital,
        max_gross_premium_outlay_krw=premium,
        max_total_loss_krw=max_loss,
        max_margin_utilization_ratio=margin_ratio,
        max_concurrent_risk_budget_krw=risk_budget,
        strategy_defaults=default_limit,
        strategies=strategies,
        max_bid_ask_spread_ratio=spread_ratio,
        max_quote_age_seconds=_integer(constraints.get("max_quote_age_seconds"), "MAX_QUOTE_AGE"),
        estimated_slippage_ticks_per_leg=_integer(
            constraints.get("estimated_slippage_ticks_per_leg"), "SLIPPAGE_TICKS", allow_zero=True
        ),
        require_authoritative_option_master=True,
        require_exact_expiry_yyyymmdd=True,
        require_fresh_authoritative_quote=True,
        require_contract_multiplier_match=True,
        fail_closed_on_missing_identity_quote_or_risk_calculation=True,
        allow_synthetic_quotes=False,
        allow_live_orders=False,
    )
