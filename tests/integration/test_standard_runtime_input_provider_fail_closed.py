from datetime import datetime

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from contracts.types import DataQuality, MarketState


def test_standard_runtime_input_provider_never_fabricates_blocked_fields():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    account = bootstrap.bundle.account
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    state = MarketState(
        as_of=datetime.fromisoformat(tick.timestamp),
        ticks={"KOSPI200": tick},
        quality={"KOSPI200": DataQuality(True, True, True)},
    )

    contexts = StandardRuntimeInputProvider(market).build(tick, state, account)

    for strategy_id in (
        "TRACK1_TAIL_DEFENSE",
        "track2_asymmetric_trap",
        "Strategy_3_StatArb",
        "track7_volatility_skew_weekly_insurance",
        "track8_macro_regime_monthly_strangle",
        "track9_event_overnight_insurance",
    ):
        payload = contexts[strategy_id].input.payload
        assert payload.__class__.__name__ == "UnavailableStrategyPayload"
        assert contexts[strategy_id].input.data_status
        assert all(value == "UNAVAILABLE" for value in contexts[strategy_id].input.data_status.values())


def test_standard_runtime_input_provider_blocks_track5_and_track6_when_volatility_source_is_missing():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    account = bootstrap.bundle.account
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    state = MarketState(as_of=datetime.fromisoformat(tick.timestamp), ticks={"KOSPI200": tick}, quality={})
    provider = StandardRuntimeInputProvider(market)

    original = market.recent_ticks
    market._recent_ticks.clear()
    try:
        contexts = provider.build(tick, state, account)
        for strategy_id in ("track5_gap_divergence", "track6_daily_tail_insurance"):
            payload = contexts[strategy_id].input.payload
            assert payload.__class__.__name__ == "UnavailableStrategyPayload"
            assert "active_vol" in contexts[strategy_id].input.data_status or "base_vol" in contexts[strategy_id].input.data_status
    finally:
        market._recent_ticks.extend(original)
