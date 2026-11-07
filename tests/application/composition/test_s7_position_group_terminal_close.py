from types import SimpleNamespace

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge


def test_s7_single_leg_close_uses_terminal_group_snapshot_path():
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    for purpose in ("WEEKLY_INSURANCE_CLOSE_PUT", "WEEKLY_INSURANCE_CLOSE_CALL"):
        plan = SimpleNamespace(
            strategy_id="track7_volatility_skew_weekly_insurance",
            purpose=purpose,
        )
        assert bridge._is_terminal_execution_plan(plan) is True


def test_s7_entry_is_not_a_terminal_execution_plan():
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    plan = SimpleNamespace(
        strategy_id="track7_volatility_skew_weekly_insurance",
        purpose="WEEKLY_INSURANCE_ENTRY",
    )
    assert bridge._is_terminal_execution_plan(plan) is False
