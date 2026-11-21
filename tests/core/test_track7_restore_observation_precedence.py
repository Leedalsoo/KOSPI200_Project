from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance


def _pending_call_strategy():
    strategy = Track7VolatilitySkewWeeklyInsurance(
        runtime_config_verified=True,
        risk_limits_available=True,
    )
    expiry = "20261127"
    group_id = "SYNTHETIC-TRACK7-RESTORE-OBSERVATION-GROUP"
    strategy._activate_expiry(expiry)
    strategy._bind_group(group_id)
    strategy.state = replace(
        strategy.state,
        entry_pending=True,
        expiry=expiry,
        put_strike=Decimal("487.5"),
        call_strike=Decimal("512.5"),
        contract_multiplier=Decimal("250000"),
        put_open=True,
        put_entry_fill_price=Decimal("2.10"),
        put_entry_filled_at=datetime(2026, 11, 21, 5, 0, tzinfo=timezone.utc),
        entry_stage="CALL_PENDING",
        entry_group_id=group_id,
        call_client_order_id="SYNTHETIC-CALL-ORDER-1",
        call_submitted_at=datetime(2026, 11, 21, 5, 1, tzinfo=timezone.utc),
    )
    report = SimpleNamespace(
        leg_id="call",
        status="FILLED",
        filled_quantity=1,
        remaining_quantity=0,
        execution_id="SYNTHETIC-EXEC-CALL-1",
        execution_timestamp=datetime(2026, 11, 21, 5, 2, tzinfo=timezone.utc),
        execution_price=Decimal("1.75"),
    )
    result = SimpleNamespace(
        group_id=group_id,
        reports=(report,),
        group_complete=True,
        position_flat=False,
    )
    return strategy, result


def test_track7_fresh_pending_fill_observation_must_not_be_overwritten_by_stale_restore():
    restore_first, result_after_restore = _pending_call_strategy()
    stale_snapshot = restore_first.state
    restore_first.state = stale_snapshot
    restore_first.on_execution_result("WEEKLY_INSURANCE_ENTRY_CALL", result_after_restore)
    assert restore_first.state.entry_stage == "COMPLETE"
    assert restore_first.state.call_open is True

    observe_first, result_before_restore = _pending_call_strategy()
    stale_snapshot = observe_first.state
    observe_first.on_execution_result("WEEKLY_INSURANCE_ENTRY_CALL", result_before_restore)
    assert observe_first.state.entry_stage == "COMPLETE"
    observe_first.state = stale_snapshot  # test-only stale aggregate restore simulation
    assert observe_first.state.entry_stage == "CALL_PENDING"
    assert observe_first.state.call_open is False
    assert observe_first.state.call_client_order_id == "SYNTHETIC-CALL-ORDER-1"