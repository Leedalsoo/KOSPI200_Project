from datetime import datetime
from decimal import Decimal

from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap


def test_track2_does_not_use_underlying_price_as_option_group_pnl():
    strategy = Track2AsymmetricTrap()
    strategy._trap_active = True
    strategy._entry_price = Decimal("100")
    strategy._entry_strike = Decimal("100")

    # A 50% move in the underlying would have triggered the legacy proxy stop.
    # It must not be treated as the option group's P&L without authoritative fills/marks.
    assert strategy.evaluate_trap(
        Decimal("50"), datetime(2026, 10, 22, 10, 0)
    ) == ()
