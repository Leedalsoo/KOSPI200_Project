from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from contracts.analytics import AnalyticsStatus
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track8_macro_regime_monthly_strangle import (
    Track8MacroRegimeMonthlyStrangle,
    Track8State,
)


def _metric(value):
    return SimpleNamespace(status=AnalyticsStatus.AVAILABLE, value=value)


def test_track8_default_unresolved_dte_budget_and_risk_gate_blocks_entry() -> None:
    strategy = Track8MacroRegimeMonthlyStrangle()
    context = SimpleNamespace(
        strategy_id=strategy.strategy_id,
        analytics=SimpleNamespace(as_of=datetime(2026, 10, 21, 10, 0), get=lambda key: _metric(Decimal("20"))),
        input=SimpleNamespace(common=SimpleNamespace(budget=Decimal("500000"), date_str="20261021")),
    )

    assert strategy.DTE_ENTRY is None
    assert strategy.MIN_BUDGET is None
    assert strategy.evaluate_entry(context) == ()


def test_track8_macro_put_overlay_and_profit_rebuild_are_retired() -> None:
    strategy = Track8MacroRegimeMonthlyStrangle()
    context = SimpleNamespace(
        analytics=SimpleNamespace(
            as_of=datetime(2026, 10, 21, 10, 0),
            get=lambda key: _metric("HIGH_VOL" if key == "market.current_regime" else Decimal("500000")),
        )
    )

    assert strategy.evaluate_macro_regime_protection(context) == ()
    assert strategy.evaluate_profit_rebuild(context) == ()


def test_track8_per_leg_50pct_stop_closes_only_the_triggered_option() -> None:
    strategy = Track8MacroRegimeMonthlyStrangle()
    strategy.state = Track8State(
        is_active=True,
        premium_spent=Decimal("500000"),
        call_strike=Decimal("510"),
        put_strike=Decimal("490"),
        qty_call=1,
        qty_put=1,
        expiry="20261022",
        call_entry_fill_price=Decimal("2.0"),
        put_entry_fill_price=Decimal("3.0"),
        call_peak_mark=Decimal("2.0"),
        put_peak_mark=Decimal("3.0"),
        call_contract_multiplier=Decimal("250000"),
        put_contract_multiplier=Decimal("250000"),
        call_open=True,
        put_open=True,
    )
    analytics = SimpleNamespace(
        as_of=datetime(2026, 10, 21, 13, 0),
        get=lambda key: _metric({
            "options.track8_call_mark_price": Decimal("1.0"),
            "options.track8_put_mark_price": Decimal("3.2"),
        }.get(key)),
    )
    signals = strategy.evaluate_take_profit(SimpleNamespace(analytics=analytics))

    assert len(signals) == 1
    proposal = signals[0].execution_proposal
    assert proposal.tag_id == "MONTHLY_STRANGLE_CLOSE_CALL"
    plan = strategy.build_execution_plan(group_id="s8-call-close", proposal=proposal)
    assert plan.purpose == "MONTHLY_STRANGLE_CLOSE_CALL"
    assert len(plan.legs) == 1
    assert plan.legs[0].leg_id == "call"
    assert plan.legs[0].side == "SELL"


def test_track8_expiry_day_force_close_is_1510() -> None:
    strategy = Track8MacroRegimeMonthlyStrangle()
    strategy.state = Track8State(
        is_active=True, call_strike=Decimal("510"), put_strike=Decimal("490"),
        qty_call=1, qty_put=1, expiry="20261021",
    )
    before = SimpleNamespace(analytics=SimpleNamespace(as_of=datetime(2026, 10, 21, 15, 9, 59)))
    at_cutoff = SimpleNamespace(analytics=SimpleNamespace(as_of=datetime(2026, 10, 21, 15, 10, 0)))

    assert strategy.evaluate_expiry_cutoff(before) == ()
    signals = strategy.evaluate_expiry_cutoff(at_cutoff)
    assert len(signals) == 1
    assert signals[0].reason == "MONTHLY_EXPIRY_15:10_FORCE_CLOSE"
