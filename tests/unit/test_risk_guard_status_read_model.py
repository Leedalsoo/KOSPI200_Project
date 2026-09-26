from datetime import timezone

from core.analytics.common import build_common_analytics_snapshot
from core.risk.risk_guard import RiskGuard
from contracts.analytics import AnalyticsProvenance, MarketSnapshot, AnalyticsStatus
from contracts.trading_state import SensorLevel, SensorSnapshot, TradingHealthSnapshot


def _green_health():
    return TradingHealthSnapshot.from_sensors(
        [SensorSnapshot("MARKET_DATA", SensorLevel.GREEN, reason="fresh")]
    )


def test_risk_guard_exposes_authoritative_status_snapshot():
    guard = RiskGuard()
    decision = guard.evaluate(health=_green_health(), kill_switch_engaged=False)

    status = guard.snapshot()

    assert decision.allowed is True
    assert status is not None
    assert status.admission_allowed is True
    assert status.kill_switch_engaged is False
    assert status.health_level is SensorLevel.GREEN
    assert status.reason == "READY"
    assert status.decision_version == "1"
    assert status.observed_at.tzinfo is timezone.utc


def test_risk_guard_status_is_unavailable_until_fresh_evaluation():
    guard = RiskGuard()
    assert guard.snapshot() is None

    guard.evaluate(health=_green_health(), kill_switch_engaged=False)
    assert guard.snapshot() is not None

    guard.reset()
    assert guard.snapshot() is None


def test_common_risk_guard_metric_uses_authoritative_status():
    guard = RiskGuard()
    guard.evaluate(health=_green_health(), kill_switch_engaged=False)
    status = guard.snapshot()

    market = MarketSnapshot(
        run_id="risk-guard-test",
        as_of=status.observed_at,
        provenance=AnalyticsProvenance(source="test"),
        instrument_identity=None,
        observations={"risk_guard_status": status},
    )
    snapshot = build_common_analytics_snapshot(market, ("risk.guard_active",))
    metric = snapshot.get("risk.guard_active")

    assert metric is not None
    assert metric.status is AnalyticsStatus.AVAILABLE
    assert metric.value is True
    assert metric.provenance[0].source == "risk-guard.authoritative"
    assert metric.provenance[0].source_as_of == status.observed_at
