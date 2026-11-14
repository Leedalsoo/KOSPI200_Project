from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

DEFAULT_TRACK2_SYNTHETIC_SCENARIO_PROFILE = (
    Path(__file__).resolve().parents[2] / "config" / "validation_only" / "track2" / "synthetic_scenario_profile.v1.json"
)


class Track2SyntheticScenarioProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Track2SyntheticScenarioProfile:
    profile_id: str
    strategy_id: str
    profile_sha256: str
    risk_limits: dict[str, int | float | str]
    u16_quote_policy: dict[str, Any]
    u17_contract_selection: dict[str, Any]
    u18_exit_policy: dict[str, Any]
    u19_recovery_policy: dict[str, Any]
    u20_entry_policy: dict[str, Any]
    u21_quote_policy: dict[str, Any]
    synthetic_cost_models: dict[str, Any]

    @property
    def execution_enabled(self) -> bool:
        return False

    @property
    def order_submission_enabled(self) -> bool:
        return False

    @property
    def live_api_enabled(self) -> bool:
        return False

    @property
    def real_vts_api_enabled(self) -> bool:
        return False


def load_track2_synthetic_scenario_profile(
    path: str | Path = DEFAULT_TRACK2_SYNTHETIC_SCENARIO_PROFILE,
) -> Track2SyntheticScenarioProfile:
    profile_path = Path(path).resolve()
    try:
        raw: Any = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_UNAVAILABLE_OR_INVALID") from exc

    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0.0":
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_SCHEMA_UNSUPPORTED")
    if raw.get("profile_type") != "SYNTHETIC_SCENARIO_ONLY" or raw.get("strategy_id") != "track2_asymmetric_trap":
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_IDENTITY_INVALID")
    if any(raw.get(key) is not False for key in (
        "execution_enabled", "order_submission_enabled", "live_api_enabled", "real_vts_api_enabled",
    )):
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_MUST_NOT_ENABLE_EXECUTION")

    limits = raw.get("risk_limits")
    expected_limit_keys = {
        "account_capital_krw", "account_max_premium_krw", "account_max_loss_krw",
        "max_margin_utilization_ratio", "max_concurrent_risk_budget_krw",
        "strategy_max_premium_krw", "strategy_max_loss_krw", "max_concurrent_groups",
        "group_max_loss_krw", "fee_model_version", "slippage_model_version", "margin_model_version",
    }
    if not isinstance(limits, dict) or set(limits) != expected_limit_keys:
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_RISK_LIMIT_KEYS_INVALID")
    for key in expected_limit_keys - {"fee_model_version", "slippage_model_version", "margin_model_version"}:
        value = limits[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise Track2SyntheticScenarioProfileError(f"TRACK2_SYNTHETIC_PROFILE_RISK_LIMIT_INVALID:{key}")
    if not all(isinstance(limits[key], str) and limits[key].strip() for key in (
        "fee_model_version", "slippage_model_version", "margin_model_version",
    )):
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_COST_MODEL_VERSION_REQUIRED")

    u16 = raw.get("U16_quote_policy")
    u17 = raw.get("U17_contract_selection")
    u18 = raw.get("U18_exit_policy")
    u19 = raw.get("U19_recovery_policy")
    u20 = raw.get("U20_entry_policy")
    u21 = raw.get("U21_quote_policy")
    costs = raw.get("synthetic_cost_models")
    if not all(isinstance(item, dict) for item in (u16, u17, u18, u19, u20, u21, costs)):
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_POLICY_OBJECT_REQUIRED")

    if u16.get("validated") is not True or u16.get("side_to_book_rule") != "BUY_ASK_SELL_BID":
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_U16_INVALID")
    if u17.get("atm_tie_break") != "LOWER_STRIKE_AT_OR_BELOW_UNDERLYING":
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_U17_INVALID")
    if u20.get("sequence") != ["inner_put", "inner_call", "outer_put", "outer_call"]:
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_U20_SEQUENCE_INVALID")
    if u20.get("partial_unknown_or_pending_blocks") is not True:
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_U20_FAIL_CLOSED_REQUIRED")
    if u19.get("mismatch_auto_adjustment") is not False or u19.get("pending_orders_block_resume") is not True:
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_U19_FAIL_CLOSED_REQUIRED")
    if u21.get("approved_for_synthetic_scenarios_only") is not True:
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_U21_SYNTHETIC_APPROVAL_REQUIRED")

    try:
        stop = Decimal(str(u18["stop_loss_ratio"]))
        activation = Decimal(str(u18["trailing_activation_ratio"]))
        pullback = Decimal(str(u18["trailing_pullback_ratio"]))
        max_age = Decimal(str(u21["max_age_seconds"]))
        max_spread = Decimal(str(u21["max_spread"]))
        tick_size = Decimal(str(u21["tick_size"]))
    except (KeyError, TypeError, ValueError):
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_NUMERIC_POLICY_INVALID") from None
    if not (stop < 0 and activation > 0 and Decimal("0") < pullback <= 1):
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_U18_THRESHOLDS_INVALID")
    if not (max_age > 0 and max_spread >= 0 and tick_size > 0):
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_U21_THRESHOLDS_INVALID")
    if u21.get("tick_rounding") != "BUY_CEILING_SELL_FLOOR":
        raise Track2SyntheticScenarioProfileError("TRACK2_SYNTHETIC_PROFILE_U21_ROUNDING_INVALID")

    return Track2SyntheticScenarioProfile(
        profile_id=str(raw.get("profile_id") or ""),
        strategy_id=str(raw["strategy_id"]),
        profile_sha256=sha256(profile_path.read_bytes()).hexdigest(),
        risk_limits=dict(limits), u16_quote_policy=dict(u16),
        u17_contract_selection=dict(u17), u18_exit_policy=dict(u18),
        u19_recovery_policy=dict(u19), u20_entry_policy=dict(u20),
        u21_quote_policy=dict(u21), synthetic_cost_models=dict(costs),
    )
