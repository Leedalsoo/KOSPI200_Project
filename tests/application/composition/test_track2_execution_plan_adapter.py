from types import SimpleNamespace
from decimal import Decimal

from application.composition.track2_execution_plan_adapter import Track2ExecutionPlanAdapter
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap


def test_track2_adapter_accepts_only_protection_first_four_leg_plan():
    strategy = Track2AsymmetricTrap(runtime_config_verified=True, risk_limits_available=True)
    signal = SimpleNamespace(track_id='track2_asymmetric_trap', reason='ASYMMETRIC_TRAP_ENTRY')
    plan = Track2ExecutionPlanAdapter().build_plan(
        approved_signal=signal, strategy=strategy,
        current_atm=Decimal('500'), active_vol=10.0, base_vol=20.0,
        group_id='track2-adapter-test',
    )
    assert [(leg.leg_id, leg.side, leg.option_type) for leg in plan.legs] == [
        ('inner_put', 'BUY', 'PUT'), ('inner_call', 'BUY', 'CALL'),
        ('outer_put', 'SELL', 'PUT'), ('outer_call', 'SELL', 'CALL'),
    ]
