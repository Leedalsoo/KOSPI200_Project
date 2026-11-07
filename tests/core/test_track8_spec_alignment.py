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


def test_track8_default_risk_gate_blocks_entry_but_no1169_policy_is_loaded() -> None:
    strategy = Track8MacroRegimeMonthlyStrangle()
    context = SimpleNamespace(
        strategy_id=strategy.strategy_id,
        analytics=SimpleNamespace(as_of=datetime(2026, 10, 21, 10, 0), get=lambda key: _metric(Decimal("20"))),
        input=SimpleNamespace(common=SimpleNamespace(budget=None, date_str="20261021")),
    )

    assert strategy.DTE_ENTRY == Decimal("10")
    assert strategy.MIN_BUDGET is None  # No.1169 retired the old minimum-budget gate.
    assert strategy.evaluate_entry(context) == ()  # Operational readiness flags remain fail-closed by default.


def test_track8_no1169_dte10_entry_does_not_require_retired_minimum_budget() -> None:
    strategy = Track8MacroRegimeMonthlyStrangle(
        runtime_config_verified=True, risk_limits_available=True
    )
    values = {
        "options.dte": Decimal("10"),
        "market.current_regime": "NORMAL",
        "options.call_strike": Decimal("515"),
        "options.put_strike": Decimal("485"),
        "options.call_contract_multiplier": Decimal("250000"),
        "options.put_contract_multiplier": Decimal("250000"),
        "options.expiry_date": "20261119",
    }
    context = SimpleNamespace(
        strategy_id=strategy.strategy_id,
        analytics=SimpleNamespace(
            as_of=datetime(2026, 11, 2, 9, 0),
            get=lambda key: _metric(values.get(key)),
        ),
        input=SimpleNamespace(common=SimpleNamespace(budget=None, date_str="20261102")),
    )

    signals = strategy.evaluate_entry(context)

    assert len(signals) == 1
    assert signals[0].execution_proposal.option_type == "CALL"
    assert strategy.state.entry_pending is True


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


def test_track8_close_callback_updates_single_leg_state_and_releases_exit_lock():
    strategy = Track8MacroRegimeMonthlyStrangle()
    strategy.state = Track8State(
        is_active=True, qty_call=1, qty_put=1,
        call_open=True, put_open=True,
        call_strike=Decimal("515"), put_strike=Decimal("485"),
    )
    strategy._exit_pending = True
    report = SimpleNamespace(
        leg_id="call", status="FILLED", filled_quantity=1, remaining_quantity=0,
        execution_id="S8-CLOSE-CALL-1", execution_timestamp=datetime(2026, 11, 5, 9, 10),
    )
    result = SimpleNamespace(reports=(report,), position_flat=False, group_complete=True)

    strategy.on_execution_result("MONTHLY_STRANGLE_CLOSE_CALL", result)

    assert strategy.state.call_open is False
    assert strategy.state.put_open is True
    assert strategy.state.is_active is True
    assert strategy._exit_pending is False


def test_track8_expiry_pair_close_callback_resets_only_after_confirmed_flat():
    strategy = Track8MacroRegimeMonthlyStrangle()
    strategy.state = Track8State(
        is_active=True, qty_call=1, qty_put=1,
        call_open=True, put_open=True,
        call_strike=Decimal("515"), put_strike=Decimal("485"),
    )
    strategy._exit_pending = True
    reports = tuple(
        SimpleNamespace(
            leg_id=leg, status="FILLED", filled_quantity=1, remaining_quantity=0,
            execution_id=f"S8-EXPIRY-{leg.upper()}",
            execution_timestamp=datetime(2026, 11, 19, 15, 10),
        )
        for leg in ("put", "call")
    )
    result = SimpleNamespace(reports=reports, position_flat=True, group_complete=True)

    strategy.on_execution_result("MONTHLY_STRANGLE_CLOSE", result)

    assert strategy.state == Track8State()
    assert strategy._exit_pending is False


def test_track8_analytics_snapshot_exposes_validation_only_option_marks():
    from datetime import date
    from application.composition.track8_analytics_provider import build_track8_analytics_snapshot

    data = SimpleNamespace(
        price=Decimal("500"), days_to_expiry=10, option_expiry=date(2026, 11, 19),
        option_iv=Decimal("0.25"), put_iv=Decimal("0.25"),
        call_strike=Decimal("515"), put_strike=Decimal("485"),
        call_contract_multiplier=Decimal("250000"), put_contract_multiplier=Decimal("250000"),
    )
    selection = SimpleNamespace(
        call=SimpleNamespace(strike=Decimal("515"), contract_multiplier=Decimal("250000")),
        put=SimpleNamespace(strike=Decimal("485"), contract_multiplier=Decimal("250000")),
    )
    snapshot = build_track8_analytics_snapshot(
        data, run_id="S8-MARK-TEST", as_of=datetime(2026, 11, 5, 9, 10),
        option_contract_selection=selection,
        option_mark_prices={"call": Decimal("0.40"), "put": Decimal("1.00")},
    )

    assert snapshot.get("options.track8_call_mark_price").value == Decimal("0.40")
    assert snapshot.get("options.track8_put_mark_price").value == Decimal("1.00")


def test_track8_expiry_cutoff_preempts_per_leg_stop_at_1510():
    strategy = Track8MacroRegimeMonthlyStrangle()
    strategy.state = Track8State(
        is_active=True, qty_call=1, qty_put=1, expiry="20261119",
        call_strike=Decimal("515"), put_strike=Decimal("485"),
        call_entry_fill_price=Decimal("1.0"), put_entry_fill_price=Decimal("1.0"),
        call_peak_mark=Decimal("1.0"), put_peak_mark=Decimal("1.0"),
        call_open=True, put_open=True,
    )
    values = {
        "options.track8_call_mark_price": Decimal("0.40"),
        "options.track8_put_mark_price": Decimal("1.00"),
    }
    context = SimpleNamespace(
        strategy_id=strategy.strategy_id,
        analytics=SimpleNamespace(
            as_of=datetime(2026, 11, 19, 15, 10, 0),
            get=lambda key: _metric(values.get(key)),
        ),
    )

    signals = strategy.evaluate(context)

    assert len(signals) == 1
    assert signals[0].reason == "MONTHLY_EXPIRY_15:10_FORCE_CLOSE"
    assert signals[0].execution_proposal.tag_id == "MONTHLY_STRANGLE_CLOSE"


def test_track8_rejected_single_leg_close_does_not_consume_prior_entry_fill_reports():
    strategy = Track8MacroRegimeMonthlyStrangle()
    strategy.state = Track8State(
        is_active=True, qty_call=1, qty_put=1,
        call_open=True, put_open=True,
    )
    strategy._exit_pending = True
    historical_call = SimpleNamespace(
        leg_id="call", status="FILLED", filled_quantity=1, remaining_quantity=0,
        execution_id="ENTRY-CALL", execution_timestamp=datetime(2026, 11, 5, 9, 0),
    )
    historical_put = SimpleNamespace(
        leg_id="put", status="FILLED", filled_quantity=1, remaining_quantity=0,
        execution_id="ENTRY-PUT", execution_timestamp=datetime(2026, 11, 5, 9, 0),
    )
    rejected_close = SimpleNamespace(
        leg_id="close-call", status="REJECTED", filled_quantity=0, remaining_quantity=1,
        execution_id=None, execution_timestamp=None,
    )
    result = SimpleNamespace(
        reports=(historical_call, historical_put, rejected_close),
        position_flat=False, group_complete=False,
    )

    strategy.on_execution_result("MONTHLY_STRANGLE_CLOSE_CALL", result)

    assert strategy.state.call_open is True
    assert strategy.state.put_open is True
    assert strategy._exit_pending is True


def test_track8_expiry_pair_close_requires_both_equal_quantities_fully_filled():
    strategy = Track8MacroRegimeMonthlyStrangle()
    strategy.state = Track8State(
        is_active=True, qty_call=2, qty_put=2,
        call_open=True, put_open=True,
        call_strike=Decimal("515"), put_strike=Decimal("485"),
    )
    strategy._exit_pending = True
    # The Virtual bridge returns canonical close reports in CALL, PUT order.
    reports = (
        SimpleNamespace(
            leg_id="close-call", status="FILLED", filled_quantity=2, remaining_quantity=0,
            execution_id="S8-EXPIRY-CALL", execution_timestamp=datetime(2026, 11, 19, 15, 10),
        ),
        SimpleNamespace(
            leg_id="close-put", status="FILLED", filled_quantity=2, remaining_quantity=0,
            execution_id="S8-EXPIRY-PUT", execution_timestamp=datetime(2026, 11, 19, 15, 10),
        ),
    )
    result = SimpleNamespace(reports=reports, position_flat=True, group_complete=True)

    strategy.on_execution_result("MONTHLY_STRANGLE_CLOSE", result)

    assert strategy.state == Track8State()
    assert strategy._exit_pending is False


def test_track8_expiry_pair_close_with_unequal_quantities_fails_closed():
    strategy = Track8MacroRegimeMonthlyStrangle()
    strategy.state = Track8State(
        is_active=True, qty_call=2, qty_put=3,
        call_open=True, put_open=True,
        call_strike=Decimal("515"), put_strike=Decimal("485"),
    )
    strategy._exit_pending = True
    reports = (
        SimpleNamespace(
            leg_id="close-call", status="FILLED", filled_quantity=2, remaining_quantity=0,
            execution_id="S8-EXPIRY-CALL", execution_timestamp=datetime(2026, 11, 19, 15, 10),
        ),
        SimpleNamespace(
            leg_id="close-put", status="FILLED", filled_quantity=3, remaining_quantity=0,
            execution_id="S8-EXPIRY-PUT", execution_timestamp=datetime(2026, 11, 19, 15, 10),
        ),
    )
    result = SimpleNamespace(reports=reports, position_flat=True, group_complete=True)

    strategy.on_execution_result("MONTHLY_STRANGLE_CLOSE", result)

    assert strategy.state.call_open is True
    assert strategy.state.put_open is True
    assert strategy._exit_pending is True
