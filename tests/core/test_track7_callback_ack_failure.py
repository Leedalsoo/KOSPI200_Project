from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.strategy_hub.hub import StrategyHub
from core.strategy.registry import StrategyRegistry
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance


def test_track7_put_fill_replay_after_callback_ack_failure_reblocks_committed_state():
    strategy = Track7VolatilitySkewWeeklyInsurance(
        runtime_config_verified=True,
        risk_limits_available=True,
    )
    expiry = "20261109"
    group_id = "SYNTHETIC-TRACK7-CALLBACK-ACK-LOSS"
    strategy._activate_expiry(expiry)
    strategy.state = strategy.state.__class__(
        entry_pending=True,
        expiry=expiry,
        put_strike=Decimal("487.5"),
        call_strike=Decimal("512.5"),
        contract_multiplier=Decimal("250000"),
        entry_stage="PUT_READY",
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="OPTION",
        side="BUY",
        track_id="track7_volatility_skew_weekly_insurance",
        tag_id="WEEKLY_INSURANCE_ENTRY_PUT",
        option_type="PUT",
        strike=Decimal("487.5"),
    )
    plan = strategy.build_execution_plan(group_id, proposal=proposal)
    result = SimpleNamespace(
        group_id=plan.group_id,
        reports=(SimpleNamespace(
            leg_id="put",
            status="FILLED",
            filled_quantity=1,
            remaining_quantity=0,
            execution_id="SYNTHETIC-EXEC-PUT-ACK-LOSS",
            execution_timestamp=datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc),
            execution_price=Decimal("1.26"),
        ),),
        group_complete=True,
        position_flat=False,
    )
    registry = StrategyRegistry()
    registry.register(strategy)
    hub = StrategyHub(registry, ((strategy.strategy_id, strategy.version),))
    original_callback = hub.on_execution_result
    attempts = 0

    def callback_with_lost_ack(strategy_id, purpose, event):
        nonlocal attempts
        original_callback(strategy_id, purpose, event)
        attempts += 1
        if attempts == 1:
            raise RuntimeError("SYNTHETIC_CALLBACK_ACK_LOST_AFTER_STATE_MUTATION")

    with pytest.raises(RuntimeError, match="SYNTHETIC_CALLBACK_ACK_LOST_AFTER_STATE_MUTATION"):
        callback_with_lost_ack(
            strategy.strategy_id,
            "WEEKLY_INSURANCE_ENTRY_PUT",
            result,
        )

    # The strategy transition committed even though the caller saw an exception.
    assert strategy.state.entry_stage == "CALL_READY"
    assert strategy.state.put_open is True

    # A caller retrying the same callback is not idempotent in the current code.
    original_callback(strategy.strategy_id, "WEEKLY_INSURANCE_ENTRY_PUT", result)
    assert strategy.state.entry_stage == "BLOCKED"
    assert strategy.state.entry_block_reason == "TRACK7_PUT_FILL_STAGE_MISMATCH"
    assert strategy.state.put_open is True
