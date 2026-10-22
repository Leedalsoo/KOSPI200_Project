from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from contracts.analytics import AnalyticsStatus
from core.strategy.track6_daily_tail_insurance import (
    Track6DailyTailInsurance,
    Track6ExecutionInput,
)


def test_track6_blocks_new_entry_at_or_after_1100_cutoff() -> None:
    strategy = Track6DailyTailInsurance(
        runtime_config_verified=True, risk_limits_available=True
    )
    values = {
        "price.last": Decimal("500"),
        "volatility.active": Decimal("0.30"),
        "volatility.base": Decimal("0.20"),
    }
    analytics = SimpleNamespace(
        as_of=datetime(2026, 10, 21, 11, 0, 0),
        get=lambda key: SimpleNamespace(
            status=AnalyticsStatus.AVAILABLE, value=values.get(key)
        ),
    )
    context = SimpleNamespace(
        analytics=analytics,
        input=SimpleNamespace(payload=Track6ExecutionInput(
            strategy_id=strategy.strategy_id,
            date_str="20261021",
            listed_put_strike=Decimal("490"),
            listed_call_strike=Decimal("510"),
            contract_multiplier=Decimal("250000"),
        )),
    )

    assert strategy.evaluate_buy(context) == ()
    assert strategy.state.entry_pending is False
