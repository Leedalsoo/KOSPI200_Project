from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.standard_runtime_input_provider import StandardRuntimeInputProvider
from contracts.trading_state import SensorLevel, SensorSnapshot, TradingHealthSnapshot
from contracts.types import DataQuality, MarketState
from core.risk.risk_guard import RiskGuard


def test_track8_gate_requires_canonical_common_metrics():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    account = bootstrap.bundle.account
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    state = MarketState(
        as_of=datetime.fromisoformat(tick.timestamp),
        ticks={"KOSPI200": tick},
        quality={"KOSPI200": DataQuality(True, True, True)},
    )
    provider = StandardRuntimeInputProvider(market)
    provider.market_condition_sensor.analyze = lambda *_args, **_kwargs: None
    context = provider.build(tick, state, account)[
        "track8_macro_regime_monthly_strangle"
    ]
    required_sources = context.input.payload.required_sources
    assert "market.current_regime" in required_sources
    assert "risk.guard_active" in required_sources
    assert "macro_regime" not in required_sources


def test_standard_runtime_input_provider_track9_gate_requires_canonical_common_metrics():
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
    track9 = contexts["track9_event_overnight_insurance"]
    assert track9.input.payload.__class__.__name__ == "UnavailableStrategyPayload"
    assert "volatility.active" in track9.input.payload.required_sources
    assert "portfolio.total_fees" in track9.input.payload.required_sources

def test_standard_runtime_input_provider_consumes_authoritative_risk_guard_status():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    account = bootstrap.bundle.account
    tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    state = MarketState(
        as_of=datetime.fromisoformat(tick.timestamp),
        ticks={"KOSPI200": tick},
        quality={"KOSPI200": DataQuality(True, True, True)},
    )
    guard = RiskGuard()
    guard.evaluate(
        health=TradingHealthSnapshot.from_sensors(
            [SensorSnapshot("MARKET_DATA", SensorLevel.GREEN, reason="fresh")]
        ),
        kill_switch_engaged=False,
    )

    contexts = StandardRuntimeInputProvider(
        market, risk_guard_status_source=guard
    ).build(tick, state, account)
    track9 = contexts["track9_event_overnight_insurance"]
    assert track9.input.payload.__class__.__name__ == "UnavailableStrategyPayload"
    assert "risk.guard_active" not in track9.input.payload.required_sources


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
    assert track9.input.payload.__class__.__name__ == "UnavailableStrategyPayload"
    assert "events.upcoming" in track9.input.payload.required_sources
    assert "risk.guard_active" in track9.input.payload.required_sources


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
        "listed_option_contracts": "UNAVAILABLE",
    }
    assert context.input.payload.__class__.__name__ == "UnavailableStrategyPayload"


def test_track7_moving_average_uses_timestamped_vms_history_without_fallback():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    base_tick = next(market.generate_tick_stream(total_days=1, ticks_per_day=1))
    base_time = datetime.fromisoformat(base_tick.timestamp)
    market._recent_ticks.clear()
    market._underlying_history.clear()
    for index in range(11):
        timestamp = base_time + timedelta(minutes=index)
        market.publish_replay_tick(
            replace(
                base_tick,
                timestamp=timestamp.isoformat(),
                underlying_price=348 + index,
                last_price=Decimal(str(999 - index)),
            )
        )
    tick = market.recent_ticks[-1]
    data = StandardRuntimeInputProvider(market).data.snapshot(tick)

    assert data.status["track7_moving_average"].available is True
    assert data.status["track7_moving_average"].source == "VMS.underlying_history"
    assert all(value is not None for value in (data.ma_1m, data.ma_3m, data.ma_5m, data.ma_10m))
    for minutes, actual in ((1, data.ma_1m), (3, data.ma_3m), (5, data.ma_5m), (10, data.ma_10m)):
        cutoff = datetime.fromisoformat(tick.timestamp).timestamp() - minutes * 60
        values = [
            price
            for timestamp, price in market.underlying_history
            if cutoff <= timestamp.timestamp() <= datetime.fromisoformat(tick.timestamp).timestamp()
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
        assert track5_context.analytics is None
        assert track5_context.input.data_status["KOSPI200_daily_open_previous_close"] == "UNAVAILABLE"
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
