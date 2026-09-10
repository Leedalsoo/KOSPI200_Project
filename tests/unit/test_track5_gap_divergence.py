from decimal import Decimal

from core.strategy.track5_gap_divergence import Track5GapDivergence, Track5MarketInput


STRATEGY_ID = "track5_gap_divergence"


def data(open_price="355", previous_close="350", active_vol="1", regime="NORMAL", current_price=None):
    return Track5MarketInput(
        strategy_id=STRATEGY_ID,
        open_price=Decimal(open_price),
        previous_close=Decimal(previous_close),
        active_vol=Decimal(active_vol),
        regime=regime,
        current_price=None if current_price is None else Decimal(current_price),
    )


def context_for(payload):
    from datetime import datetime, timezone
    from core.domain.market_models import MarketState
    from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput

    state = MarketState(as_of=datetime.now(timezone.utc), ticks={}, quality={})
    common = CommonStrategyInput(as_of=state.as_of, current_price=payload.current_price)
    return StrategyContext(state, STRATEGY_ID, StrategyInput(common=common, payload=payload))


def test_normal_gap_up_enters_short():
    s = Track5GapDivergence()
    signals = s.evaluate_gap(data())
    assert signals and signals[0].direction == "SHORT"
    assert s.state.target_price == Decimal("350")


def test_normal_gap_down_enters_long():
    s = Track5GapDivergence()
    signals = s.evaluate_gap(data("345", "350", "1", "NORMAL"))
    assert signals and signals[0].direction == "LONG"


def test_high_vol_threshold_is_more_strict():
    s = Track5GapDivergence()
    assert s.effective_z_threshold("HIGH_VOL") == Decimal("1.8")
    assert s.effective_z_threshold("NOISE_CHOPPY") == Decimal("1.8")


def test_extreme_gap_is_blocked():
    s = Track5GapDivergence()
    signals = s.evaluate_gap(data("370", "350", "1", "NORMAL"))
    assert signals == ()
    assert not s.state.is_active


def test_mean_reversion_target_closes_position():
    s = Track5GapDivergence()
    s.evaluate_gap(data())
    signals = s.evaluate_mean_reversion(Decimal("350"))
    assert signals and signals[0].direction == "CLOSE"
    assert not s.state.is_active


def test_timeout_closes_after_30_ticks():
    s = Track5GapDivergence()
    s.evaluate_gap(data())
    for _ in range(29):
        s.evaluate_mean_reversion(Decimal("354"))
    signals = s.evaluate_mean_reversion(Decimal("354"))
    assert signals and "TIMEOUT_15M" in signals[0].reason


def test_trailing_lock_closes_after_reversal():
    s = Track5GapDivergence()
    s.evaluate_gap(data())
    s.evaluate_mean_reversion(Decimal("353"))
    signals = s.evaluate_mean_reversion(Decimal("354.5"))
    assert signals and signals[0].direction == "CLOSE"


def test_strategy_context_input_is_used():
    s = Track5GapDivergence()
    signals = s.evaluate(context_for(data()))
    assert signals and signals[0].direction == "SHORT"


def test_context_strategy_id_mismatch_does_not_trade():
    s = Track5GapDivergence()
    from datetime import datetime, timezone
    from core.domain.market_models import MarketState
    from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput

    payload = data()
    state = MarketState(as_of=datetime.now(timezone.utc), ticks={}, quality={})
    common = CommonStrategyInput(as_of=state.as_of)
    bad_context = StrategyContext(state, "another_strategy", StrategyInput(common, payload))
    assert s.evaluate(bad_context) == ()


def test_payload_strategy_id_mismatch_does_not_trade():
    s = Track5GapDivergence()
    from dataclasses import replace
    payload = replace(data(), strategy_id="another_strategy")
    assert s.evaluate(context_for(payload)) == ()


def test_strategy_has_no_legacy_order_dependency():
    import inspect
    from core.strategy import track5_gap_divergence
    source = inspect.getsource(track5_gap_divergence)
    assert "OrderRequest" not in source
    assert "Broker" not in source
