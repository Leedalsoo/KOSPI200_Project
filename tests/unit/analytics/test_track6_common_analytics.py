from datetime import datetime, timezone
from decimal import Decimal

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track6 import build_track6_evaluators
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance


def snapshot(**observations):
    return MarketSnapshot(
        run_id="track6-test",
        as_of=datetime.now(timezone.utc),
        provenance=AnalyticsProvenance(source="test"),
        instrument_identity=None,
        observations=observations,
    )


def test_track6_common_analytics_provides_required_features():
    engine = AnalyticsEngine(build_track6_evaluators())
    requests = tuple(
        AnalyticsRequest(key, "tick", 1, deps, 1.0, "authoritative", "1")
        for key, deps in (
            ("price.last", ("current_price",)),
            ("volatility.active", ("active_vol",)),
            ("volatility.base", ("base_vol",)),
            ("volatility.ratio", ("active_vol", "base_vol")),
            ("portfolio.premium_spent", ("premium_spent",)),
        )
    )
    result = engine.evaluate(
        snapshot(
            current_price=Decimal("350"),
            active_vol=Decimal("1.5"),
            base_vol=Decimal("1"),
            premium_spent=Decimal("1000000"),
        ),
        requests,
    )
    assert result.get("price.last").value == Decimal("350")
    assert result.get("volatility.active").value == Decimal("1.5")
    assert result.get("volatility.base").value == Decimal("1")
    assert result.get("volatility.ratio").value == Decimal("1.5")
    assert result.get("portfolio.premium_spent").value == Decimal("1000000")


def test_track6_strategy_declares_common_analytics_features():
    keys = {item.metric_key for item in Track6DailyTailInsurance().feature_requirements()}
    assert keys == {
        "price.last",
        "volatility.active",
        "volatility.base",
        "volatility.ratio",
        "portfolio.premium_spent",
    }


def test_track6_strategy_consumes_analytics_snapshot():
    analytics = AnalyticsEngine(build_track6_evaluators()).evaluate(
        snapshot(
            current_price=Decimal("350"),
            active_vol=Decimal("2"),
            base_vol=Decimal("1"),
            premium_spent=Decimal("1000000"),
        ),
        tuple(
            AnalyticsRequest(key, "tick", 1, deps, 1.0, "authoritative", "1")
            for key, deps in (
                ("price.last", ("current_price",)),
                ("volatility.active", ("active_vol",)),
                ("volatility.base", ("base_vol",)),
                ("volatility.ratio", ("active_vol", "base_vol")),
                ("portfolio.premium_spent", ("premium_spent",)),
            )
        ),
    )
    context = StrategyContext(
        CommonStrategyInput(as_of=analytics.as_of),
        "track6_daily_tail_insurance",
        StrategyInput(CommonStrategyInput(as_of=analytics.as_of)),
        analytics=analytics,
    )
    assert Track6DailyTailInsurance().evaluate(context) == ()
