from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from contracts.analytics import AnalyticsMetric, AnalyticsSnapshot, AnalyticsStatus
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance, Track6ExecutionInput, Track6State

STRATEGY_ID = "track6_daily_tail_insurance"
BASE_VALUES = {
    "price.last": Decimal("100"),
    "volatility.active": Decimal("1"),
    "volatility.base": Decimal("1"),
    "volatility.ratio": Decimal("1"),
    "portfolio.premium_spent": Decimal("10"),
}

def make_context(time_str="10:00:00", values=None, *, payload=True):
    at = datetime.fromisoformat(f"2026-10-01T{time_str}")
    metrics = {}
    for key, value in (BASE_VALUES if values is None else values).items():
        metrics[key] = AnalyticsMetric(
            metric_key=key, value=value, status=AnalyticsStatus.AVAILABLE,
            unit="UNSPECIFIED", as_of=at, calculation_version="parity-test-v1",
            provenance=("UNIT_TEST",),
        )
    analytics = AnalyticsSnapshot(
        run_id="parity-test-run", instrument_identity=None, as_of=at,
        timeframe="tick", window=1, analytics_version="parity-test-v1", metrics=metrics,
    )
    execution_input = None
    if payload:
        execution_input = Track6ExecutionInput(
            strategy_id=STRATEGY_ID, date_str="2026-10-01", time_str=time_str,
            listed_put_strike=Decimal("87.5"), listed_call_strike=Decimal("112.5"),
            contract_multiplier=Decimal("250000"),
        )
    return StrategyContext(strategy_id=STRATEGY_ID, input=StrategyInput(payload=execution_input), analytics=analytics)

def active_strategy(*, high="0", trailing=False, pending=False):
    plugin = Track6DailyTailInsurance()
    plugin.state = Track6State(
        is_active=True, bought_date="2026-10-01", long_put_strike=Decimal("100"),
        long_call_strike=Decimal("100"), high_watermark_intrinsic=Decimal(high),
        trailing_stop_active=trailing,
    )
    plugin._exit_pending = pending
    return plugin

def case_contexts():
    cases = []
    cases.append(("inactive_volatility_below_trigger", Track6DailyTailInsurance(), make_context(values={**BASE_VALUES, "volatility.active": Decimal("1.2")}), ()))
    missing_multiplier = make_context(values={**BASE_VALUES, "volatility.active": Decimal("1.3")})
    missing_multiplier = replace(missing_multiplier, input=StrategyInput(payload=replace(missing_multiplier.input.payload, contract_multiplier=None)))
    cases.append(("trigger_but_multiplier_missing", Track6DailyTailInsurance(), missing_multiplier, ()))
    missing_strike = make_context(values={**BASE_VALUES, "volatility.active": Decimal("1.3")})
    missing_strike = replace(missing_strike, input=StrategyInput(payload=replace(missing_strike.input.payload, listed_call_strike=None)))
    cases.append(("trigger_but_strike_missing", Track6DailyTailInsurance(), missing_strike, ()))
    cases.append(("normal_buy_proposal", Track6DailyTailInsurance(), make_context(values={**BASE_VALUES, "volatility.active": Decimal("1.3")}), ("BUY_INSURANCE",)))
    cases.append(("base_vol_nonpositive", Track6DailyTailInsurance(), make_context(values={**BASE_VALUES, "volatility.active": Decimal("5"), "volatility.base": Decimal("0")}), ()))
    cases.append(("15_15_pending_cancel", Track6DailyTailInsurance(), make_context("15:15:00"), ("CANCEL",)))
    cases.append(("active_trailing_not_activated", active_strategy(), make_context(values={**BASE_VALUES, "portfolio.premium_spent": Decimal("10")}), ()))
    cases.append(("trailing_activation_low_vol_1_5x", active_strategy(), make_context(values={**BASE_VALUES, "price.last": Decimal("102"), "volatility.active": Decimal("1.2")}), ("UPDATE_TRAILING",)))
    cases.append(("trailing_activation_high_vol_2x", active_strategy(), make_context(values={**BASE_VALUES, "price.last": Decimal("102"), "volatility.active": Decimal("1.3")}), ("UPDATE_TRAILING",)))
    cases.append(("watermark_previous_high_zero", active_strategy(), make_context(values={**BASE_VALUES, "price.last": Decimal("102"), "volatility.active": Decimal("1.2")}), ("UPDATE_TRAILING",)))
    cases.append(("watermark_1_01_before_boundary", active_strategy(high="20", trailing=True), make_context(values={**BASE_VALUES, "price.last": Decimal("102.0199")}), ()))
    cases.append(("watermark_1_01_at_boundary", active_strategy(high="20", trailing=True), make_context(values={**BASE_VALUES, "price.last": Decimal("102.02")}), ("UPDATE_TRAILING",)))
    cases.append(("trailing_close_ratio_090_at_2_boundary", active_strategy(high="20", trailing=True), make_context(values={**BASE_VALUES, "price.last": Decimal("101.8")}), ("CLOSE",)))
    cases.append(("trailing_close_ratio_088", active_strategy(high="15", trailing=True), make_context(values={**BASE_VALUES, "price.last": Decimal("101.32")}), ("CLOSE",)))
    cases.append(("trailing_close_ratio_088_at_1_3_boundary", active_strategy(high="13", trailing=True), make_context(values={**BASE_VALUES, "price.last": Decimal("101.144")}), ("CLOSE",)))
    cases.append(("trailing_close_ratio_085_below_1_3", active_strategy(high="12", trailing=True), make_context(values={**BASE_VALUES, "price.last": Decimal("101.02")}), ("CLOSE",)))
    cases.append(("15_00_limit_close", active_strategy(), make_context("15:00:00"), ("CLOSE_LIMIT",)))
    cases.append(("15_15_fallback_close", active_strategy(), make_context("15:15:00"), ("CLOSE_FALLBACK",)))
    cases.append(("take_profit_suppressed_at_15_12", active_strategy(high="20", trailing=True), make_context("15:12:00", {**BASE_VALUES, "price.last": Decimal("101.8")}), ()))
    cases.append(("exit_pending_suppresses_resignal", active_strategy(high="20", trailing=True, pending=True), make_context(values={**BASE_VALUES, "price.last": Decimal("101.8")}), ()))
    cases.append(("premium_spent_nonpositive", active_strategy(high="20", trailing=True), make_context(values={**BASE_VALUES, "price.last": Decimal("101.8"), "portfolio.premium_spent": Decimal("0")}), ()))
    cases.append(("analytics_value_not_decimal", Track6DailyTailInsurance(), make_context(values={**BASE_VALUES, "volatility.active": 1.3}), ()))
    cases.append(("analytics_missing_payload", Track6DailyTailInsurance(), make_context(payload=False), ()))
    return cases