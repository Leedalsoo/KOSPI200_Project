"""Common option strike rounding rules.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


STRIKE_TICK = Decimal("2.5")


def round_to_strike_tick(price: Decimal | float | int) -> Decimal:
    value = Decimal(str(price))
    return (value / STRIKE_TICK).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * STRIKE_TICK
