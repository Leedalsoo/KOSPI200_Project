from decimal import Decimal

from core.risk.delta_hedge_quantity import delta_to_mini_futures_qty


def test_delta_to_mini_futures_qty_uses_ceil_abs_delta_times_five() -> None:
    assert delta_to_mini_futures_qty(Decimal("0.01")) == 1
    assert delta_to_mini_futures_qty(Decimal("0.2")) == 1
    assert delta_to_mini_futures_qty(Decimal("0.21")) == 2
    assert delta_to_mini_futures_qty(Decimal("-0.21")) == 2


def test_delta_to_mini_futures_qty_rejects_invalid_multiplier() -> None:
    try:
        delta_to_mini_futures_qty(Decimal("0.2"), Decimal("0"))
    except ValueError as exc:
        assert str(exc) == "CONTRACT_MULTIPLIER_MUST_BE_POSITIVE"
    else:
        raise AssertionError("expected ValueError")

# Consolidated from tests\unit\test_track1_track4_delta_hedge_domain.py; retained because it covers the same production boundary.

from decimal import Decimal

from core.risk.delta_hedge_quantity import delta_to_mini_futures_qty


def test_track1_domain_quantity_is_shared_common_rule() -> None:
    assert delta_to_mini_futures_qty(Decimal("1.01")) == 6


def test_track4_domain_quantity_is_shared_common_rule() -> None:
    assert delta_to_mini_futures_qty(Decimal("-1.01")) == 6
