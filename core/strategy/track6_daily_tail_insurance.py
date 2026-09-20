from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from contracts.analytics import AnalyticsSnapshot, AnalyticsStatus
from contracts.types import MultiLegExecutionPlan
from core.strategy.contracts import Signal, StrategyContext, StrategyFeatureRequirement
from core.strategy.multi_leg_plan import build_pair_plan
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


@dataclass(frozen=True)
class Track6ExecutionInput:
    """Authoritative option-selection metadata; market analytics stay in AnalyticsSnapshot."""
    strategy_id: str
    date_str: str
    time_str: str = "09:00:00"
    listed_put_strike: Decimal | None = None
    listed_call_strike: Decimal | None = None
    contract_multiplier: Decimal | None = None


@dataclass(frozen=True)
class Track6State:
    is_active: bool = False
    bought_date: str | None = None
    long_put_strike: Decimal = Decimal("0")
    long_call_strike: Decimal = Decimal("0")
    high_watermark_intrinsic: Decimal = Decimal("0")
    trailing_stop_active: bool = False


class Track6DailyTailInsurance:
    strategy_id = "track6_daily_tail_insurance"
    version = "1.0"
    VOL_TRIGGER_MULTIPLIER = Decimal("1.3")
    INSURANCE_QTY = 1

    def __init__(self, vol_trigger_multiplier: Decimal = VOL_TRIGGER_MULTIPLIER,
                 insurance_qty: int = INSURANCE_QTY) -> None:
        self.vol_trigger_multiplier = vol_trigger_multiplier
        self.insurance_qty = insurance_qty
        self.state = Track6State()

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        return tuple(
            StrategyFeatureRequirement(key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
            for key in (
                "price.last", "volatility.active", "volatility.base", "volatility.ratio",
                "portfolio.premium_spent",
            )
        )

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track6State()

    @staticmethod
    def _metric(snapshot: AnalyticsSnapshot, key: str):
        metric = snapshot.get(key)
        if metric is None or metric.status is not AnalyticsStatus.AVAILABLE:
            return None
        return metric.value

    @staticmethod
    def _as_execution_input(context: StrategyContext) -> Track6ExecutionInput | None:
        payload = getattr(getattr(context, "input", None), "payload", None)
        return payload if isinstance(payload, Track6ExecutionInput) else None

    @staticmethod
    def _as_time(snapshot: AnalyticsSnapshot) -> str:
        return snapshot.as_of.strftime("%H:%M:%S")

    @staticmethod
    def _as_date(snapshot: AnalyticsSnapshot) -> str:
        return snapshot.as_of.date().isoformat()

    def evaluate_buy(self, context: StrategyContext) -> Sequence[Signal]:
        analytics = context.analytics
        data = self._as_execution_input(context)
        if analytics is None or data is None or self.state.is_active:
            return ()
        current_price = self._metric(analytics, "price.last")
        active_vol = self._metric(analytics, "volatility.active")
        base_vol = self._metric(analytics, "volatility.base")
        if not all(isinstance(value, Decimal) for value in (current_price, active_vol, base_vol)):
            return ()
        if "15:15" <= self._as_time(analytics) < "15:20":
            return (Signal(self.strategy_id, "CANCEL", 1.0, "CANCEL_PENDING_TRANCHES_15:15"),)
        if data.contract_multiplier is None or data.contract_multiplier <= 0:
            return ()
        if data.listed_put_strike is None or data.listed_call_strike is None:
            return ()
        if base_vol <= 0 or active_vol < base_vol * self.vol_trigger_multiplier:
            return ()
        put_strike = data.listed_put_strike
        call_strike = data.listed_call_strike
        self.state = replace(self.state, is_active=True, bought_date=self._as_date(analytics),
                             long_put_strike=put_strike, long_call_strike=call_strike,
                             high_watermark_intrinsic=Decimal("0"), trailing_stop_active=False)
        return (Signal(
            self.strategy_id, "BUY_INSURANCE", 1.0,
            f"VOL_SPIKE:{active_vol}>={base_vol * self.vol_trigger_multiplier};PUT:{put_strike};CALL:{call_strike};QTY:{self.insurance_qty}",
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=self.insurance_qty, asset_type="OPTION", side="BUY",
                track_id=self.strategy_id, tag_id="DAILY_TAIL_INSURANCE_ENTRY",
                option_type="PUT", strike=put_strike,
            ),
        ),)

    def build_execution_plan(self, group_id: str) -> MultiLegExecutionPlan | None:
        if not self.state.is_active or self.state.long_put_strike <= 0 or self.state.long_call_strike <= 0:
            return None
        return build_pair_plan(group_id=group_id, strategy_id=self.strategy_id,
                               purpose="DAILY_TAIL_INSURANCE_ENTRY",
                               put_strike=self.state.long_put_strike, call_strike=self.state.long_call_strike,
                               put_quantity=self.insurance_qty, call_quantity=self.insurance_qty, side="BUY")

    def evaluate_take_profit(self, context: StrategyContext) -> Sequence[Signal]:
        analytics = context.analytics
        if analytics is None or not self.state.is_active:
            return ()
        current_price = self._metric(analytics, "price.last")
        active_vol = self._metric(analytics, "volatility.active")
        premium_spent = self._metric(analytics, "portfolio.premium_spent")
        if not all(isinstance(value, Decimal) for value in (current_price, active_vol, premium_spent)):
            return ()
        if self._as_time(analytics) >= "15:12:00":
            return ()
        if premium_spent <= 0 or self.insurance_qty <= 0:
            return ()
        multiplier = premium_spent / Decimal(self.insurance_qty)
        put_intrinsic = max(Decimal("0"), self.state.long_put_strike - current_price) * multiplier * self.insurance_qty
        call_intrinsic = max(Decimal("0"), current_price - self.state.long_call_strike) * multiplier * self.insurance_qty
        total_intrinsic = put_intrinsic + call_intrinsic
        spent = premium_spent
        minimum_multiplier = Decimal("1.5") if active_vol < Decimal("1.3") else Decimal("2.0")
        trailing_active = self.state.trailing_stop_active or total_intrinsic >= spent * minimum_multiplier
        if not trailing_active:
            return ()
        previous_high = self.state.high_watermark_intrinsic
        current_high = max(previous_high, total_intrinsic)
        pnl_ratio = current_high / max(Decimal("1"), spent)
        trailing_ratio = Decimal("0.90") if pnl_ratio >= 2 else Decimal("0.88") if pnl_ratio >= Decimal("1.3") else Decimal("0.85")
        stop_trigger = current_high * trailing_ratio
        if current_high > 0 and total_intrinsic <= stop_trigger:
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0,
                           f"TRAILING_STOP;REALIZED:{total_intrinsic};HIGH:{current_high};RATIO:{trailing_ratio}"),)
        if previous_high == 0 or current_high >= previous_high * Decimal("1.01"):
            self.state = replace(self.state, trailing_stop_active=True, high_watermark_intrinsic=current_high)
            return (Signal(self.strategy_id, "UPDATE_TRAILING", 0.9,
                           f"HIGH_WATERMARK:{current_high};STOP_TRIGGER:{stop_trigger};OFFSET_TICKS:2"),)
        self.state = replace(self.state, trailing_stop_active=trailing_active)
        return ()

    def evaluate_expiry_cutoff(self, context: StrategyContext) -> Sequence[Signal]:
        if not self.state.is_active or context.analytics is None:
            return ()
        time_str = self._as_time(context.analytics)
        if "15:00:00" <= time_str < "15:15:00":
            return (Signal(self.strategy_id, "CLOSE_LIMIT", 1.0, "DAILY_INSURANCE_15:00_CUTOFF"),)
        if time_str >= "15:15:00":
            self.reset()
            return (Signal(self.strategy_id, "CLOSE_FALLBACK", 1.0, "DAILY_INSURANCE_15:15_FALLBACK"),)
        return ()

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.analytics is None:
            return ()
        if self.state.is_active:
            cutoff = self.evaluate_expiry_cutoff(context)
            return cutoff or self.evaluate_take_profit(context)
        return self.evaluate_buy(context)
