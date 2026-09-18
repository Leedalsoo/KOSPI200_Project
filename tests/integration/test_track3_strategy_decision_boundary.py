from datetime import datetime

from application.composition.runtime_strategy_result_collection_adapter import (
    RuntimeStrategyResultCollectionAdapter,
)
from application.composition.runtime_strategy_to_decision_adapter import (
    RuntimeStrategyToDecisionAdapter,
)
from core.decision.decision_arbiter import DecisionArbiter
from core.domain.market_models import MarketState
from core.strategy.contracts import (
    CommonStrategyInput,
    StrategyContext,
    StrategyInput,
)
from core.strategy.track3_statistical_arbitrage import (
    Track3MarketInput,
    Track3StatisticalArbitrage,
)


def _context(data: Track3MarketInput) -> StrategyContext:
    as_of = datetime(2026, 9, 18, 10, 0)
    return StrategyContext(
        market_state=MarketState(as_of=as_of, ticks={}, quality={}),
        strategy_id="Strategy_3_StatArb",
        input=StrategyInput(
            common=CommonStrategyInput(as_of=as_of, current_price=500),
            payload=data,
        ),
    )


def _entry_data() -> Track3MarketInput:
    return Track3MarketInput(
        spread_history=(1.0,) * 9 + (2.0,),
        active_vol=0.1,
        base_vol=0.1,
        bid_ask_spread=0.02,
        contract_multiplier=250000,
        current_price=500,
        options_legs=(
            {
                "strike": 500,
                "price": 1,
                "qty": 1,
                "side": "BUY",
                "type": "CALL",
                "current_market_price": 1,
                "contract_multiplier": 250000,
            },
        ),
        date_str="2026-09-18",
        time_str="10:00:00",
    )


def test_track3_entry_signal_materializes_to_canonical_decision():
    strategy = Track3StatisticalArbitrage()
    result = strategy.evaluate_input(_entry_data())

    assert result.status == "ENTER"
    signal = result.signals[0]
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.asset_type == "FUTURES"
    assert signal.execution_proposal.side == "SELL"
    assert signal.execution_proposal.proposed_quantity == 1

    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=1,
        context=_context(_entry_data()),
        result=result,
    )
    decision = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
        evaluations,
        price=500.0,
        timestamp="2026-09-18T10:00:00",
        account={"available_cash": 250_000_000},
    )

    assert len(decision.canonical_signals) == 1
    canonical = decision.canonical_signals[0]
    assert canonical.track_id == "Strategy_3_StatArb"
    assert canonical.asset_type.value == "FUTURES"
    assert canonical.side.value == "SELL"
    assert canonical.qty == 1
    assert len(decision.arbitration.approved_signals) == 1


def test_track3_signal_without_execution_proposal_remains_fail_closed():
    strategy = Track3StatisticalArbitrage()
    result = strategy.evaluate_input(_entry_data())
    signal = result.signals[0]

    from core.strategy.contracts import Signal

    broken = Signal(
        strategy_id=signal.strategy_id,
        direction=signal.direction,
        confidence=signal.confidence,
        reason=signal.reason,
        execution_proposal=None,
    )
    broken_result = type(result)(
        status=result.status,
        regime=result.regime,
        z_score=result.z_score,
        signals=(broken,),
    )

    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=1,
        context=_context(_entry_data()),
        result=broken_result,
    )
    decision = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
        evaluations,
        price=500.0,
        timestamp="2026-09-18T10:00:00",
        account={"available_cash": 250_000_000},
    )

    assert decision.canonical_signals == ()
    assert decision.arbitration.approved_signals == []

