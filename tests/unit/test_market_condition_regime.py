from datetime import datetime, timezone
from decimal import Decimal

from contracts.analytics import AnalyticsStatus, MarketSnapshot
from contracts.types import CanonicalMarketTick, DataQuality, MarketState
from core.analytics.common import build_common_analytics_snapshot
from core.sensor.market_condition_sensor import MarketConditionSensor


def _state(price: str) -> MarketState:
    tick = CanonicalMarketTick("KOSPI200", datetime.now(timezone.utc), Decimal(price))
    return MarketState(tick.observed_at, {tick.instrument_id: tick}, {tick.instrument_id: DataQuality(True, True, True)})


def test_regime_thresholds_and_precedence():
    sensor = MarketConditionSensor()
    assert sensor._regime(0.0, 1.0) == "NORMAL"
    assert sensor._regime(0.0, 1.4) == "HIGH_VOL"
    assert sensor._regime(0.0, 2.5) == "CRASH"
    assert sensor._regime(0.02, 1.0) == "CRASH"
    assert sensor._regime(0.08, 3.0) == "CIRCUIT_BREAKER"


def test_sensor_materializes_authoritative_regime():
    sensor = MarketConditionSensor()
    first = sensor.analyze(_state("100"), "KOSPI200")
    second = sensor.analyze(_state("108"), "KOSPI200")
    assert first.current_regime == "NORMAL"
    assert second.current_regime == "CIRCUIT_BREAKER"


def test_common_regime_metric_uses_authoritative_provenance_and_fails_closed():
    available = MarketSnapshot("run", datetime.now(timezone.utc), None, None, {"current_regime": "CRASH"})
    snapshot = build_common_analytics_snapshot(available, ("market.current_regime",))
    metric = snapshot.get("market.current_regime")
    assert metric.status is AnalyticsStatus.AVAILABLE
    assert metric.value == "CRASH"
    assert metric.provenance[0].source == "market-condition.authoritative"

    missing = MarketSnapshot("run", available.as_of, None, None, {})
    blocked = build_common_analytics_snapshot(missing, ("market.current_regime",))
    assert blocked.get("market.current_regime").status is AnalyticsStatus.UNAVAILABLE
