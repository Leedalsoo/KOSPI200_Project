from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from contracts.analytics import AnalyticsStatus
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track9_event_overnight_insurance import Track9EventOvernightInsurance


class _Metric:
    def __init__(self, value):
        self.value = value
        self.status = AnalyticsStatus.AVAILABLE


class _LegacyAnalytics:
    """Complete legacy metrics that used to trigger the overnight pair entry."""

    _values = {
        "price.last": Decimal("700"),
        "options.atm_put_strike": Decimal("700"),
        "options.atm_call_strike": Decimal("700"),
        "options.contract_multiplier": Decimal("250000"),
        "options.track9_put_entry_price": Decimal("2.0"),
        "options.track9_call_entry_price": Decimal("2.0"),
        "options.track9_put_mark_price": Decimal("2.1"),
        "options.track9_call_mark_price": Decimal("2.1"),
    }

    def get(self, key):
        value = self._values.get(key)
        return _Metric(value) if value is not None else None


def test_s9_does_not_emit_legacy_overnight_pair_signal():
    strategy = Track9EventOvernightInsurance()
    now = datetime(2026, 10, 21, 15, 20, tzinfo=ZoneInfo("Asia/Seoul"))
    context = StrategyContext(
        strategy_id=strategy.strategy_id,
        input=StrategyInput(
            common=CommonStrategyInput(
                as_of=now,
                time_str="15:20:00",
                date_str="20261021",
            )
        ),
        analytics=_LegacyAnalytics(),
    )

    assert strategy.evaluate(context) == ()
