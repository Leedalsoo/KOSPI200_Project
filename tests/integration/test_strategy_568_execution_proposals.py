from decimal import Decimal

from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance, Track6MarketInput
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle, Track8MarketInput
from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance, Track9MarketInput


def test_track6_entry_has_option_execution_proposal():
    s = Track6DailyTailInsurance()
    d = Track6MarketInput(s.strategy_id, Decimal("350"), Decimal("2"), Decimal("1"), Decimal("1000000"), "2026-09-04")
    sig = next(x for x in s.evaluate(StrategyContext(strategy_id=s.strategy_id, input=StrategyInput(payload=d))) if x.direction == "BUY_INSURANCE")
    assert sig.execution_proposal is not None
    assert sig.execution_proposal.asset_type == "OPTION"
    assert sig.execution_proposal.side == "BUY"
    assert sig.execution_proposal.proposed_quantity == 1
    assert sig.execution_proposal.option_type == "PUT"
    assert sig.execution_proposal.strike == s.state.long_put_strike


def test_track8_entry_has_option_execution_proposal():
    s = Track8MacroRegimeMonthlyStrangle()
    d = Track8MarketInput(s.strategy_id, Decimal("20"), Decimal("2000000"), Decimal("350"), "NORMAL", "2026-09-04")
    sig = next(x for x in s.evaluate(StrategyContext(strategy_id=s.strategy_id, input=StrategyInput(payload=d))) if x.direction == "BUY_LIMIT_TRANCHE")
    assert sig.execution_proposal is not None
    assert sig.execution_proposal.asset_type == "OPTION"
    assert sig.execution_proposal.side == "BUY"
    assert sig.execution_proposal.proposed_quantity == s.state.qty_call
    assert sig.execution_proposal.option_type == "CALL"
    assert sig.execution_proposal.strike == s.state.call_strike


def test_track9_add_insurance_has_option_execution_proposal():
    s = Track9EventOvernightInsurance()
    d = Track9MarketInput(s.strategy_id, Decimal("350"), 4, 0, "2026-09-04")
    sig = next(x for x in s.evaluate_overnight_insurance(d) if x.direction == "ADD_INSURANCE")
    assert sig.execution_proposal is not None
    assert sig.execution_proposal.asset_type == "OPTION"
    assert sig.execution_proposal.side == "BUY"
    assert sig.execution_proposal.proposed_quantity == 2
    assert sig.execution_proposal.option_type == "PUT"
    assert sig.execution_proposal.strike == Decimal("335")


def test_track6_8_9_proposals_reach_canonical_boundary():
    from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyResultCollectionAdapter
    from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
    from contracts.types import OptionInstrumentIdentity
    from core.decision.decision_arbiter import DecisionArbiter

    cases = []
    s6 = Track6DailyTailInsurance()
    d6 = Track6MarketInput(s6.strategy_id, Decimal("350"), Decimal("2"), Decimal("1"), Decimal("1000000"), "2026-09-04")
    cases.append((s6, d6))
    s8 = Track8MacroRegimeMonthlyStrangle()
    d8 = Track8MarketInput(s8.strategy_id, Decimal("20"), Decimal("2000000"), Decimal("350"), "NORMAL", "2026-09-04")
    cases.append((s8, d8))
    s9 = Track9EventOvernightInsurance()
    d9 = Track9MarketInput(s9.strategy_id, Decimal("350"), 4, 0, "2026-09-04")
    cases.append((s9, d9))

    for strategy, data in cases:
        result = strategy.evaluate(StrategyContext(strategy_id=strategy.strategy_id, input=StrategyInput(payload=data)))
        signal = next(x for x in result if x.execution_proposal is not None)
        proposal = signal.execution_proposal
        identity = OptionInstrumentIdentity("OPT-TEST", "KOSPI200", "202609", proposal.option_type, proposal.strike, Decimal("250000"), "TEST_OPTION_MASTER")
        evaluations = RuntimeStrategyResultCollectionAdapter().collect(
            tick_sequence=1,
            context=StrategyContext(strategy_id=strategy.strategy_id, input=StrategyInput(payload=data)),
            result=type("R", (), {"signals": (signal,)})(),
        )
        decision = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
            evaluations, price=350.0, timestamp="2026-09-04T10:00:00", account={"available_cash": 100000000},
            instrument_identity_provider=lambda evaluation, market_tick: identity,
        )
        assert len(decision.canonical_signals) == 1
        assert decision.canonical_signals[0].qty == proposal.proposed_quantity
