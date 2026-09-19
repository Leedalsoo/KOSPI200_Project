from datetime import datetime, timezone

from contracts.types import ProviderHealth
from contracts.trading_state import SensorLevel
from core.monitoring.trading_sensors import (
    FreshnessPolicy,
    aggregate_sensors,
    connection_sensor,
    provider_health_sensor,
)


def test_connection_sensor_blocks_when_disconnected():
    sensor = connection_sensor("KIS_WS", connected=False)
    assert sensor.level is SensorLevel.BLOCKED


def test_provider_health_requires_explicit_freshness_policy():
    observed = datetime.now(timezone.utc)
    health = ProviderHealth(True, observed, source="KIS", observed_at=observed, freshness_seconds=1.0)
    sensor = provider_health_sensor("MARKET_DATA", health)
    assert sensor.level is SensorLevel.UNKNOWN


def test_provider_health_uses_configured_thresholds():
    observed = datetime.now(timezone.utc)
    health = ProviderHealth(True, observed, source="KIS", observed_at=observed, freshness_seconds=1.0)
    policy = FreshnessPolicy(yellow_after_seconds=2.0, red_after_seconds=5.0)
    sensor = provider_health_sensor("MARKET_DATA", health, policy=policy)
    assert sensor.level is SensorLevel.GREEN


def test_aggregate_preserves_fail_closed_overall_state():
    sensors = [connection_sensor("KIS_WS", connected=True), connection_sensor("POSITION", connected=False)]
    assert aggregate_sensors(sensors).overall_level() is SensorLevel.BLOCKED
