from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from core.strategy.contracts import AnalyticsStatus
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle
from environments.high_speed.validation_only_trading_calendar import ValidationOnlyTradingCalendar
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge


def _metric(value):
    return SimpleNamespace(status=AnalyticsStatus.AVAILABLE, value=value)


def _context(as_of):
    values = {
        "options.dte": Decimal("10"),
        "market.current_regime": "NORMAL",
        "options.call_strike": Decimal("515"),
        "options.put_strike": Decimal("485"),
        "options.call_contract_multiplier": Decimal("250000"),
        "options.put_contract_multiplier": Decimal("250000"),
        "options.expiry_date": "20261119",
    }
    return SimpleNamespace(
        strategy_id="track8_macro_regime_monthly_strangle",
        analytics=SimpleNamespace(as_of=as_of, get=lambda key: _metric(values.get(key))),
        input=SimpleNamespace(common=SimpleNamespace(date_str=as_of.strftime("%Y%m%d"))),
    )


def _calendar():
    return ValidationOnlyTradingCalendar(
        scenario_id="S8-RETRY-TEST",
        calendar_id="S8-RETRY-CALENDAR",
        trading_days=tuple(date(2026, 11, day) for day in (3, 4, 5, 6, 9)),
    )


def _start():
    strategy = Track8MacroRegimeMonthlyStrangle(
        runtime_config_verified=True, risk_limits_available=True
    )
    strategy.retry_calendar = _calendar()
    signal = strategy.evaluate_entry(_context(datetime(2026, 11, 3, 9, 0)))[0]
    plan = strategy.build_execution_plan("S8-GROUP", proposal=signal.execution_proposal)
    return strategy, plan


def _cancel_result(plan, *, submitted_at, observed_at, filled=0, remaining=1, reason="TIMEOUT_10M", leg_id="call", price=None):
    report = SimpleNamespace(
        leg_id=leg_id,
        status="CANCELLED",
        filled_quantity=filled,
        remaining_quantity=remaining,
        execution_price=Decimal(str(price)) if price is not None else None,
        execution_timestamp=observed_at,
        submitted_at=submitted_at,
        lifecycle_reason=reason,
        rejected_reason=None,
    )
    return SimpleNamespace(group_id=plan.group_id, reports=(report,), group_complete=False)


def test_timeout_zero_fill_waits_10m_then_retries_with_new_client_order_id():
    strategy, initial_plan = _start()
    submitted = datetime(2026, 11, 3, 9, 0)
    timed_out = datetime(2026, 11, 3, 9, 10)
    strategy.on_execution_result(
        initial_plan.purpose,
        _cancel_result(initial_plan, submitted_at=submitted, observed_at=timed_out),
    )
    assert strategy.state.entry_stage == "RETRY_WAIT"

    retry_signals = strategy.evaluate(_context(timed_out))
    assert len(retry_signals) == 1
    assert strategy.state.entry_stage == "CALL_RETRY_READY"
    retry_plan = strategy.build_execution_plan(
        "new-signal-id", proposal=retry_signals[0].execution_proposal
    )
    assert retry_plan.group_id == initial_plan.group_id
    assert retry_plan.attempt_id == "CALL-RETRY-1"

    leg = SimpleNamespace(leg_id="call", side="BUY", quantity=1, position_role="OPEN")
    identity = SimpleNamespace(instrument_id="SYNTHETIC-CALL")
    initial_id = VirtualMultiLegExecutionBridge._client_order_id(initial_plan, leg, identity)
    retry_id = VirtualMultiLegExecutionBridge._client_order_id(retry_plan, leg, identity)
    assert retry_id != initial_id
    assert strategy.state.call_retry_count == 1


def test_timeout_partial_fill_blocks_retry():
    strategy, plan = _start()
    strategy.state = strategy.state.__class__(**{
        **strategy.state.__dict__,
        "qty_call": 2,
    })
    strategy.on_execution_result(
        plan.purpose,
        _cancel_result(
            plan,
            submitted_at=datetime(2026, 11, 3, 9, 0),
            observed_at=datetime(2026, 11, 3, 9, 10),
            filled=1,
            remaining=1,
            price="1.25",
        ),
    )
    assert strategy.state.entry_stage == "BLOCKED"
    assert strategy.state.entry_block_reason == "TRACK8_CALL_PARTIAL_FILL_REQUIRES_RECONCILIATION"
    assert strategy.state.call_open is True
    assert strategy.state.qty_call == 1
    assert strategy.state.is_active is True
    assert strategy.state.entry_pending is False
    assert strategy.evaluate(_context(datetime(2026, 11, 3, 9, 20))) == ()


def test_manual_cancel_is_not_retryable():
    strategy, plan = _start()
    strategy.on_execution_result(
        plan.purpose,
        _cancel_result(
            plan,
            submitted_at=datetime(2026, 11, 3, 9, 0),
            observed_at=datetime(2026, 11, 3, 9, 10),
            reason="MANUAL",
        ),
    )
    assert strategy.state.entry_stage == "BLOCKED"
    assert "CANCEL_NOT_RETRYABLE" in strategy.state.entry_block_reason


def test_retry_is_blocked_at_third_trading_day_1500_kst():
    strategy, plan = _start()
    strategy.on_execution_result(
        plan.purpose,
        _cancel_result(
            plan,
            submitted_at=datetime(2026, 11, 3, 9, 0),
            observed_at=datetime(2026, 11, 5, 15, 0),
        ),
    )
    assert strategy.state.entry_stage == "BLOCKED"
    assert strategy.state.entry_block_reason == "TRACK8_RETRY_WINDOW_CLOSED_OR_UNVERIFIED"


def test_retry_limit_is_three_retries_after_initial_order():
    strategy, plan = _start()
    strategy.state = strategy.state.__class__(**{
        **strategy.state.__dict__,
        "call_retry_count": 3,
    })
    strategy.on_execution_result(
        plan.purpose,
        _cancel_result(
            plan,
            submitted_at=datetime(2026, 11, 3, 9, 0),
            observed_at=datetime(2026, 11, 3, 9, 10),
        ),
    )
    assert strategy.state.entry_stage == "BLOCKED"
    assert strategy.state.entry_block_reason == "TRACK8_CALL_RETRY_LIMIT_REACHED"


def test_put_leg_uses_same_retry_policy_after_call_is_filled():
    strategy, call_plan = _start()
    call_report = SimpleNamespace(
        leg_id="call",
        status="FILLED",
        filled_quantity=1,
        remaining_quantity=0,
        execution_price=Decimal("1.30"),
        execution_timestamp=datetime(2026, 11, 3, 9, 0),
        submitted_at=datetime(2026, 11, 3, 9, 0),
        lifecycle_reason=None,
        rejected_reason=None,
    )
    strategy.on_execution_result(
        call_plan.purpose,
        SimpleNamespace(group_id=call_plan.group_id, reports=(call_report,), group_complete=True),
    )
    put_signal = strategy.evaluate(_context(datetime(2026, 11, 3, 9, 0)))[0]
    put_plan = strategy.build_execution_plan(
        "put-signal", proposal=put_signal.execution_proposal
    )
    strategy.on_execution_result(
        put_plan.purpose,
        _cancel_result(
            put_plan,
            submitted_at=datetime(2026, 11, 3, 9, 1),
            observed_at=datetime(2026, 11, 3, 9, 11),
            leg_id="put",
        ),
    )
    assert strategy.state.entry_stage == "RETRY_WAIT"
    assert strategy.state.retry_leg == "put"

    retry_signal = strategy.evaluate(_context(datetime(2026, 11, 3, 9, 11)))[0]
    retry_plan = strategy.build_execution_plan(
        "put-retry-signal", proposal=retry_signal.execution_proposal
    )
    assert retry_plan.group_id == call_plan.group_id
    assert retry_plan.attempt_id == "PUT-RETRY-1"
    assert strategy.state.put_retry_count == 1
