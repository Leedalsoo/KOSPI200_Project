from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


def _s7_proposal(tag_id: str, option_type: str, strike: str):
    return StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", side="BUY",
        track_id="track7_volatility_skew_weekly_insurance",
        tag_id=tag_id, option_type=option_type, strike=Decimal(strike),
    )


def _s7_fill(leg_id: str, price: str, *, status="FILLED", filled=1, remaining=0):
    return SimpleNamespace(
        leg_id=leg_id, status=status, filled_quantity=filled,
        remaining_quantity=remaining, execution_id=f"exec-{leg_id}" if status == "FILLED" else None,
        execution_timestamp=datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc),
        execution_price=Decimal(price) if status == "FILLED" else None,
        rejected_reason="TIMEOUT_10M" if status == "CANCELLED" else None,
    )


def test_s7_sequential_put_then_call_reuses_one_expiry_group():
    strategy = Track7VolatilitySkewWeeklyInsurance(runtime_config_verified=True, risk_limits_available=True)
    strategy._activate_expiry("20261109")
    strategy.state = strategy.state.__class__(
        entry_pending=True, expiry="20261109", put_strike=Decimal("487.5"),
        call_strike=Decimal("512.5"), contract_multiplier=Decimal("250000"),
        entry_stage="PUT_READY",
    )

    put_plan = strategy.build_execution_plan("generated-put-group", proposal=_s7_proposal(
        "WEEKLY_INSURANCE_ENTRY_PUT", "PUT", "487.5"))
    assert put_plan.purpose == "WEEKLY_INSURANCE_ENTRY_PUT"
    assert put_plan.group_id == "generated-put-group"
    assert [(leg.leg_id, leg.option_type) for leg in put_plan.legs] == [("put", "PUT")]

    strategy.on_execution_result("WEEKLY_INSURANCE_ENTRY_PUT", SimpleNamespace(
        group_id=put_plan.group_id, reports=(_s7_fill("put", "1.26"),),
        group_complete=True, position_flat=False,
    ))
    assert strategy.state.entry_stage == "CALL_READY"
    assert strategy.state.put_open is True

    call_plan = strategy.build_execution_plan("different-generated-call-group", proposal=_s7_proposal(
        "WEEKLY_INSURANCE_ENTRY_CALL", "CALL", "512.5"))
    assert call_plan.purpose == "WEEKLY_INSURANCE_ENTRY_CALL"
    assert call_plan.group_id == put_plan.group_id
    assert [(leg.leg_id, leg.option_type) for leg in call_plan.legs] == [("call", "CALL")]

    strategy.on_execution_result("WEEKLY_INSURANCE_ENTRY_CALL", SimpleNamespace(
        group_id=call_plan.group_id, reports=(_s7_fill("call", "1.16"),),
        group_complete=True, position_flat=False,
    ))
    assert strategy.state.entry_stage == "COMPLETE"
    assert strategy.state.entry_pending is False
    assert strategy.state.insurance_active is True
    assert strategy.state.put_open is True
    assert strategy.state.call_open is True


def test_s7_opposite_leg_terminal_timeout_blocks_without_retry_or_compensating_order():
    strategy = Track7VolatilitySkewWeeklyInsurance(runtime_config_verified=True, risk_limits_available=True)
    strategy._activate_expiry("20261109")
    strategy.state = strategy.state.__class__(
        entry_pending=True, expiry="20261109", put_strike=Decimal("487.5"),
        call_strike=Decimal("512.5"), contract_multiplier=Decimal("250000"),
        entry_stage="PUT_READY",
    )
    put_plan = strategy.build_execution_plan("group-timeout", proposal=_s7_proposal(
        "WEEKLY_INSURANCE_ENTRY_PUT", "PUT", "487.5"))
    strategy.on_execution_result("WEEKLY_INSURANCE_ENTRY_PUT", SimpleNamespace(
        group_id=put_plan.group_id, reports=(_s7_fill("put", "1.26"),),
        group_complete=True, position_flat=False,
    ))
    call_plan = strategy.build_execution_plan("another-group", proposal=_s7_proposal(
        "WEEKLY_INSURANCE_ENTRY_CALL", "CALL", "512.5"))
    strategy.on_execution_result("WEEKLY_INSURANCE_ENTRY_CALL", SimpleNamespace(
        group_id=call_plan.group_id, reports=(_s7_fill("call", "0", status="CANCELLED", filled=0, remaining=1),),
        group_complete=False, position_flat=False,
    ))

    assert strategy.state.entry_stage == "BLOCKED_U16"
    assert strategy.state.entry_pending is True
    assert strategy.state.put_open is True
    assert strategy.state.insurance_active is False
    assert strategy._call_entry_signal(datetime(2026, 11, 2, 10, 20)) == ()


def test_s7_call_followup_after_1500_is_blocked_pending_u17_decision():
    strategy = Track7VolatilitySkewWeeklyInsurance(runtime_config_verified=True, risk_limits_available=True)
    strategy._activate_expiry("20261112")
    strategy.state = strategy.state.__class__(
        entry_pending=True, expiry="20261112", put_strike=Decimal("487.5"),
        call_strike=Decimal("512.5"), contract_multiplier=Decimal("250000"),
        put_open=True, put_entry_fill_price=Decimal("2.42"),
        put_entry_filled_at=datetime(2026, 11, 5, 5, 40, tzinfo=timezone.utc),
        entry_stage="CALL_READY", entry_group_id="group-thu",
    )

    assert strategy._call_entry_signal(datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)) == ()
    assert strategy.state.entry_stage == "BLOCKED_U17"
    assert strategy.state.entry_pending is True
    assert strategy.state.put_open is True


def _s7_pending_call(client_order_id: str, submitted_at: datetime):
    return SimpleNamespace(
        leg_id="call", status="PENDING", filled_quantity=0, remaining_quantity=1,
        client_order_id=client_order_id, submitted_at=submitted_at,
    )


def test_s7_u16_call_timeout_cancels_and_keeps_put_single_leg():
    from datetime import timezone

    strategy = Track7VolatilitySkewWeeklyInsurance(runtime_config_verified=True, risk_limits_available=True)
    strategy._activate_expiry("20261109")
    strategy.state = strategy.state.__class__(
        entry_pending=True, expiry="20261109", put_open=True,
        put_entry_fill_price=Decimal("1.26"), entry_stage="CALL_PENDING",
        entry_group_id="group-u16",
    )
    strategy._group_expiry["group-u16"] = "20261109"
    put_filled_at = datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc)  # 14:00 KST
    strategy.state = strategy.state.__class__(**{
        **strategy.state.__dict__, "put_entry_filled_at": put_filled_at,
    })
    submitted = datetime(2026, 11, 2, 5, 5, tzinfo=timezone.utc)  # 14:05 KST
    strategy.on_execution_result("WEEKLY_INSURANCE_ENTRY_CALL", SimpleNamespace(
        group_id="group-u16", reports=(_s7_pending_call("call-u16", submitted),),
        group_complete=False, position_flat=False,
    ))

    assert strategy.lifecycle_clock_action(datetime(2026, 11, 2, 5, 9, 59, tzinfo=timezone.utc)) is None
    action = strategy.lifecycle_clock_action(datetime(2026, 11, 2, 5, 10, tzinfo=timezone.utc))
    assert action.kind == "CANCEL_AND_RECONCILE"
    assert action.client_order_id == "call-u16"
    assert action.reason == "TIMEOUT_10M"

    strategy.on_execution_result("WEEKLY_INSURANCE_ENTRY_CALL", SimpleNamespace(
        group_id="group-u16",
        reports=(SimpleNamespace(
            leg_id="call", status="CANCELLED", filled_quantity=0, remaining_quantity=1,
            execution_id=None, execution_timestamp=None, execution_price=None,
            rejected_reason="TIMEOUT_10M", client_order_id="call-u16",
        ),),
        group_complete=False, position_flat=False,
    ))
    assert strategy.state.entry_stage == "BLOCKED_U16"
    assert strategy.state.put_open is True
    assert strategy.state.call_open is False
    assert strategy.state.entry_pending is True
    assert strategy._call_entry_signal(datetime(2026, 11, 2, 5, 11, tzinfo=timezone.utc)) == ()


def test_s7_u17_1500_cutoff_cancels_then_reconciles_final_fill_state():
    from datetime import timezone

    strategy = Track7VolatilitySkewWeeklyInsurance(runtime_config_verified=True, risk_limits_available=True)
    strategy._activate_expiry("20261112")
    strategy.state = strategy.state.__class__(
        entry_pending=True, expiry="20261112", put_open=True,
        put_entry_fill_price=Decimal("2.42"), entry_stage="CALL_PENDING",
        entry_group_id="group-u17",
    )
    strategy._group_expiry["group-u17"] = "20261112"
    put_filled_at = datetime(2026, 11, 5, 5, 40, tzinfo=timezone.utc)  # 14:40 KST
    strategy.state = strategy.state.__class__(**{
        **strategy.state.__dict__, "put_entry_filled_at": put_filled_at,
    })
    submitted = datetime(2026, 11, 5, 5, 59, tzinfo=timezone.utc)  # 14:59 KST
    strategy.on_execution_result("WEEKLY_INSURANCE_ENTRY_CALL", SimpleNamespace(
        group_id="group-u17", reports=(_s7_pending_call("call-u17", submitted),),
        group_complete=False, position_flat=False,
    ))

    action = strategy.lifecycle_clock_action(datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc))
    assert action.kind == "CANCEL_AND_RECONCILE"
    assert action.client_order_id == "call-u17"
    assert action.reason == "15:00_CUTOFF"

    strategy.on_execution_result("WEEKLY_INSURANCE_ENTRY_CALL", SimpleNamespace(
        group_id="group-u17",
        reports=(SimpleNamespace(
            leg_id="call", status="CANCELLED", filled_quantity=0, remaining_quantity=1,
            execution_id=None, execution_timestamp=None, execution_price=None,
            rejected_reason="CANCELLED_AT_CUTOFF", client_order_id="call-u17",
        ),),
        group_complete=False, position_flat=False,
    ))
    assert strategy.state.entry_stage == "BLOCKED_U17"
    assert strategy.state.put_open is True
    assert strategy.state.call_open is False
    assert strategy.state.entry_pending is True




def test_s7_u16_blocks_call_signal_when_ten_minutes_elapsed_before_submission():
    from datetime import timezone

    strategy = Track7VolatilitySkewWeeklyInsurance(runtime_config_verified=True, risk_limits_available=True)
    strategy._activate_expiry("20261109")
    strategy.state = strategy.state.__class__(
        entry_pending=True, expiry="20261109", put_open=True,
        put_strike=Decimal("487.5"), call_strike=Decimal("512.5"),
        put_entry_fill_price=Decimal("1.26"),
        put_entry_filled_at=datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc),
        entry_stage="CALL_READY", entry_group_id="group-u16-delayed",
    )
    strategy._group_expiry["group-u16-delayed"] = "20261109"

    assert strategy._call_entry_signal(datetime(2026, 11, 2, 5, 9, 59, tzinfo=timezone.utc))
    assert strategy.state.entry_stage == "CALL_READY"
    assert strategy._call_entry_signal(datetime(2026, 11, 2, 5, 10, tzinfo=timezone.utc)) == ()
    assert strategy.state.entry_stage == "BLOCKED_U16"
    assert strategy.state.put_open is True
    assert strategy.state.entry_pending is True
