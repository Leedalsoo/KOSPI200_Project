from types import SimpleNamespace

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge


def test_s6_per_leg_and_force_close_plans_use_terminal_position_group_reconciliation():
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    for purpose in (
        "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_PUT",
        "DAILY_TAIL_INSURANCE_TRAILING_CLOSE_CALL",
        "DAILY_TAIL_INSURANCE_FORCE_CLOSE",
    ):
        assert bridge._is_terminal_execution_plan(SimpleNamespace(
            strategy_id="track6_daily_tail_insurance", purpose=purpose,
        )) is True
    assert bridge._is_terminal_execution_plan(SimpleNamespace(
        strategy_id="track6_daily_tail_insurance", purpose="DAILY_TAIL_INSURANCE_ENTRY",
    )) is False
