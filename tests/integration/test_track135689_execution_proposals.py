from decimal import Decimal

from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyResultCollectionAdapter
from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
from contracts.types import OptionInstrumentIdentity
from core.decision.decision_arbiter import DecisionArbiter
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track1_tail_defense import Track1TailDefense, Track1Input
from core.strategy.track5_gap_divergence import Track5GapDivergence, Track5MarketInput


def test_track1_futures_unwind_has_proposal_with_active_quantity():
    strategy = Track1TailDefense()
    context = StrategyContext(strategy_id=strategy.strategy_id)
    strategy.initialize(context)
    strategy.state.market_opened = True
    strategy.state.base_price = 350.0
    strategy.state.active_fence_type = "PUT"
    strategy.state.active_fence_strike = 342.5
    strategy.state.active_hedge = "SELL"
    strategy.state.hedge_entry_price = 350.0
    strategy.state.active_hedge_quantity = 3

    context = StrategyContext(
        strategy_id=strategy.strategy_id,
        input=StrategyInput(payload=Track1Input(current_time=None, momentum_confirmed=True)),
        market_state=None,
    )
    # evaluate() needs a market tick, so the quantity/proposal mapping is asserted through the helper.
    signal = strategy._build_hedge_unwind_signal()
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.asset_type == "FUTURES"
    assert signal.execution_proposal.side == "BUY"
    assert signal.execution_proposal.proposed_quantity == 3


def test_track5_entry_is_fail_closed_without_execution_metadata():
    strategy = Track5GapDivergence()
    data = Track5MarketInput(
        strategy.strategy_id,
        Decimal("360"),
        Decimal("350"),
        Decimal("1.5"),
    )
    signal = strategy.evaluate_gap(data)[0]
    assert signal.execution_proposal is None


def test_track5_entry_proposal_requires_explicit_execution_metadata():
    strategy = Track5GapDivergence()
    data = Track5MarketInput(
        strategy.strategy_id,
        Decimal("360"),
        Decimal("350"),
        Decimal("1.5"),
        execution_asset_type="FUTURES",
        position_quantity=2,
    )
    signal = strategy.evaluate_gap(data)[0]
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.asset_type == "FUTURES"
    assert signal.execution_proposal.proposed_quantity == 2
    assert signal.execution_proposal.side == "SELL"


def test_track5_proposal_reaches_decision_boundary_when_metadata_is_explicit():
    strategy = Track5GapDivergence()
    data = Track5MarketInput(
        strategy.strategy_id,
        Decimal("360"),
        Decimal("350"),
        Decimal("1.5"),
        execution_asset_type="FUTURES",
        position_quantity=2,
    )
    signal = strategy.evaluate_gap(data)[0]
    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=1,
        context=StrategyContext(strategy_id=strategy.strategy_id, input=StrategyInput(payload=data)),
        result=type("R", (), {"signals": (signal,)})(),
    )
    identity = OptionInstrumentIdentity(
        "FUT-TEST", "KOSPI200", "202609", "CALL", Decimal("350"), Decimal("250000"), "TEST_MASTER"
    )
    decision = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
        evaluations,
        price=352.0,
        timestamp="2026-09-04T10:00:00",
        account={"available_cash": 100000000},
        instrument_identity_provider=lambda evaluation, market_tick: identity,
    )
    assert len(decision.canonical_signals) == 1
    assert decision.canonical_signals[0].qty == 2
    assert decision.canonical_signals[0].side == "SELL"


