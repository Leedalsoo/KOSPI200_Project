from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
from typing import Iterable

@dataclass(frozen=True)
class SyntheticLongOptionLeg:
    leg_id: str
    side: str
    quantity: int
    ask_price: Decimal
    contract_multiplier: Decimal

@dataclass(frozen=True)
class ValidationRiskBudgetResult:
    verdict: str
    computed_gross_premium_krw: int
    computed_max_loss_krw: int
    computed_concurrent_exposure_krw: int
    operational_reference_overage_krw: int
    validation_budget_overage_krw: int
    validation_only: bool = True

def load_validation_profile(path: str | Path, strategy_key: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("validation_only") is not True or payload.get("runtime_eligible") is not False:
        raise ValueError("VALIDATION_ONLY_PROFILE_REQUIRED")
    if payload.get("allow_live_orders") is not False or payload.get("allow_kis_api") is not False:
        raise ValueError("OPERATIONAL_ACCESS_MUST_REMAIN_DISABLED")
    if payload.get("risk_checks_enabled") is not True:
        raise ValueError("VALIDATION_RISK_CHECKS_MUST_REMAIN_ENABLED")
    try:
        profile = payload["profiles"][strategy_key]
    except KeyError as exc:
        raise ValueError("VALIDATION_RISK_PROFILE_NOT_FOUND") from exc
    return profile

def evaluate_validation_budget(
    legs: Iterable[SyntheticLongOptionLeg], profile: dict
) -> ValidationRiskBudgetResult:
    gross = Decimal("0")
    for leg in legs:
        if str(leg.side).upper() != "BUY":
            raise ValueError("VALIDATION_PROFILE_SUPPORTS_LONG_OPTIONS_ONLY")
        if leg.quantity <= 0 or leg.ask_price <= 0 or leg.contract_multiplier <= 0:
            raise ValueError("INVALID_SYNTHETIC_RISK_INPUT")
        gross += leg.ask_price * leg.quantity * leg.contract_multiplier
    gross_krw = int(gross)
    max_loss_krw = gross_krw
    reference = int(profile["operational_reference_limit_krw"])
    validation_limit = int(profile["max_gross_premium_outlay_krw"])
    validation_overage = max(0, gross_krw - validation_limit)
    verdict = "VALIDATION_ONLY_ALLOW" if validation_overage == 0 else "BLOCKED_VALIDATION_BUDGET"
    return ValidationRiskBudgetResult(
        verdict=verdict,
        computed_gross_premium_krw=gross_krw,
        computed_max_loss_krw=max_loss_krw,
        computed_concurrent_exposure_krw=gross_krw,
        operational_reference_overage_krw=max(0, gross_krw-reference),
        validation_budget_overage_krw=validation_overage,
    )
