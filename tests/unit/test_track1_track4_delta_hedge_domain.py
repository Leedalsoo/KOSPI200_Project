from decimal import Decimal

from core.risk.delta_hedge_quantity import delta_to_mini_futures_qty


def test_track1_domain_quantity_is_shared_common_rule() -> None:
    assert delta_to_mini_futures_qty(Decimal("1.01")) == 6


def test_track4_domain_quantity_is_shared_common_rule() -> None:
    assert delta_to_mini_futures_qty(Decimal("-1.01")) == 6
