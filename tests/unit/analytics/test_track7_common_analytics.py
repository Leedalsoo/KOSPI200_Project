from datetime import datetime, timezone
from decimal import Decimal

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, AnalyticsStatus, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track7 import build_track7_evaluators
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance


def snapshot(**observations):
    return MarketSnapshot(
        run_id="track7-test",
        as_of=datetime.now(timezone.utc),
        provenance=AnalyticsProvenance(source="test"),
        instrument_identity=None,
        observations=observations,
    )


def requests():
    return tuple(
        AnalyticsRequest(key, "tick", 1, deps, 1.0, "authoritative", "1")
        for key, deps in (
            ("price.last", ("current_price",)),
            ("options.call_iv", ("call_iv",)),
            ("options.put_iv", ("put_iv",)),
            ("options.skew", ("call_iv", "put_iv")),
            ("trend.ma_1m", ("ma_1m",)),
            ("trend.ma_3m", ("ma_3m",)),
            ("trend.ma_5m", ("ma_5m",)),
            ("trend.ma_10m", ("ma_10m",)),
            ("levels.support", ("support",)),
            ("levels.resistance", ("resistance",)),
            ("calendar.is_new_week_start", ("is_new_week_start",)),
            ("calendar.is_expiry_day", ("is_expiry_day",)),
            ("calendar.is_week_end", ("is_week_end",)),
            ("execution.order_timeout", ("order_timeout",)),
        )
    )


def test_track7_common_analytics_provides_required_features():
    result = AnalyticsEngine(build_track7_evaluators()).evaluate(
        snapshot(
            current_price=Decimal("350"), call_iv=Decimal("10"), put_iv=Decimal("13"),
            ma_1m=Decimal("354"), ma_3m=Decimal("353"), ma_5m=Decimal("352"), ma_10m=Decimal("351"),
            support=Decimal("348.35"), resistance=Decimal("356.65"),
            is_new_week_start=True, is_expiry_day=False, is_week_end=False,
            order_timeout=False,
        ), requests()
    )
    assert result.get("options.skew").value == Decimal("3")
    assert result.get("trend.ma_10m").value == Decimal("351")
    assert result.get("levels.support").value == Decimal("348.35")
    assert result.get("calendar.is_new_week_start").value is True


def test_track7_missing_source_is_fail_closed():
    result = AnalyticsEngine(build_track7_evaluators()).evaluate(
        snapshot(call_iv=Decimal("10"), put_iv=None),
        tuple(requests()[0:4]),
    )
    assert result.get("options.skew").status is AnalyticsStatus.UNAVAILABLE
    assert result.get("options.skew").value is None


def test_track7_strategy_declares_common_analytics_features():
    keys = {item.metric_key for item in Track7VolatilitySkewWeeklyInsurance().feature_requirements()}
    assert keys == {
        "price.last", "options.call_iv", "options.put_iv", "options.skew",
        "trend.ma_1m", "trend.ma_3m", "trend.ma_5m", "trend.ma_10m",
        "levels.support", "levels.resistance",
        "calendar.is_new_week_start", "calendar.is_expiry_day", "calendar.is_week_end",
        "execution.order_timeout",
    }


def test_track7_strategy_consumes_analytics_snapshot():
    analytics = AnalyticsEngine(build_track7_evaluators()).evaluate(
        snapshot(
            current_price=Decimal("350"), call_iv=Decimal("10"), put_iv=Decimal("10"),
            ma_1m=Decimal("354"), ma_3m=Decimal("353"), ma_5m=Decimal("352"), ma_10m=Decimal("351"),
            support=Decimal("348.35"), resistance=Decimal("356.65"),
            is_new_week_start=False, is_expiry_day=False, is_week_end=False,
            order_timeout=False,
        ), requests()
    )
    context = StrategyContext(
        strategy_id="track7_volatility_skew_weekly_insurance",
        input=StrategyInput(),
        analytics=analytics,
    )
    strategy = Track7VolatilitySkewWeeklyInsurance()
    assert strategy.evaluate(context) == ()
