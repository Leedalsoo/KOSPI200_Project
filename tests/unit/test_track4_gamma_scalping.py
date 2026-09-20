from datetime import datetime
from decimal import Decimal

from application.composition.track4_analytics_provider import build_track4_analytics_snapshot
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track4_gamma_scalping import Track4GammaScalping, Track4MarketInput

AS_OF = datetime(2026, 9, 8, 10, 0)


def data(*, delta: str, equity: str = "1000000", history: tuple[str, ...] = ("350", "351"), time_str: str = "10:00:00") -> Track4MarketInput:
    return Track4MarketInput(
        observed_at=AS_OF, current_price=Decimal("350"), active_vol=Decimal("1"), base_vol=Decimal("1"),
        time_str=time_str, current_delta=Decimal(delta), current_gamma=Decimal("0"), current_pnl=Decimal("0"),
        current_equity=Decimal(equity), price_history=tuple(Decimal(x) for x in history), current_theta=Decimal("-0.1"),
    )


def context(payload: Track4MarketInput):
    return StrategyContext(
        strategy_id="track4_gamma_scalping",
        input=StrategyInput(payload=payload),
        analytics=build_track4_analytics_snapshot(payload, run_id="track4-test", as_of=payload.observed_at),
    )


def test_delta_hedge_positive_delta_is_sell_with_domain_quantity() -> None:
    hedge = Track4GammaScalping().evaluate(context(data(delta="0.41")))[0]
    assert hedge.execution_proposal is not None
    assert hedge.execution_proposal.asset_type == "FUTURES"
    assert hedge.execution_proposal.proposed_quantity == 3
    assert hedge.execution_proposal.side == "SELL"


def test_delta_hedge_negative_delta_is_buy_with_domain_quantity() -> None:
    hedge = Track4GammaScalping().evaluate(context(data(delta="-0.41")))[0]
    assert hedge.execution_proposal is not None
    assert hedge.execution_proposal.proposed_quantity == 3
    assert hedge.execution_proposal.side == "BUY"


def test_delta_equal_deadband_does_not_hedge() -> None:
    assert Track4GammaScalping().evaluate(context(data(delta="0.2", history=("350",)))) == ()


def test_delta_hedge_quantity_is_clamped_to_one_hundred() -> None:
    hedge = Track4GammaScalping().evaluate(context(data(delta="30")))[0]
    assert hedge.execution_proposal is not None
    assert hedge.execution_proposal.proposed_quantity == 100
    assert hedge.execution_proposal.side == "SELL"


def test_equity_threshold_unwinds_existing_hedge_and_blocks_new_hedge() -> None:
    strategy = Track4GammaScalping(equity_threshold=Decimal("100"))
    strategy.state.active_hedge_qty = -3
    signals = strategy.evaluate(context(data(delta="1", equity="99")))
    assert len(signals) == 1
    assert "UNWIND_FUT_HEDGE" in signals[0].reason
    assert strategy.state.active_hedge_qty == 0


def test_basecamp_cutoff_at_1515_blocks_new_entry() -> None:
    strategy = Track4GammaScalping()
    assert strategy.evaluate(context(data(delta="0", time_str="15:15:00"))) == ()
