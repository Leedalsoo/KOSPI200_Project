from decimal import Decimal
from pathlib import Path
import pytest
from environments.high_speed.validation_only_option_risk_budget import (
    SyntheticLongOptionLeg, evaluate_validation_budget, load_validation_profile,
)

ROOT = Path(__file__).resolve().parents[3]
PROFILE_PATH = ROOT / "config/validation_only/q25_strategy7_8_risk_profiles.v1.json"

def test_strategy7_budget_counts_two_expiry_groups_and_logs_operational_overage():
    profile = load_validation_profile(PROFILE_PATH, "track7_weekly_insurance")
    legs = [
        SyntheticLongOptionLeg("mon_put", "BUY", 1, Decimal("1.20"), Decimal("250000")),
        SyntheticLongOptionLeg("mon_call", "BUY", 1, Decimal("1.10"), Decimal("250000")),
        SyntheticLongOptionLeg("thu_put", "BUY", 1, Decimal("1.20"), Decimal("250000")),
        SyntheticLongOptionLeg("thu_call", "BUY", 1, Decimal("1.10"), Decimal("250000")),
    ]
    result = evaluate_validation_budget(legs, profile)
    assert result.verdict == "VALIDATION_ONLY_ALLOW"
    assert result.computed_gross_premium_krw == 1150000
    assert result.computed_max_loss_krw == 1150000
    assert result.operational_reference_overage_krw == 900000
    assert result.validation_budget_overage_krw == 0

def test_strategy8_budget_uses_pair_premium_without_macro_scaleup():
    profile = load_validation_profile(PROFILE_PATH, "track8_monthly_strangle")
    legs = [
        SyntheticLongOptionLeg("call", "BUY", 1, Decimal("1.10"), Decimal("250000")),
        SyntheticLongOptionLeg("put", "BUY", 1, Decimal("1.20"), Decimal("250000")),
    ]
    result = evaluate_validation_budget(legs, profile)
    assert result.verdict == "VALIDATION_ONLY_ALLOW"
    assert result.computed_gross_premium_krw == 575000
    assert result.operational_reference_overage_krw == 325000

def test_budget_overrun_is_not_silently_allowed():
    profile = dict(load_validation_profile(PROFILE_PATH, "track8_monthly_strangle"))
    profile["max_gross_premium_outlay_krw"] = 100000
    legs = [SyntheticLongOptionLeg("call", "BUY", 1, Decimal("1.0"), Decimal("250000"))]
    result = evaluate_validation_budget(legs, profile)
    assert result.verdict == "BLOCKED_VALIDATION_BUDGET"
    assert result.validation_budget_overage_krw == 150000

def test_missing_or_invalid_risk_inputs_fail_closed():
    profile = load_validation_profile(PROFILE_PATH, "track8_monthly_strangle")
    with pytest.raises(ValueError, match="INVALID_SYNTHETIC_RISK_INPUT"):
        evaluate_validation_budget(
            [SyntheticLongOptionLeg("put", "BUY", 1, Decimal("0"), Decimal("250000"))],
            profile,
        )
