from datetime import datetime

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from contracts.types import DataQuality, MarketState


def test_standard_runtime_materializes_track5_analytics_snapshot():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    account = bootstrap.bundle.account
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    state = MarketState(
        as_of=datetime.fromisoformat(tick.timestamp),
        ticks={"KOSPI200": tick},
        quality={"KOSPI200": DataQuality(True, True, True)},
    )
    context = StandardRuntimeInputProvider(market).build(tick, state, account)["track5_gap_divergence"]
    assert context.analytics is not None
    assert context.analytics.run_id == "virtual"
    assert context.analytics.get("price.gap") is not None
    assert context.analytics.get("stats.z_score") is not None


def test_standard_runtime_track5_fails_closed_when_volatility_is_missing():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    account = bootstrap.bundle.account
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    market._recent_ticks.clear()
    state = MarketState(as_of=datetime.fromisoformat(tick.timestamp), ticks={"KOSPI200": tick}, quality={})
    context = StandardRuntimeInputProvider(market).build(tick, state, account)["track5_gap_divergence"]
    assert context.analytics is not None
    assert context.analytics.get("volatility.expected_move").value is None
