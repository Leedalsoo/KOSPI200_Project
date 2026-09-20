from datetime import datetime, timezone
from decimal import Decimal

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot, AnalyticsStatus
from core.analytics.engine import AnalyticsEngine
from core.analytics.track5 import build_track5_evaluators


def snapshot(**observations):
    return MarketSnapshot(
        run_id="test-run",
        as_of=datetime.now(timezone.utc),
        provenance=AnalyticsProvenance(source="test"),
        instrument_identity=None,
        observations=observations,
    )


def test_gap_and_gap_pct_are_common_analytics():
    engine = AnalyticsEngine(build_track5_evaluators())
    result = engine.evaluate(snapshot(open_price=Decimal("355"), previous_close=Decimal("350")), (
        AnalyticsRequest("price.gap", "tick", 1, ("open_price", "previous_close"), 1.0, "authoritative", "1"),
        AnalyticsRequest("price.gap_pct", "tick", 1, ("open_price", "previous_close"), 1.0, "authoritative", "1"),
    ))
    assert result.get("price.gap").value == Decimal("5")
    assert result.get("price.gap_pct").value == Decimal("5") / Decimal("350")


def test_expected_move_and_z_score_are_common_analytics():
    engine = AnalyticsEngine(build_track5_evaluators())
    result = engine.evaluate(snapshot(previous_close=Decimal("350"), active_vol=Decimal("1"), open_price=Decimal("355")), (
        AnalyticsRequest("volatility.expected_move", "tick", 1, ("previous_close", "active_vol"), 1.0, "authoritative", "1"),
        AnalyticsRequest("stats.z_score", "tick", 1, ("open_price", "previous_close", "active_vol"), 1.0, "authoritative", "1"),
    ))
    expected = Decimal("350") * (Decimal("0.15") / Decimal("15.874507866"))
    assert result.get("volatility.expected_move").value == expected
    assert result.get("stats.z_score").value == Decimal("5") / expected


def test_missing_volatility_fails_closed():
    engine = AnalyticsEngine(build_track5_evaluators())
    result = engine.evaluate(snapshot(previous_close=Decimal("350"), open_price=Decimal("355")), (
        AnalyticsRequest("volatility.expected_move", "tick", 1, ("previous_close", "active_vol"), 1.0, "authoritative", "1"),
    ))
    assert result.get("volatility.expected_move").status == AnalyticsStatus.UNAVAILABLE
    assert result.get("volatility.expected_move").value is None


def test_gap_divergence_requests_cover_strategy_features():
    engine = AnalyticsEngine(build_track5_evaluators())
    result = engine.evaluate(snapshot(open_price=Decimal("355"), previous_close=Decimal("350"), active_vol=Decimal("1"), current_price=Decimal("354"), regime="NORMAL"), (
        AnalyticsRequest("price.gap", "tick", 1, ("open_price", "previous_close"), 1.0, "authoritative", "1"),
        AnalyticsRequest("volatility.expected_move", "tick", 1, ("previous_close", "active_vol"), 1.0, "authoritative", "1"),
        AnalyticsRequest("stats.z_score", "tick", 1, ("open_price", "previous_close", "active_vol"), 1.0, "authoritative", "1"),
        AnalyticsRequest("price.last", "tick", 1, ("current_price",), 1.0, "authoritative", "1"),
        AnalyticsRequest("regime.market", "tick", 1, ("regime",), 1.0, "authoritative", "1"),
    ))
    assert result.get("price.gap").value == Decimal("5")
    assert result.get("price.last").value == Decimal("354")
    assert result.get("regime.market").value == "NORMAL"


def test_missing_gap_dependencies_fail_closed():
    engine = AnalyticsEngine(build_track5_evaluators())
    result = engine.evaluate(snapshot(open_price=Decimal("355")), (
        AnalyticsRequest("price.gap", "tick", 1, ("open_price", "previous_close"), 1.0, "authoritative", "1"),
    ))
    assert result.get("price.gap").status == AnalyticsStatus.UNAVAILABLE
    assert result.get("price.gap").value is None
