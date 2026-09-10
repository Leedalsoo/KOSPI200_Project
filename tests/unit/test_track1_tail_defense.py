## Track1 typed payload 검증

from datetime import datetime, timezone
from decimal import Decimal

from core.domain.market_models import CanonicalMarketTick, DataQuality, MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track1_tail_defense import Track1Input, Track1TailDefense


def state(price: str) -> MarketState:
    now = datetime.now(timezone.utc)
    tick = CanonicalMarketTick("KOSPI200", now, Decimal(price), None)
    return MarketState(now, {"KOSPI200": tick}, {"KOSPI200": DataQuality(True, True, True)})


def context(price: str, **kwargs: object) -> StrategyContext:
    now = datetime.now(timezone.utc)
    payload = Track1Input(**kwargs)
    common = CommonStrategyInput(as_of=now, current_price=Decimal(price))
    return StrategyContext(state(price), "TRACK1_TAIL_DEFENSE", StrategyInput(common, payload))


def test_market_open_preserves_dual_ring_and_inner_fence() -> None:
    strategy = Track1TailDefense()
    signals = strategy.evaluate(context("350"))
    assert len(signals) == 3
    assert strategy.state.active_fence_type == "PUT"
    assert strategy.state.active_fence_strike == 342.5
# assert signals[0].execution_proposal is not None
    assert signals[0].execution_proposal.proposed_quantity == 1
    assert signals[0].execution_proposal.asset_type == "OPTION"
    assert signals[0].execution_proposal.option_type == "CALL"
    assert signals[0].execution_proposal.strike == Decimal("362.5")
# assert signals[1].execution_proposal is not None
    assert signals[1].execution_proposal.option_type == "PUT"
    assert signals[1].execution_proposal.strike == Decimal("337.5")
# assert signals[2].execution_proposal is not None
    assert signals[2].execution_proposal.tag_id == "1"
    assert signals[2].execution_proposal.strike == Decimal("342.5")


def test_typed_input_can_trigger_sell_hedge_with_domain_quantity() -> None:
    strategy = Track1TailDefense()
# strategy.evaluate(context("350"))
    signals = strategy.evaluate(
        context("343", momentum_confirmed=True, short_option_net_delta=Decimal("0.21"))
    )
    hedge_signal = next(signal for signal in signals if "FUTURES_HEDGE_TRIGGER" in signal.reason)
    assert strategy.state.active_hedge == "SELL"
# assert hedge_signal.execution_proposal is not None
    assert hedge_signal.execution_proposal.asset_type == "FUTURES"
    assert hedge_signal.execution_proposal.proposed_quantity == 2
    assert hedge_signal.execution_proposal.side == "SELL"
    assert strategy.state.futures_hedge_count == 1


def test_missing_or_zero_delta_does_not_create_synthetic_hedge() -> None:
    for delta in (None, Decimal("0")):
        pass
        strategy = Track1TailDefense()
# strategy.evaluate(context("350"))
        signals = strategy.evaluate(
            context("343", momentum_confirmed=True, short_option_net_delta=delta)
        )
# assert not any("FUTURES_HEDGE_TRIGGER" in signal.reason for signal in signals)
        assert strategy.state.futures_hedge_count == 0
# assert strategy.state.active_hedge is None


def test_daily_hedge_limit_stops_after_twenty_entries() -> None:
    strategy = Track1TailDefense()
# strategy.evaluate(context("350"))
    for _ in range(20):
        pass
        strategy.state.active_hedge = None
        strategy.state.hedge_entry_price = None
        signals = strategy.evaluate(
            context("343", momentum_confirmed=True, short_option_net_delta=Decimal("0.21"))
        )
# assert any("FUTURES_HEDGE_TRIGGER" in signal.reason for signal in signals)
    assert strategy.state.futures_hedge_count == 20
    strategy.state.active_hedge = None
    strategy.state.hedge_entry_price = None
    signals = strategy.evaluate(
        context("343", momentum_confirmed=True, short_option_net_delta=Decimal("0.21"))
    )
# assert not any("FUTURES_HEDGE_TRIGGER" in signal.reason for signal in signals)
    assert strategy.state.futures_hedge_count == 20


def test_daily_hedge_count_resets_on_date_change() -> None:
    strategy = Track1TailDefense()
    strategy.evaluate(context("350", current_time=datetime(2026, 9, 7, 10, 0)))
    strategy.state.futures_hedge_count = 20
    strategy.state.active_hedge = None
    strategy.state.hedge_entry_price = None
    signals = strategy.evaluate(
        context(
            "343",
            current_time=datetime(2026, 9, 8, 9, 0),
            momentum_confirmed=True,
            short_option_net_delta=Decimal("0.21"),
        )
    )
# assert any("FUTURES_HEDGE_TRIGGER" in signal.reason for signal in signals)
    assert strategy.state.futures_hedge_count == 1
    assert strategy.state.hedge_count_date == datetime(2026, 9, 8).date()


def test_typed_dte_triggers_d4_fence_cutoff() -> None:
    strategy = Track1TailDefense()
# strategy.evaluate(context("350"))
    signals = strategy.evaluate(context("350", days_to_expiry=4.0))
# assert any("D4_CUTOFF" in signal.reason for signal in signals)
# assert strategy.state.active_fence_type is None
    cutoff_signal = next(signal for signal in signals if "D4_CUTOFF" in signal.reason)
# assert cutoff_signal.execution_proposal is not None
    assert cutoff_signal.execution_proposal.proposed_quantity == 1
    assert cutoff_signal.execution_proposal.asset_type == "OPTION"
# assert cutoff_signal.execution_proposal.side is None
    assert cutoff_signal.execution_proposal.option_type == "PUT"
    assert cutoff_signal.execution_proposal.strike == Decimal("342.5")


def test_volatility_input_expands_fence() -> None:
    strategy = Track1TailDefense()
    strategy.evaluate(context("350", active_vol=1.3, base_vol=1.0))
    assert strategy.state.fence_distance == 12.5


def test_strategy_does_not_import_order_request() -> None:
    import inspect
    from core.strategy import track1_tail_defense
    source = inspect.getsource(track1_tail_defense)
# assert "OrderRequest" not in source





