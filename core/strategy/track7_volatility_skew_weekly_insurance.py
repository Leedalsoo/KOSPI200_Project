from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from contracts.analytics import AnalyticsSnapshot, AnalyticsStatus
from core.strategy.contracts import Signal, StrategyContext, StrategyFeatureRequirement


@dataclass(frozen=True)
class Track7State:
    insurance_active: bool = False
    bought_date: str | None = None
    put_strike: Decimal = Decimal("0")
    call_strike: Decimal = Decimal("0")
    premium_spent: Decimal = Decimal("0")
    high_watermark_intrinsic: Decimal = Decimal("0")
    trailing_active: bool = False
    skew_active: bool = False
    skew_limit_pending: bool = False


class Track7VolatilitySkewWeeklyInsurance:
    strategy_id = "track7_volatility_skew_weekly_insurance"
    version = "1.0"
    INSURANCE_QTY = 1
    SKEW_ENTRY = Decimal("3.0")
    SKEW_STOP = Decimal("8.0")
    SKEW_EXIT = Decimal("0.5")

    def __init__(self, insurance_qty: int = INSURANCE_QTY, expiry_mode: str = "D-0 CUTOFF") -> None:
        self.insurance_qty = insurance_qty
        self.expiry_mode = expiry_mode
        self.state = Track7State()

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        return tuple(
            StrategyFeatureRequirement(key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
            for key in (
                "price.last", "options.call_iv", "options.put_iv", "options.skew",
                "trend.ma_1m", "trend.ma_3m", "trend.ma_5m", "trend.ma_10m",
                "levels.support", "levels.resistance",
                "calendar.is_new_week_start", "calendar.is_expiry_day", "calendar.is_week_end",
                "execution.order_timeout",
            )
        )

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track7State()

    @staticmethod
    def _metric(snapshot: AnalyticsSnapshot, key: str):
        metric = snapshot.get(key)
        if metric is None or metric.status is not AnalyticsStatus.AVAILABLE:
            return None
        return metric.value

    def evaluate_insurance_buy(self, context: StrategyContext) -> Sequence[Signal]:
        analytics = context.analytics
        if analytics is None or self.state.insurance_active:
            return ()
        is_new_week_start = self._metric(analytics, "calendar.is_new_week_start")
        if is_new_week_start is not True:
            return ()
        if self._metric(analytics, "execution.order_timeout") is True:
            return ()
        # Contract identity/strike selection is intentionally not derived here.
        # Until an authoritative Option Master selection is injected, fail closed.
        return ()

    def evaluate_skew_arbitrage(self, context: StrategyContext) -> Sequence[Signal]:
        analytics = context.analytics
        if analytics is None:
            return ()
        skew = self._metric(analytics, "options.skew")
        if not isinstance(skew, Decimal):
            return ()
        if not self.state.skew_active:
            if abs(skew) < self.SKEW_ENTRY:
                return ()
            self.state = replace(self.state, skew_active=True, skew_limit_pending=True)
            direction = "LONG_PUT_SHORT_CALL" if skew > 0 else "LONG_CALL_SHORT_PUT"
            return (Signal(self.strategy_id, "ENTER_SKEW_ARB_LIMIT", 1.0, f"TYPE:{direction};SKEW:{skew};QTY:1"),)
        timeout = self._metric(analytics, "execution.order_timeout")
        if self.state.skew_limit_pending and timeout is True:
            self.state = replace(self.state, skew_limit_pending=False)
            return (Signal(self.strategy_id, "ENTER_SKEW_ARB_FALLBACK_MARKET", 1.0, f"SKEW:{skew};QTY:1"),)
        if abs(skew) > self.SKEW_STOP:
            self.state = replace(self.state, skew_active=False, skew_limit_pending=False)
            return (Signal(self.strategy_id, "CLOSE_SKEW_ARB_STOP_LOSS", 1.0, f"SKEW:{skew};STOP:{self.SKEW_STOP};QTY:1"),)
        if abs(skew) <= self.SKEW_EXIT:
            self.state = replace(self.state, skew_active=False, skew_limit_pending=False)
            return (Signal(self.strategy_id, "CLOSE_SKEW_ARB_LIMIT", 1.0, f"SKEW:{skew};EXIT:{self.SKEW_EXIT};QTY:1"),)
        return ()

    def evaluate_preemptive_take_profit(self, context: StrategyContext) -> Sequence[Signal]:
        analytics = context.analytics
        if analytics is None or not self.state.insurance_active:
            return ()
        values = tuple(self._metric(analytics, key) for key in (
            "price.last", "trend.ma_1m", "trend.ma_3m", "trend.ma_5m", "trend.ma_10m",
        ))
        price, ma_1m, ma_3m, ma_5m, ma_10m = values
        if not all(isinstance(value, Decimal) for value in values):
            return ()
        bullish_cross = ma_1m > ma_3m > ma_5m > ma_10m
        bearish_cross = ma_1m < ma_3m < ma_5m < ma_10m
        support = self._metric(analytics, "levels.support")
        resistance = self._metric(analytics, "levels.resistance")
        near_resistance = isinstance(resistance, Decimal) and price >= resistance
        near_support = isinstance(support, Decimal) and price <= support
        if bullish_cross or bearish_cross or near_resistance or near_support:
            return (Signal(self.strategy_id, "PREEMPTIVE_LIMIT_TAKE_PROFIT", 0.8,
                           f"MA_CROSS:{bullish_cross or bearish_cross};SUPPORT:{support};RESISTANCE:{resistance};PRICE:{price}"),)
        return ()

    def evaluate_expiry_cutoff(self, context: StrategyContext) -> Sequence[Signal]:
        analytics = context.analytics
        if analytics is None or not self.state.insurance_active:
            return ()
        time_str = analytics.as_of.strftime("%H:%M:%S")
        expiry_active = self._metric(analytics, "calendar.is_expiry_day") is True or self._metric(analytics, "calendar.is_week_end") is True
        if self.expiry_mode == "D-4" and time_str >= "15:00:00":
            self.reset()
            return (Signal(self.strategy_id, "CLOSE_WEEKLY_INSURANCE_PREEMPTIVE_D4", 1.0, "D4_PREEMPTIVE_CUTOFF"),)
        if not expiry_active:
            return ()
        if "15:00:00" <= time_str < "15:15:00":
            return (Signal(self.strategy_id, "CLOSE_WEEKLY_INSURANCE_LIMIT", 1.0, "15:00_LIMIT_CUTOFF"),)
        if time_str >= "15:15:00":
            self.reset()
            return (Signal(self.strategy_id, "CLOSE_WEEKLY_INSURANCE_FALLBACK_MARKET", 1.0, "15:15_FALLBACK_MARKET"),)
        return ()

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.analytics is None:
            return ()
        if self.state.insurance_active:
            cutoff = self.evaluate_expiry_cutoff(context)
            if cutoff:
                return cutoff
            return self.evaluate_preemptive_take_profit(context)
        skew = self.evaluate_skew_arbitrage(context)
        if skew:
            return skew
        return self.evaluate_insurance_buy(context)
