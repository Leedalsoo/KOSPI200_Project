from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

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
    ):
        payload = contexts[strategy_id].input.payload
        assert payload.__class__.__name__ == "UnavailableStrategyPayload"
        assert contexts[strategy_id].input.data_status
        assert all(value == "UNAVAILABLE" for value in contexts[strategy_id].input.data_status.values())

    track9 = contexts["track9_event_overnight_insurance"]
    assert track9.analytics is not None
    assert track9.analytics.get("events.upcoming").value is None
    assert track9.analytics.get("risk.guard_active").value is None


def test_track7_consumes_authoritative_call_put_iv_without_unblocking_missing_sources():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    account = bootstrap.bundle.account
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    state = MarketState(
        as_of=datetime.fromisoformat(tick.timestamp),
        ticks={"KOSPI200": tick},
        quality={"KOSPI200": DataQuality(True, True, True)},
    )

    class AuthoritativeIVSource:
        def get_iv(self, *, expiry, option_type, strike):
            return {"CALL": Decimal("20.0"), "PUT": Decimal("25.0")}[option_type]

    provider = StandardRuntimeInputProvider(
        market, track2_option_iv_source=AuthoritativeIVSource()
    )
    context = provider.build(tick, state, account)["track7_volatility_skew_weekly_insurance"]
    assert "option_iv_chain" not in context.input.data_status
    assert context.input.data_status == {
        "moving_average": "UNAVAILABLE",
        "order_timeout": "UNAVAILABLE",
        "support_resistance": "UNAVAILABLE",
        "expiry_calendar": "UNAVAILABLE",
    }
    assert context.input.payload.__class__.__name__ == "UnavailableStrategyPayload"


def test_track7_moving_average_uses_timestamped_vms_history_without_fallback():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    base_tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    base_time = datetime.fromisoformat(base_tick.timestamp)
    market._recent_ticks.clear()
    for index in range(11):
        timestamp = base_time + timedelta(minutes=index)
        market._recent_ticks.append(
            replace(base_tick, timestamp=timestamp.isoformat(), last_price=348 + index)
        )
    tick = market.recent_ticks[-1]
    data = StandardRuntimeInputProvider(market).data.snapshot(tick)

    assert data.status["track7_moving_average"].available is True
    assert data.status["track7_moving_average"].source == "VMS.recent_ticks"
    assert all(value is not None for value in (data.ma_1m, data.ma_3m, data.ma_5m, data.ma_10m))
    for minutes, actual in ((1, data.ma_1m), (3, data.ma_3m), (5, data.ma_5m), (10, data.ma_10m)):
        cutoff = datetime.fromisoformat(tick.timestamp).timestamp() - minutes * 60
        values = [
            Decimal(str(item.last_price))
            for item in market.recent_ticks
            if cutoff <= datetime.fromisoformat(item.timestamp).timestamp() <= datetime.fromisoformat(tick.timestamp).timestamp()
        ]
        assert actual == sum(values, Decimal("0")) / Decimal(len(values))


def test_track7_moving_average_stays_unavailable_without_history_coverage():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    data = StandardRuntimeInputProvider(market).data.snapshot(tick)
    assert data.status["track7_moving_average"].available is False
    assert data.status["track7_moving_average"].reason == "TRACK7_MOVING_AVERAGE_HISTORY_COVERAGE_UNAVAILABLE"
    assert all(value is None for value in (data.ma_1m, data.ma_3m, data.ma_5m, data.ma_10m))


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
        track5_context = contexts["track5_gap_divergence"]
        assert track5_context.analytics is not None
        assert track5_context.analytics.get("volatility.expected_move").value is None
        track6_context = contexts["track6_daily_tail_insurance"]
        if track6_context.analytics is not None:
            assert track6_context.analytics.get("volatility.active").value is None
            assert track6_context.analytics.get("volatility.base").value is None
            assert track6_context.analytics.get("volatility.ratio").value is None
            assert track6_context.analytics.get("portfolio.premium_spent").value is None
        else:
            assert track6_context.input.data_status["listed_option_contracts"] == "UNAVAILABLE"
    finally:
        market._recent_ticks.extend(original)


def test_track6_runtime_input_uses_listed_option_contract_source():
    from types import SimpleNamespace
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    account = bootstrap.bundle.account
    ticks = list(market.generate_tick_stream(total_days=1, ticks_per_day=11))
    tick = ticks[-1]
    state = MarketState(
        as_of=datetime.fromisoformat(tick.timestamp),
        ticks={"KOSPI200": tick},
        quality={"KOSPI200": DataQuality(True, True, True)},
    )
    selection = SimpleNamespace(
        put=SimpleNamespace(strike=Decimal("337.5"), contract_multiplier=Decimal("123456")),
        call=SimpleNamespace(strike=Decimal("362.5"), contract_multiplier=Decimal("123456")),
    )
    source = SimpleNamespace(select=lambda **kwargs: selection)
    provider = StandardRuntimeInputProvider(market, track6_option_contract_source=source)
    payload = provider.build(tick, state, account)["track6_daily_tail_insurance"].input.payload
    assert payload.listed_put_strike == Decimal("337.5")
    assert payload.listed_call_strike == Decimal("362.5")
    assert payload.contract_multiplier == Decimal("123456")
