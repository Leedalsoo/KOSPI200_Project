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


def track9_context(*, date_str="2026-09-04", time_str="15:00:00", price="350", put_mark="12", call_mark="12"):
    market = MarketSnapshot(
        "T9-TEST", datetime.fromisoformat(f"{date_str}T{time_str}"),
        AnalyticsProvenance("test"), None,
        {"current_price": Decimal(price),
         "atm_put_strike": Decimal("335"), "atm_call_strike": Decimal("365"),
         "contract_multiplier": Decimal("250000"),
         "track9_put_entry_price": Decimal("10"), "track9_call_entry_price": Decimal("10"),
         "track9_put_mark_price": Decimal(put_mark), "track9_call_mark_price": Decimal(call_mark)}
    )
    keys = (
        ("price.last", ("current_price",)),
        ("options.atm_call_strike", ("atm_call_strike",)),
        ("options.atm_put_strike", ("atm_put_strike",)),
        ("options.contract_multiplier", ("contract_multiplier",)),
        ("options.track9_put_entry_price", ("track9_put_entry_price",)),
        ("options.track9_call_entry_price", ("track9_call_entry_price",)),
        ("options.track9_put_mark_price", ("track9_put_mark_price",)),
        ("options.track9_call_mark_price", ("track9_call_mark_price",)),
    )
    analytics = AnalyticsEngine(build_track9_evaluators()).evaluate(
        market, tuple(AnalyticsRequest(k, "tick", 1, d, 1.0, "authoritative", "1") for k, d in keys)
    )
    common = CommonStrategyInput(
        as_of=analytics.as_of,
        current_price=Decimal(price),
        time_str=time_str,
        date_str=date_str,
    )
    return StrategyContext(
        MarketState(as_of=analytics.as_of, ticks={}, quality={}),
        "track9_event_overnight_insurance",
        StrategyInput(common),
        analytics=analytics,
    )


def test_track9_entry_is_an_independent_put_call_pair():
    strategy = Track9EventOvernightInsurance()
    signals = strategy.evaluate(track9_context(time_str="15:10:00"))
    assert [x.direction for x in signals] == [
        "ENTER_OVERNIGHT_STRANGLE_PUT",
        "ENTER_OVERNIGHT_STRANGLE_CALL",
    ]
    assert signals[0].execution_proposal.option_type == "PUT"
    assert signals[1].execution_proposal.option_type == "CALL"
    assert signals[0].execution_proposal.proposed_quantity == 1
    assert signals[1].execution_proposal.proposed_quantity == 1


def test_track9_closes_after_next_open_shock_or_stops_without_shock():
    strategy = Track9EventOvernightInsurance()
    strategy.evaluate(track9_context(time_str="15:10:00"))

    shock = strategy.evaluate(track9_context(
        date_str="2026-09-05", time_str="09:00:01", price="353.5"
    ))
    assert shock == ()
    assert strategy.state.trailing_active is True

    trailing_close = strategy.evaluate(track9_context(
        date_str="2026-09-05", time_str="09:01:01", price="353.5", put_mark="10.5", call_mark="10.5"
    ))
    assert [x.direction for x in trailing_close] == [
        "CLOSE_OVERNIGHT_INSURANCE_PUT",
        "CLOSE_OVERNIGHT_INSURANCE_CALL",
    ]
    assert all(x.execution_proposal is not None for x in trailing_close)

    strategy.reset()
    strategy.evaluate(track9_context(time_str="15:10:00"))
    no_shock = strategy.evaluate(track9_context(
        date_str="2026-09-05", time_str="09:00:01", price="350.7"
    ))
    assert [x.direction for x in no_shock] == [
        "STOP_LOSS_OVERNIGHT_INSURANCE_PUT",
        "STOP_LOSS_OVERNIGHT_INSURANCE_CALL",
    ]
    assert all(x.execution_proposal is not None for x in no_shock)


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
