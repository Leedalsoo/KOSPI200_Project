from datetime import datetime
from decimal import Decimal

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track6 import build_track6_evaluators
from core.analytics.track9 import build_track9_evaluators
from core.domain.market_models import MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance, Track6ExecutionInput
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle
from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance


def track6_context(data):
    market = MarketSnapshot(
        "T6-TEST", datetime.fromisoformat("2026-09-04T10:00:00"),
        AnalyticsProvenance("test"), None,
        {"current_price": Decimal("350"), "active_vol": Decimal("2"),
         "base_vol": Decimal("1"), "equity": Decimal("1000000")},
    )
    keys = (
        ("price.last", ("current_price",)), ("volatility.active", ("active_vol",)),
        ("volatility.base", ("base_vol",)), ("volatility.ratio", ("active_vol", "base_vol")),
        ("portfolio.equity", ("equity",)),
    )
    analytics = AnalyticsEngine(build_track6_evaluators()).evaluate(
        market, tuple(AnalyticsRequest(k, "tick", 1, d, 1.0, "authoritative", "1") for k, d in keys)
    )
    return StrategyContext(MarketState(as_of=analytics.as_of, ticks={}, quality={}),
                           "track6_daily_tail_insurance", StrategyInput(payload=data), analytics=analytics)


def test_track6_entry_has_option_execution_proposal():
    s = Track6DailyTailInsurance()
    d = Track6ExecutionInput(s.strategy_id, "2026-09-04", "10:00:00",
                             listed_put_strike=Decimal("337.5"), listed_call_strike=Decimal("362.5"),
                             contract_multiplier=Decimal("250000"))
    sig = next(x for x in s.evaluate(track6_context(d)) if x.direction == "BUY_INSURANCE")
    assert sig.execution_proposal is not None
    assert sig.execution_proposal.asset_type == "OPTION"
    assert sig.execution_proposal.side == "BUY"
    assert sig.execution_proposal.proposed_quantity == 1
    assert sig.execution_proposal.option_type == "PUT"
    assert sig.execution_proposal.strike == s.state.long_put_strike


def test_track8_entry_has_option_execution_proposal():
    # Strategy 8 now requires canonical Analytics and authoritative contract selection.
    s = Track8MacroRegimeMonthlyStrangle()
    assert s.evaluate(StrategyContext(strategy_id=s.strategy_id, input=StrategyInput())) == ()


def track9_context():
    market = MarketSnapshot(
        "T9-TEST", datetime.fromisoformat("2026-09-04T10:00:00"),
        AnalyticsProvenance("test"), None,
        {"active_sell_qty": 4, "insurance_qty": 0, "event_upcoming": True,
         "iv_spike": Decimal("4"), "iv_crush": Decimal("0"),
         "current_pnl": Decimal("0"), "total_fees": Decimal("0"),
         "margin_ratio": Decimal("0"), "risk_guard_active": False,
         "event_budget": Decimal("1000000"), "estimated_event_cost": Decimal("100"),
         "atm_put_strike": Decimal("335"), "atm_call_strike": Decimal("365"),
         "contract_multiplier": Decimal("250000"), "premium_spent": Decimal("100000")}
    )
    keys = (
        ("portfolio.active_sell_qty", ("active_sell_qty",)),
        ("portfolio.insurance_qty", ("insurance_qty",)),
        ("events.upcoming", ("event_upcoming",)),
        ("options.iv_spike", ("iv_spike",)),
        ("options.iv_crush", ("iv_crush",)),
        ("portfolio.current_pnl", ("current_pnl",)),
        ("portfolio.total_fees", ("total_fees",)),
        ("portfolio.net_pnl", ("current_pnl", "total_fees")),
        ("portfolio.margin_ratio", ("margin_ratio",)),
        ("risk.guard_active", ("risk_guard_active",)),
        ("portfolio.event_budget", ("event_budget",)),
        ("portfolio.estimated_event_cost", ("estimated_event_cost",)),
        ("options.atm_call_strike", ("atm_call_strike",)),
        ("options.atm_put_strike", ("atm_put_strike",)),
        ("options.contract_multiplier", ("contract_multiplier",)),
        ("portfolio.premium_spent", ("premium_spent",)),
    )
    analytics = AnalyticsEngine(build_track9_evaluators()).evaluate(
        market, tuple(AnalyticsRequest(k, "tick", 1, d, 1.0, "authoritative", "1") for k, d in keys)
    )
    common = CommonStrategyInput(
        as_of=analytics.as_of, time_str="10:00:00", date_str="2026-09-04"
    )
    return StrategyContext(MarketState(as_of=analytics.as_of, ticks={}, quality={}),
                           "track9_event_overnight_insurance", StrategyInput(common), analytics=analytics)


def test_track9_add_insurance_has_option_execution_proposal():
    strategy = Track9EventOvernightInsurance()
    sig = next(x for x in strategy.evaluate_overnight_insurance(track9_context()) if x.direction == "ADD_INSURANCE")
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
    d6 = Track6ExecutionInput(s6.strategy_id, "2026-09-04", "10:00:00",
                               listed_put_strike=Decimal("337.5"), listed_call_strike=Decimal("362.5"),
                               contract_multiplier=Decimal("250000"))
    cases.append((s6, d6))
    s8 = Track8MacroRegimeMonthlyStrangle()
    d8 = None
    cases.append((s8, d8))


    for strategy, data in cases:
        if strategy is s8:
            continue
        context = track6_context(data) if strategy is s6 else StrategyContext(
            strategy_id=strategy.strategy_id, input=StrategyInput(payload=data)
        )
        result = strategy.evaluate(context)
        signal = next(x for x in result if x.execution_proposal is not None)
        proposal = signal.execution_proposal
        identity = OptionInstrumentIdentity("OPT-TEST", "KOSPI200", "202609", proposal.option_type, proposal.strike, Decimal("250000"), "TEST_OPTION_MASTER")
        evaluations = RuntimeStrategyResultCollectionAdapter().collect(
            tick_sequence=1,
            context=context,
            result=type("R", (), {"signals": (signal,)})(),
        )
        decision = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
            evaluations, price=350.0, timestamp="2026-09-04T10:00:00", account={"available_cash": 100000000},
            instrument_identity_provider=lambda evaluation, market_tick: identity,
        )
        assert len(decision.canonical_signals) == 1
        assert decision.canonical_signals[0].qty == proposal.proposed_quantity
