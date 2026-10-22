from decimal import Decimal

import pytest

from core.strategy.track1_tail_defense import Track1TailDefense


def test_track1_put_base_fence_is_buy_not_inferred_sell() -> None:
    strategy = Track1TailDefense()

    signal = strategy._build_fence_signal(
        "PUT", 87.5, 0, "TAIL_DEFENSE_BUILD_OUTER", side="BUY"
    )

    assert signal.direction == "BUY"
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.side == "BUY"
    assert signal.execution_proposal.asset_type == "OPTION"
    assert signal.execution_proposal.option_type == "PUT"
    assert signal.execution_proposal.strike == Decimal("87.5")


def test_track1_short_put_fence_remains_explicit_sell() -> None:
    strategy = Track1TailDefense()

    signal = strategy._build_fence_signal(
        "PUT", 92.5, 1, "INITIAL_INNER_FENCE", side="SELL"
    )

    assert signal.direction == "SELL"
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.side == "SELL"
    assert signal.execution_proposal.asset_type == "OPTION"


def test_track1_rejects_implicit_or_invalid_order_side() -> None:
    strategy = Track1TailDefense()

    with pytest.raises(ValueError, match="TRACK1_OPTION_SIDE_INVALID"):
        strategy._build_fence_signal(
            "PUT", 92.5, 1, "INITIAL_INNER_FENCE", side="HOLD"
        )


def test_track1_new_entry_blocks_when_approved_config_and_risk_gates_are_unverified() -> None:
    from datetime import datetime
    from contracts.types import CanonicalMarketTick, MarketState
    from core.strategy.contracts import StrategyContext

    strategy = Track1TailDefense()
    now = datetime(2026, 10, 21, 10, 0)
    market_state = MarketState(
        as_of=now,
        ticks={"KOSPI200": CanonicalMarketTick(instrument_id="KOSPI200", observed_at=now, price=Decimal("500"))},
        quality={},
    )
    context = StrategyContext(market_state=market_state, strategy_id=strategy.strategy_id)

    assert strategy.evaluate(context) == []
    assert strategy.state.market_opened is False
