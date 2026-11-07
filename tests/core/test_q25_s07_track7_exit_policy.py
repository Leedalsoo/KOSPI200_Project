from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from contracts.analytics import AnalyticsStatus
from core.strategy.track7_volatility_skew_weekly_insurance import (
    Track7State,
    Track7VolatilitySkewWeeklyInsurance,
)


def _metric(value):
    return SimpleNamespace(status=AnalyticsStatus.AVAILABLE, value=value)


def _strategy(*, expiry="20261112", put_entry="1.0", call_entry="1.0",
              put_peak="1.0", call_peak="1.0"):
    strategy = Track7VolatilitySkewWeeklyInsurance(
        runtime_config_verified=True, risk_limits_available=True
    )
    strategy.state = Track7State(
        insurance_active=True, expiry=expiry,
        put_strike=Decimal("487.5"), call_strike=Decimal("512.5"),
        contract_multiplier=Decimal("250000"),
        put_entry_fill_price=Decimal(put_entry),
        call_entry_fill_price=Decimal(call_entry),
        put_peak_mark=Decimal(put_peak), call_peak_mark=Decimal(call_peak),
        put_open=True, call_open=True,
    )
    return strategy


def _evaluate(strategy, at, put_mark, call_mark):
    analytics = SimpleNamespace(
        as_of=at,
        get=lambda key: _metric({
            "options.track7_put_mark_price": Decimal(put_mark),
            "options.track7_call_mark_price": Decimal(call_mark),
        }.get(key)),
    )
    return strategy.evaluate(SimpleNamespace(
        strategy_id=strategy.strategy_id, analytics=analytics
    ))


def test_s07_put_trailing_arms_at_2x_then_closes_at_10pct_drawdown():
    strategy = _strategy()
    assert _evaluate(strategy, datetime(2026, 11, 10, 10, 0), "2.0", "1.0") == ()
    assert strategy.state.put_peak_mark == Decimal("2.0")
    signals = _evaluate(strategy, datetime(2026, 11, 10, 10, 1), "1.8", "1.0")
    assert len(signals) == 1
    assert signals[0].reason == "PUT_LEG_2X_ARMED_10PCT_DRAWDOWN"
    assert signals[0].execution_proposal.tag_id == "WEEKLY_INSURANCE_CLOSE_PUT"


def test_s07_trailing_uses_updated_high_water_not_entry_multiple():
    strategy = _strategy(put_peak="2.5")
    signals = _evaluate(strategy, datetime(2026, 11, 10, 10, 0), "2.24", "1.0")
    assert len(signals) == 1
    assert signals[0].reason == "PUT_LEG_2X_ARMED_10PCT_DRAWDOWN"


def test_s07_call_50pct_stop_is_independent_per_leg():
    strategy = _strategy()
    signals = _evaluate(strategy, datetime(2026, 11, 10, 10, 0), "1.0", "0.5")
    assert len(signals) == 1
    assert signals[0].reason == "CALL_LEG_50PCT_STOP"
    assert signals[0].execution_proposal.tag_id == "WEEKLY_INSURANCE_CLOSE_CALL"


def test_s07_expiry_1510_terminal_close_precedes_per_leg_stop():
    strategy = _strategy(expiry="20261110")
    signals = _evaluate(strategy, datetime(2026, 11, 10, 15, 10), "0.4", "0.4")
    assert len(signals) == 1
    assert signals[0].reason == "WEEKLY_EXACT_EXPIRY_15:10"
    assert signals[0].execution_proposal.tag_id == "WEEKLY_INSURANCE_CLOSE"
    plan = strategy.build_execution_plan(
        group_id="s7-expiry-close",
        proposal=signals[0].execution_proposal,
    )
    assert {leg.leg_id for leg in plan.legs} == {"put", "call"}
    assert all(leg.side == "SELL" for leg in plan.legs)


def test_s07_pre_expiry_cutoff_still_allows_per_leg_stop():
    strategy = _strategy(expiry="20261110")
    signals = _evaluate(strategy, datetime(2026, 11, 10, 15, 9, 59), "0.5", "1.0")
    assert len(signals) == 1
    assert signals[0].reason == "PUT_LEG_50PCT_STOP"


def test_s07_expiry_cutoff_normalizes_offset_aware_timestamp_to_kst():
    strategy = _strategy(expiry="20261110")
    # 06:10 UTC is 15:10 KST on the same expiry date.
    signals = _evaluate(
        strategy, datetime(2026, 11, 10, 6, 10, tzinfo=timezone.utc), "1.0", "1.0"
    )
    assert len(signals) == 1
    assert signals[0].reason == "WEEKLY_EXACT_EXPIRY_15:10"
