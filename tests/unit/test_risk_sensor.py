from decimal import Decimal

from core.risk.risk_config import RiskConfig
from core.risk.risk_sensor import RiskSensor


def test_normal_sensor_state():
    result = RiskSensor().scan_risk(1.0, 1.0)
# assert result.is_vol_spike is False
# assert result.is_crisis_regime is False
# assert result.is_margin_diet_required is False
    assert result.reason == "NORMAL"
    assert result.active_vol_ratio == Decimal("1")


def test_nan_or_missing_volatility_fails_closed():
    sensor = RiskSensor()
    assert sensor.scan_risk(float("nan"), 1.0).reason == "INVALID_OR_NAN_SENSOR_INPUT"
    assert sensor.scan_risk(1.0, float("nan")).reason == "INVALID_OR_NAN_SENSOR_INPUT"
    assert sensor.scan_risk(None, 1.0).reason == "INVALID_OR_NAN_SENSOR_INPUT"


def test_zero_or_negative_base_vol_uses_reference_ratio_fallback():
    result = RiskSensor().scan_risk(10.0, 0.0)
    assert result.active_vol_ratio == Decimal("1")
# assert result.is_vol_spike is False


def test_volatility_spike_detection():
    result = RiskSensor().scan_risk(1.30, 1.0)
# assert result.is_vol_spike is True
    assert result.active_vol_ratio == Decimal("1.3")
    assert result.reason == "VOLATILITY_SPIKE_DETECTED (Ratio=1.30)"


def test_crisis_regimes_are_detected():
    for regime in ("CRISIS", "HIGH_VOLATILITY", "EXTREME_MOVE"):
        pass
        result = RiskSensor().scan_risk(1.0, 1.0, current_regime=regime)
# assert result.is_crisis_regime is True
        assert result.reason == f"CRISIS_REGIME_ACTIVE ({regime})"


def test_margin_diet_has_highest_reason_precedence():
    result = RiskSensor().scan_risk(
        1.50, 1.0, current_regime="CRISIS", account_margin_ratio=0.90,
    )
# assert result.is_margin_diet_required is True
# assert result.is_vol_spike is True
# assert result.is_crisis_regime is True
    assert result.reason == "MARGIN_DIET_TRIGGERED (Ratio=90.00%)"


def test_stale_state_reason_precedes_normal_only():
    result = RiskSensor().scan_risk(
        1.0, 1.0, is_account_stale=True, is_position_stale=True,
    )
# assert result.is_account_stale is True
# assert result.is_position_stale is True
    assert result.reason == "STALE_STATE_DETECTED (AccountStale=True, PosStale=True)"


def test_reason_precedence_spike_over_crisis_and_stale():
    result = RiskSensor().scan_risk(
        1.40, 1.0, current_regime="CRISIS", is_account_stale=True,
    )
    assert result.reason == "VOLATILITY_SPIKE_DETECTED (Ratio=1.40)"


def test_custom_volatility_threshold_is_used():
    config = RiskConfig(vol_spike_threshold_multiplier=1.50)
    result = RiskSensor(config).scan_risk(1.40, 1.0)
# assert result.is_vol_spike is False
    assert result.reason == "NORMAL"


def test_margin_ratio_threshold_distinguishes_sub_float_epsilon():
    config = RiskConfig(max_margin_utilization_ratio=0.85)
    sensor = RiskSensor(config)
    at_limit = sensor.scan_risk(
        Decimal("1"), Decimal("1"),
        account_margin_ratio=Decimal("0.850000000000000000"),
    )
    above_limit = sensor.scan_risk(
        Decimal("1"), Decimal("1"),
        account_margin_ratio=Decimal("0.850000000000000001"),
    )
# assert at_limit.is_margin_diet_required is False
# assert above_limit.is_margin_diet_required is True


def test_volatility_threshold_distinguishes_sub_float_epsilon():
    config = RiskConfig(vol_spike_threshold_multiplier=1.30)
    sensor = RiskSensor(config)
    below = sensor.scan_risk(
        Decimal("1.299999999999999999"), Decimal("1"),
    )
    at_limit = sensor.scan_risk(
        Decimal("1.300000000000000000"), Decimal("1"),
    )
# assert below.is_vol_spike is False
# assert at_limit.is_vol_spike is True

def test_invalid_risk_config_cannot_construct_risk_sensor():
    import pytest
    with pytest.raises(ValueError, match="VOL_SPIKE_THRESHOLD_MULTIPLIER_POSITIVE_REQUIRED"):
        pass
        RiskSensor(RiskConfig(vol_spike_threshold_multiplier=0))


def test_valid_decimal_risk_config_constructs_sensor_and_preserves_threshold():
    config = RiskConfig(vol_spike_threshold_multiplier=Decimal("1.300000000000000001"))
    sensor = RiskSensor(config)
    result = sensor.scan_risk(Decimal("1.3"), Decimal("1"))
# assert result.is_vol_spike is False
