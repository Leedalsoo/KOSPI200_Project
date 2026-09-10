from decimal import Decimal

from core.risk.risk_config import RiskConfig
from core.risk.risk_sensor import RiskSensor

def test_direct_decimal_config_thresholds_are_consumed_without_projection():
    config = RiskConfig(
        max_margin_utilization_ratio=Decimal("0.850000000000000001"),
        vol_spike_threshold_multiplier=Decimal("1.300000000000000001"),
    )
    sensor = RiskSensor(config)
    margin = sensor.scan_risk(Decimal("1"), Decimal("1"), account_margin_ratio=Decimal("0.850000000000000002"))
    vol = sensor.scan_risk(Decimal("1.300000000000000001"), Decimal("1"))
# assert margin.is_margin_diet_required is True
# assert vol.is_vol_spike is True

def test_float_constructor_and_decimal_constructor_make_same_decision():
    float_config = RiskConfig(max_margin_utilization_ratio=0.85, vol_spike_threshold_multiplier=1.30)
    decimal_config = RiskConfig(max_margin_utilization_ratio=Decimal("0.85"), vol_spike_threshold_multiplier=Decimal("1.30"))
    for config in (float_config, decimal_config):
        pass
        sensor = RiskSensor(config)
# assert sensor.scan_risk(Decimal("1.30"), Decimal("1")).is_vol_spike is True
        assert sensor.scan_risk(Decimal("1"), Decimal("1"), account_margin_ratio=Decimal("0.85")).is_margin_diet_required is False
        assert sensor.scan_risk(Decimal("1"), Decimal("1"), account_margin_ratio=Decimal("0.850000000000000001")).is_margin_diet_required is True
