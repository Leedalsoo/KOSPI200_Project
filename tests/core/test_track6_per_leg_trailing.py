from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from core.strategy.track6_daily_tail_insurance import (
    Track6DailyTailInsurance,
    Track6ExecutionInput,
    Track6OptionMark,
    Track6State,
)

KST = timezone(timedelta(hours=9))
PUT_ID = "SYNTHETIC_CONTRACT:SYNTH-S6-1-20261102-PUT-487.5"
CALL_ID = "SYNTHETIC_CONTRACT:SYNTH-S6-1-20261102-CALL-512.5"


def mark(instrument_id, option_type, strike, bid, as_of):
    return Track6OptionMark(
        instrument_id=instrument_id,
        option_type=option_type,
        strike=Decimal(str(strike)),
        expiry="20261102",
        bid_price=Decimal(str(bid)),
        ask_price=Decimal(str(bid)) + Decimal("0.02"),
        last_price=Decimal(str(bid)) + Decimal("0.01"),
        as_of=as_of,
        source="SYNTHETIC:DERIVED_SCENARIO",
        evidence_sha256="a" * 64,
    )


def context(as_of, marks):
    payload = Track6ExecutionInput(
        strategy_id="track6_daily_tail_insurance",
        date_str="20261102",
        time_str=as_of.strftime("%H:%M:%S"),
        listed_put_strike=Decimal("487.5"),
        listed_call_strike=Decimal("512.5"),
        contract_multiplier=Decimal("250000"),
        listed_put_instrument_id=PUT_ID,
        listed_call_instrument_id=CALL_ID,
        expiry="20261102",
        option_marks=tuple(marks),
    )
    return SimpleNamespace(analytics=SimpleNamespace(as_of=as_of), input=SimpleNamespace(payload=payload))


def active_strategy():
    strategy = Track6DailyTailInsurance(runtime_config_verified=True, risk_limits_available=True)
    strategy.state = Track6State(
        is_active=True,
        bought_date="20261102",
        long_put_strike=Decimal("487.5"),
        long_call_strike=Decimal("512.5"),
        put_instrument_id=PUT_ID,
        call_instrument_id=CALL_ID,
        put_entry_fill_price=Decimal("1.0"),
        call_entry_fill_price=Decimal("1.0"),
        put_open=True,
        call_open=True,
    )
    return strategy


def test_per_leg_trailing_uses_fill_price_and_executable_bid_only():
    strategy = active_strategy()
    t1 = datetime(2026, 11, 2, 10, 0, tzinfo=KST)
    assert strategy.evaluate_take_profit(context(t1, [
        mark(PUT_ID, "PUT", "487.5", "2.0", t1),
        mark(CALL_ID, "CALL", "512.5", "1.5", t1),
    ])) == ()
    assert strategy.state.put_trailing_active is True
    assert strategy.state.put_high_watermark == Decimal("2.0")
    assert strategy.state.call_trailing_active is False

    t2 = t1 + timedelta(seconds=1)
    assert strategy.evaluate_take_profit(context(t2, [
        mark(PUT_ID, "PUT", "487.5", "2.5", t2),
        mark(CALL_ID, "CALL", "512.5", "1.6", t2),
    ])) == ()
    assert strategy.state.put_high_watermark == Decimal("2.5")

    t3 = t2 + timedelta(seconds=1)
    signals = strategy.evaluate_take_profit(context(t3, [
        mark(PUT_ID, "PUT", "487.5", "2.25", t3),
        mark(CALL_ID, "CALL", "512.5", "1.6", t3),
    ]))
    assert len(signals) == 1
    proposal = signals[0].execution_proposal
    assert proposal.tag_id == "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_PUT"
    assert proposal.option_type == "PUT"
    assert proposal.strike == Decimal("487.5")
    assert strategy.state.put_exit_pending is True

    strategy.on_execution_result(
        proposal.tag_id, SimpleNamespace(group_complete=True, position_flat=True, reports=())
    )
    assert strategy.state.is_active is True
    assert strategy.state.put_open is False
    assert strategy.state.call_open is True

    t4 = t3 + timedelta(seconds=1)
    assert strategy.evaluate_take_profit(context(t4, [mark(CALL_ID, "CALL", "512.5", "2.0", t4)])) == ()
    assert strategy.state.call_trailing_active is True
    t5 = t4 + timedelta(seconds=1)
    signals = strategy.evaluate_take_profit(context(t5, [mark(CALL_ID, "CALL", "512.5", "1.8", t5)]))
    assert len(signals) == 1
    assert signals[0].execution_proposal.tag_id == "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_CALL"
    strategy.on_execution_result(
        signals[0].execution_proposal.tag_id,
        SimpleNamespace(group_complete=True, position_flat=True, reports=()),
    )
    assert strategy.state.is_active is False


def test_missing_or_future_option_mark_never_triggers_trailing():
    strategy = active_strategy()
    t = datetime(2026, 11, 2, 10, 0, tzinfo=KST)
    future = t + timedelta(seconds=1)
    signals = strategy.evaluate_take_profit(context(t, [
        mark(PUT_ID, "PUT", "487.5", "3.0", future),
    ]))
    assert signals == ()
    assert strategy.state.put_trailing_active is False


def test_1510_force_close_waits_for_fresh_marks_for_each_open_leg():
    strategy = active_strategy()
    t = datetime(2026, 11, 2, 15, 10, tzinfo=KST)
    assert strategy.evaluate_expiry_cutoff(context(t, [])) == ()
    assert strategy.state.force_close_pending is False
    signals = strategy.evaluate_expiry_cutoff(context(t, [
        mark(PUT_ID, "PUT", "487.5", "0.5", t),
        mark(CALL_ID, "CALL", "512.5", "0.6", t),
    ]))
    assert len(signals) == 1
    assert signals[0].execution_proposal.tag_id == "DAILY_TAIL_INSURANCE_FORCE_CLOSE"
    assert strategy.state.force_close_pending is True


def test_entry_execution_plan_carries_selected_option_master_identities():
    from contracts.types import OptionInstrumentIdentity

    strategy = Track6DailyTailInsurance()
    put = OptionInstrumentIdentity(PUT_ID, PUT_ID, "20261102", "PUT", Decimal("487.5"), Decimal("250000"), "OPTION_MASTER")
    call = OptionInstrumentIdentity(CALL_ID, CALL_ID, "20261102", "CALL", Decimal("512.5"), Decimal("250000"), "OPTION_MASTER")
    strategy.state = Track6State(
        entry_pending=True, long_put_strike=Decimal("487.5"), long_call_strike=Decimal("512.5"),
        put_instrument_identity=put, call_instrument_identity=call,
    )
    plan = strategy.build_execution_plan("s6-group")
    assert plan is not None
    assert {leg.instrument_identity.instrument_id for leg in plan.legs} == {PUT_ID, CALL_ID}



def test_no_retry_after_both_legs_exit_on_same_trading_date():
    strategy = active_strategy()
    strategy.state = __import__("dataclasses").replace(
        strategy.state, bought_date="20261102", force_close_pending=True,
        put_exit_pending=True, call_exit_pending=True,
    )
    strategy.on_execution_result(
        "DAILY_TAIL_INSURANCE_FORCE_CLOSE",
        SimpleNamespace(group_complete=True, position_flat=True, reports=()),
    )
    assert strategy.state.is_active is False
    assert strategy.state.bought_date == "20261102"
    t = datetime(2026, 11, 2, 10, 30, tzinfo=KST)
    ctx = context(t, [
        mark(PUT_ID, "PUT", "487.5", "0.8", t),
        mark(CALL_ID, "CALL", "512.5", "0.9", t),
    ])
    # Force an otherwise valid volatility snapshot and contract input.
    ctx.analytics.get = lambda key: SimpleNamespace(status=SimpleNamespace(name="AVAILABLE"), value=Decimal("1.5"))
    strategy.runtime_config_verified = True
    strategy.risk_limits_available = True
    assert strategy.evaluate_buy(ctx) == ()



def test_s6_entry_is_blocked_before_regular_session_open():
    strategy = Track6DailyTailInsurance(runtime_config_verified=True, risk_limits_available=True)
    t = datetime(2026, 11, 2, 8, 59, 59, tzinfo=KST)
    ctx = context(t, [
        mark(PUT_ID, "PUT", "487.5", "1.0", t),
        mark(CALL_ID, "CALL", "512.5", "1.0", t),
    ])
    assert strategy.evaluate_buy(ctx) == ()
    assert strategy.state.entry_pending is False
