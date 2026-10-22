from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from contracts.analytics import AnalyticsStatus
from core.strategy.track7_volatility_skew_weekly_insurance import (
    Track7ExecutionInput,
    Track7VolatilitySkewWeeklyInsurance,
)


def test_track7_blocks_new_entry_at_or_after_1500_cutoff() -> None:
    strategy = Track7VolatilitySkewWeeklyInsurance(
        runtime_config_verified=True, risk_limits_available=True
    )
    values = {
        "calendar.is_new_week_start": True,
        "volatility.active": Decimal("0.30"),
        "volatility.base": Decimal("0.20"),
    }
    analytics = SimpleNamespace(
        as_of=datetime(2026, 10, 19, 15, 0, 0),
        get=lambda key: SimpleNamespace(
            status=AnalyticsStatus.AVAILABLE, value=values.get(key)
        ),
    )
    context = SimpleNamespace(
        strategy_id=strategy.strategy_id,
        analytics=analytics,
        input=SimpleNamespace(payload=Track7ExecutionInput(
            strategy_id=strategy.strategy_id,
            expiry="20261022",
            reference_price=Decimal("500"),
            put_strike=Decimal("487.5"),
            call_strike=Decimal("512.5"),
            contract_multiplier=Decimal("250000"),
        )),
    )

    assert strategy.evaluate(context) == ()
    assert strategy.state.entry_pending is False
