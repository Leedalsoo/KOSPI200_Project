from datetime import datetime, timezone
from decimal import Decimal

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track5 import build_track5_evaluators
from core.domain.market_models import MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track5_gap_divergence import Track5GapDivergence


STRATEGY_ID = "track5_gap_divergence"


def analytics(open_price="355", previous_close="350", active_vol="1", regime="NORMAL", current_price=None):
    now = datetime.now(timezone.utc)
    observations = {
        "open_price": Decimal(open_price),
        "previous_close": Decimal(previous_close),
        "active_vol": Decimal(active_vol),
        "current_price": Decimal(current_price if current_price is not None else open_price),
        "regime": regime,
    }
    snapshot = MarketSnapshot(
        run_id="test-run", as_of=now, provenance=AnalyticsProvenance(source="test"),
        instrument_identity=None, observations=observations,
    )
    requests = tuple(
        AnalyticsRequest(key, "tick", 1, deps, 1.0, "authoritative", "1")
        for key, deps in (
            ("price.open", ("open_price",)),
            ("price.gap", ("open_price", "previous_close")),
            ("price.last", ("current_price",)),
            ("price.previous_close", ("previous_close",)),
            ("volatility.expected_move", ("previous_close", "active_vol")),
            ("stats.z_score", ("open_price", "previous_close", "active_vol")),
            ("regime.market", ("regime",)),
        )
    )
    return AnalyticsEngine(build_track5_evaluators()).evaluate(snapshot, requests)


def context_for(snapshot):
    return StrategyContext(
        MarketState(as_of=snapshot.as_of, ticks={}, quality={}),
        STRATEGY_ID,
        StrategyInput(CommonStrategyInput(as_of=snapshot.as_of)),
        analytics=snapshot,
    )


def test_normal_gap_up_enters_short():
    s = Track5GapDivergence()
    signals = s.evaluate_gap(analytics())
    assert signals and signals[0].direction == "SHORT"
    assert s.state.target_price == Decimal("350")


def test_normal_gap_down_enters_long():
    s = Track5GapDivergence()
    signals = s.evaluate_gap(analytics("345", "350", "1", "NORMAL"))
    assert signals and signals[0].direction == "LONG"


def test_high_vol_threshold_is_more_strict():
    s = Track5GapDivergence()
    assert s.effective_z_threshold("HIGH_VOL") == Decimal("1.8")
    assert s.effective_z_threshold("NOISE_CHOPPY") == Decimal("1.8")


def test_extreme_gap_is_blocked():
    s = Track5GapDivergence()
    signals = s.evaluate_gap(analytics("370", "350", "1", "NORMAL"))
    assert signals == ()
    assert not s.state.is_active


def test_mean_reversion_target_closes_position():
    s = Track5GapDivergence()
    s.evaluate_gap(analytics())
    signals = s.evaluate_mean_reversion(Decimal("350"))
    assert signals and signals[0].direction == "CLOSE"
    assert not s.state.is_active


def test_timeout_closes_after_30_ticks():
    s = Track5GapDivergence()
    s.evaluate_gap(analytics())
    for _ in range(29):
        s.evaluate_mean_reversion(Decimal("354"))
    signals = s.evaluate_mean_reversion(Decimal("354"))
    assert signals and "TIMEOUT_15M" in signals[0].reason


def test_trailing_lock_closes_after_reversal():
    s = Track5GapDivergence()
    s.evaluate_gap(analytics())
    s.evaluate_mean_reversion(Decimal("353"))
    signals = s.evaluate_mean_reversion(Decimal("354.5"))
    assert signals and signals[0].direction == "CLOSE"


def test_strategy_context_input_is_analytics_only():
    s = Track5GapDivergence()
    signals = s.evaluate(context_for(analytics()))
    assert signals and signals[0].direction == "SHORT"


def test_context_strategy_id_mismatch_does_not_trade():
    snapshot = analytics()
    bad_context = StrategyContext(
        MarketState(as_of=snapshot.as_of, ticks={}, quality={}),
        "another_strategy", StrategyInput(CommonStrategyInput(as_of=snapshot.as_of)),
        analytics=snapshot,
    )
    assert Track5GapDivergence().evaluate(bad_context) == ()


def test_missing_analytics_fails_closed():
    s = Track5GapDivergence()
    snapshot = analytics()
    metrics = dict(snapshot.metrics)
    metrics.pop("stats.z_score")
    from dataclasses import replace
    blocked = replace(snapshot, metrics=metrics)
    assert s.evaluate(context_for(blocked)) == ()


def test_strategy_declares_common_analytics_features():
    keys = {item.metric_key for item in Track5GapDivergence().feature_requirements()}
    assert keys == {
        "price.open", "price.gap", "price.last", "price.previous_close",
        "volatility.expected_move", "stats.z_score", "regime.market",
    }


def test_strategy_does_not_contain_legacy_common_calculations():
    import inspect
    from core.strategy import track5_gap_divergence
    source = inspect.getsource(track5_gap_divergence)
    assert "daily_std_points" not in source
    assert "Track5MarketInput" not in source
    assert "OrderRequest" not in source
    assert "Broker" not in source
