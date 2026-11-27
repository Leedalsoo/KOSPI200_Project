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
import pytest

from application.composition.automated_virtual_runtime_factory import (
    _should_release_track7_validation_reservation,
)


@pytest.mark.parametrize(
    ("group_has_open_lots", "pending_legs", "expected"),
    [
        (False, 1, False),
        (False, 0, True),
        (True, 0, False),
        (True, 1, False),
    ],
)
def test_s7_validation_reservation_release_requires_no_open_lots_and_no_pending_orders(
    group_has_open_lots, pending_legs, expected
):
    result = SimpleNamespace(pending_legs=pending_legs)
    assert _should_release_track7_validation_reservation(
        result, group_has_open_lots=group_has_open_lots
    ) is expected
