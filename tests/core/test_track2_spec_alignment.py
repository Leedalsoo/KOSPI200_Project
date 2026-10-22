from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap


def test_track2_short_switch_timeout_is_retired() -> None:
    strategy = Track2AsymmetricTrap()
    now = datetime(2026, 10, 21, 14, 0)
    strategy._trap_active = True
    strategy._entry_price = Decimal("100")
    strategy._entry_strike = Decimal("100")
    strategy._short_switch_at = now - strategy.COOLDOWN - timedelta(seconds=1)
    strategy._short_switched = True

    signals = strategy.evaluate_trap(Decimal("110"), now)

    assert signals == ()


def test_track2_structure_does_not_claim_zero_cost_or_resolved_pricing() -> None:
    strategy = Track2AsymmetricTrap()

    trap = strategy.build_asymmetric_trap(
        Decimal("500"), active_vol=10.0, base_vol=20.0
    )

    assert trap["status"] == "STRUCTURE_READY_NOT_PRICED"
    assert trap["pricing_mode"] == "UNRESOLVED_LIMIT_PRICE"
    assert "ZERO_COST" not in str(trap)


def test_track2_execution_plan_fails_closed_without_verified_config_and_risk() -> None:
    strategy = Track2AsymmetricTrap()

    with pytest.raises(ValueError, match="TRACK2_CONFIG_OR_RISK_GATE_BLOCKED"):
        strategy.build_execution_plan(
            group_id="test-group",
            current_atm=Decimal("500"),
            active_vol=10.0,
            base_vol=20.0,
        )
