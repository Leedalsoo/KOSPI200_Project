from types import SimpleNamespace

import pytest

from application.composition.automated_virtual_runtime_factory import (
    _should_release_validation_reservation_after_terminal_result,
)


@pytest.mark.parametrize(
    ("position_flat", "pending_legs", "expected"),
    [
        (True, 1, False),
        (True, 0, True),
        (False, 0, False),
        (False, 1, False),
    ],
)
def test_s8_s9_validation_reservation_waits_for_pending_orders(
    position_flat, pending_legs, expected
):
    result = SimpleNamespace(
        position_flat=position_flat,
        pending_legs=pending_legs,
    )
    assert _should_release_validation_reservation_after_terminal_result(result) is expected
