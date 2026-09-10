from decimal import Decimal

import pytest

from core.risk.risk_config import RiskConfig


def test_defaults_use_decimal_authoritative_thresholds():
    config = RiskConfig()

    assert config.max_daily_loss_krw == Decimal("10000000")
    assert config.max_margin_utilization_ratio == Decimal("0.85")
    assert config.vol_spike_threshold_multiplier == Decimal("1.30")


def test_constructor_preserves_float_input_compatibility_at_boundary():
    config = RiskConfig(
        max_daily_loss_krw=100.25,
        max_margin_utilization_ratio=0.85,
        vol_spike_threshold_multiplier=1.30,
    )

    assert isinstance(config.max_daily_loss_krw, Decimal)
    assert isinstance(config.max_margin_utilization_ratio, Decimal)
    assert isinstance(config.vol_spike_threshold_multiplier, Decimal)
    assert config.max_daily_loss_krw == Decimal(str(100.25))
    assert config.max_margin_utilization_ratio == Decimal(str(0.85))
    assert config.vol_spike_threshold_multiplier == Decimal(str(1.30))


def test_high_precision_string_and_decimal_boundaries_are_preserved():
    config = RiskConfig(
        max_daily_loss_krw="10000000.000000000000000001",
        max_margin_utilization_ratio="0.850000000000000001",
        vol_spike_threshold_multiplier=Decimal("1.300000000000000001"),
    )

    assert config.max_daily_loss_krw == Decimal("10000000.000000000000000001")
    assert config.max_margin_utilization_ratio == Decimal("0.850000000000000001")
    assert config.vol_spike_threshold_multiplier == Decimal("1.300000000000000001")


def test_duration_values_remain_float_domain():
    config = RiskConfig(
        account_stale_timeout_sec=12.5,
        position_stale_timeout_sec=7.25,
    )

    assert config.account_stale_timeout_sec == 12.5
    assert config.position_stale_timeout_sec == 7.25


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("max_daily_loss_krw", None, "RISK_CONFIG_DECIMAL_VALUE_REQUIRED"),
        (
            "max_daily_loss_krw",
            float("nan"),
            "RISK_CONFIG_DECIMAL_VALUE_FINITE_REQUIRED",
        ),
        (
            "max_daily_loss_krw",
            float("inf"),
            "RISK_CONFIG_DECIMAL_VALUE_FINITE_REQUIRED",
        ),
        ("max_daily_loss_krw", True, "RISK_CONFIG_DECIMAL_VALUE_REQUIRED"),
        (
            "max_margin_utilization_ratio",
            "NaN",
            "RISK_CONFIG_DECIMAL_VALUE_FINITE_REQUIRED",
        ),
        (
            "vol_spike_threshold_multiplier",
            "Infinity",
            "RISK_CONFIG_DECIMAL_VALUE_FINITE_REQUIRED",
        ),
    ],
)
def test_invalid_decimal_thresholds_fail_fast(field, value, error):
    with pytest.raises(ValueError, match=error):
        RiskConfig(**{field: value})


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("max_order_qty", 0, "MAX_ORDER_QTY_POSITIVE_INT_REQUIRED"),
        ("max_order_qty", True, "MAX_ORDER_QTY_POSITIVE_INT_REQUIRED"),
        (
            "max_position_per_instrument",
            -1,
            "MAX_POSITION_PER_INSTRUMENT_POSITIVE_INT_REQUIRED",
        ),
        ("max_daily_loss_krw", "0", "MAX_DAILY_LOSS_KRW_POSITIVE_REQUIRED"),
        ("max_daily_loss_krw", "-1", "MAX_DAILY_LOSS_KRW_POSITIVE_REQUIRED"),
        (
            "max_margin_utilization_ratio",
            "0",
            "MAX_MARGIN_UTILIZATION_RATIO_RANGE_REQUIRED",
        ),
        (
            "max_margin_utilization_ratio",
            "1.0001",
            "MAX_MARGIN_UTILIZATION_RATIO_RANGE_REQUIRED",
        ),
        (
            "vol_spike_threshold_multiplier",
            "0",
            "VOL_SPIKE_THRESHOLD_MULTIPLIER_POSITIVE_REQUIRED",
        ),
    ],
)
def test_invalid_domain_ranges_fail_fast(field, value, error):
    with pytest.raises(ValueError, match=error):
        RiskConfig(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_stale_timeout_sec", -1),
        ("account_stale_timeout_sec", float("nan")),
        ("position_stale_timeout_sec", float("inf")),
        ("position_stale_timeout_sec", True),
    ],
)
def test_invalid_timeouts_fail_fast(field, value):
    with pytest.raises(
        ValueError,
        match=f"{field.upper()}_NONNEGATIVE_FINITE_REQUIRED",
    ):
        RiskConfig(**{field: value})


def test_valid_boundaries_preserve_constructor_compatibility():
    config = RiskConfig(
        max_daily_loss_krw=1,
        max_margin_utilization_ratio=1,
        vol_spike_threshold_multiplier=Decimal("0.0001"),
        account_stale_timeout_sec=0,
        position_stale_timeout_sec="12.5",
    )

    assert config.max_daily_loss_krw == Decimal("1")
    assert config.max_margin_utilization_ratio == Decimal("1")
    assert config.vol_spike_threshold_multiplier == Decimal("0.0001")
    assert config.account_stale_timeout_sec == 0.0
    assert config.position_stale_timeout_sec == 12.5
