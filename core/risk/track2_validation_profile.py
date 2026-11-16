from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

DEFAULT_TRACK2_VALIDATION_PROFILE = (
    Path(__file__).resolve().parents[2]
    / "config" / "validation_only" / "track2" / "risk_profile.v1.json"
)

EXPECTED_TRACK2_RISK_LIMIT_KEYS = frozenset({
    "account_capital_krw",
    "account_max_premium_krw",
    "account_max_loss_krw",
    "max_margin_utilization_ratio",
    "max_concurrent_risk_budget_krw",
    "strategy_max_premium_krw",
    "strategy_max_loss_krw",
    "max_concurrent_groups",
    "group_max_loss_krw",
    "fee_model_version",
    "slippage_model_version",
    "margin_model_version",
})

REQUIRED_TRACK2_POLICY_DEPENDENCIES = frozenset({
    "S2-U16", "S2-U17", "S2-U18", "S2-U19", "S2-U20", "S2-U21",
})


class Track2ValidationProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Track2ValidationProfile:
    profile_id: str
    strategy_id: str
    profile_sha256: str
    risk_limit_keys: tuple[str, ...]
    policy_dependencies: tuple[str, ...]
    execution_enabled: bool
    order_submission_enabled: bool
    live_api_enabled: bool
    real_vts_api_enabled: bool
    numeric_limits_resolved: bool

    def require_execution(self) -> None:
        raise Track2ValidationProfileError(
            "TRACK2_VALIDATION_ONLY_PROFILE_CANNOT_AUTHORIZE_EXECUTION"
        )


def load_track2_validation_profile(
    path: str | Path = DEFAULT_TRACK2_VALIDATION_PROFILE,
) -> Track2ValidationProfile:
    profile_path = Path(path).resolve()
    try:
        payload = profile_path.read_bytes()
        raw: Any = json.loads(payload.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Track2ValidationProfileError(
            "TRACK2_VALIDATION_PROFILE_UNAVAILABLE_OR_INVALID"
        ) from exc

    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0.0":
        raise Track2ValidationProfileError("TRACK2_VALIDATION_PROFILE_SCHEMA_UNSUPPORTED")
    if (
        raw.get("profile_type") != "VALIDATION_ONLY"
        or raw.get("strategy_id") != "track2_asymmetric_trap"
        or not str(raw.get("profile_id") or "").strip()
    ):
        raise Track2ValidationProfileError("TRACK2_VALIDATION_PROFILE_IDENTITY_INVALID")

    disabled_flags = (
        "execution_enabled", "order_submission_enabled",
        "live_api_enabled", "real_vts_api_enabled",
    )
    if any(raw.get(key) is not False for key in disabled_flags):
        raise Track2ValidationProfileError(
            "TRACK2_VALIDATION_PROFILE_MUST_REMAIN_DISABLED"
        )

    limits = raw.get("risk_limits")
    if (
        not isinstance(limits, dict)
        or set(limits) != EXPECTED_TRACK2_RISK_LIMIT_KEYS
        or any(value is not None for value in limits.values())
    ):
        raise Track2ValidationProfileError(
            "TRACK2_VALIDATION_PROFILE_LIMITS_MUST_REMAIN_NULL"
        )

    dependencies = raw.get("unresolved_policy_dependencies")
    if (
        not isinstance(dependencies, list)
        or len(dependencies) != len(REQUIRED_TRACK2_POLICY_DEPENDENCIES)
        or set(dependencies) != REQUIRED_TRACK2_POLICY_DEPENDENCIES
    ):
        raise Track2ValidationProfileError(
            "TRACK2_VALIDATION_PROFILE_POLICY_REGISTER_MISMATCH"
        )

    return Track2ValidationProfile(
        profile_id=str(raw["profile_id"]),
        strategy_id=str(raw["strategy_id"]),
        profile_sha256=sha256(payload).hexdigest(),
        risk_limit_keys=tuple(sorted(limits)),
        policy_dependencies=tuple(sorted(dependencies)),
        execution_enabled=False,
        order_submission_enabled=False,
        live_api_enabled=False,
        real_vts_api_enabled=False,
        numeric_limits_resolved=False,
    )
