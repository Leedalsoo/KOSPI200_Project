from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from contracts.analytics import AnalyticsSnapshot, AnalyticsStatus
from core.market.session_policy import MarketSessionPolicy
from contracts.types import MultiLegExecutionPlan
from core.strategy.contracts import Signal, StrategyContext, StrategyFeatureRequirement
from core.strategy.multi_leg_plan import ExecutionLeg
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


@dataclass(frozen=True)
class Track7ExecutionInput:
    """Authoritative Option Master selection supplied by composition."""

    strategy_id: str
    expiry: str
    listed_put_strike: Decimal
    listed_call_strike: Decimal
    contract_multiplier: Decimal


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
    skew_direction: str | None = None


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

    @staticmethod
    def _execution_input(context: StrategyContext) -> Track7ExecutionInput | None:
        payload = getattr(getattr(context, "input", None), "payload", None)
        return payload if isinstance(payload, Track7ExecutionInput) else None

    def evaluate_insurance_buy(self, context: StrategyContext) -> Sequence[Signal]:
        analytics = context.analytics
        if analytics is None or self.state.insurance_active:
            return ()
        is_new_week_start = self._metric(analytics, "calendar.is_new_week_start")
        if is_new_week_start is not True:
            return ()
        if self._metric(analytics, "execution.order_timeout") is True:
            return ()
        contract = self._execution_input(context)
        if contract is None or contract.contract_multiplier <= 0:
            return ()
        if contract.listed_put_strike <= 0 or contract.listed_call_strike <= 0:
            return ()
        as_of = analytics.as_of.date().isoformat()
        self.state = replace(self.state, insurance_active=True, bought_date=as_of,
                             put_strike=contract.listed_put_strike, call_strike=contract.listed_call_strike,
                             premium_spent=Decimal("0"), high_watermark_intrinsic=Decimal("0"), trailing_active=False)
        return (Signal(
            self.strategy_id, "BUY_WEEKLY_INSURANCE", 1.0,
            f"NEW_WEEK:{as_of};PUT:{contract.listed_put_strike};CALL:{contract.listed_call_strike};QTY:{self.insurance_qty}",
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=self.insurance_qty, asset_type="OPTION", side="BUY",
                track_id=self.strategy_id, tag_id="WEEKLY_INSURANCE_ENTRY",
                option_type="PUT", strike=contract.listed_put_strike,
            ),
        ),)

    def evaluate_skew_arbitrage(self, context: StrategyContext) -> Sequence[Signal]:
        analytics = context.analytics
        contract = self._execution_input(context)
        if analytics is None or contract is None or contract.contract_multiplier <= 0:
            return ()
        skew = self._metric(analytics, "options.skew")
        if not isinstance(skew, Decimal):
            return ()

        if not self.state.skew_active:
            if abs(skew) < self.SKEW_ENTRY:
                return ()
            direction = "LONG_PUT_SHORT_CALL" if skew > 0 else "LONG_CALL_SHORT_PUT"
            self.state = replace(
                self.state, skew_active=True, skew_limit_pending=True, skew_direction=direction,
                put_strike=contract.listed_put_strike, call_strike=contract.listed_call_strike,
            )
            long_type = "PUT" if direction == "LONG_PUT_SHORT_CALL" else "CALL"
            long_strike = contract.listed_put_strike if long_type == "PUT" else contract.listed_call_strike
            return (
                Signal(
                    self.strategy_id, "ENTER_SKEW_ARB_LIMIT", 1.0,
                    f"TYPE:{direction};SKEW:{skew};QTY:{self.insurance_qty}",
                    execution_proposal=StrategyExecutionProposal(
                        proposed_quantity=self.insurance_qty, asset_type="OPTION", side="BUY",
                        track_id=self.strategy_id, tag_id="WEEKLY_SKEW_ARB_ENTRY",
                        option_type=long_type, strike=long_strike,
                    ),
                ),
            )

        timeout = self._metric(analytics, "execution.order_timeout")
        long_type = "PUT" if self.state.skew_direction == "LONG_PUT_SHORT_CALL" else "CALL"
        long_strike = self.state.put_strike if long_type == "PUT" else self.state.call_strike
        if self.state.skew_limit_pending and timeout is True:
            self.state = replace(self.state, skew_limit_pending=False)
            return (
                Signal(
                    self.strategy_id, "ENTER_SKEW_ARB_FALLBACK_MARKET", 1.0,
                    f"SKEW:{skew};QTY:{self.insurance_qty}",
                    execution_proposal=StrategyExecutionProposal(
                        proposed_quantity=self.insurance_qty, asset_type="OPTION", side="BUY",
                        track_id=self.strategy_id, tag_id="WEEKLY_SKEW_ARB_ENTRY_FALLBACK",
                        option_type=long_type, strike=long_strike,
                    ),
                ),
            )
        if abs(skew) > self.SKEW_STOP:
            self.state = replace(self.state, skew_active=False, skew_limit_pending=False)
            return (
                Signal(
                    self.strategy_id, "CLOSE_SKEW_ARB_STOP_LOSS", 1.0,
                    f"SKEW:{skew};STOP:{self.SKEW_STOP};QTY:1",
                    execution_proposal=StrategyExecutionProposal(
                        proposed_quantity=self.insurance_qty, asset_type="OPTION", side="SELL",
                        track_id=self.strategy_id, tag_id="WEEKLY_SKEW_ARB_STOP",
                        option_type=long_type, strike=long_strike,
                    ),
                ),
            )
        if abs(skew) <= self.SKEW_EXIT:
            self.state = replace(self.state, skew_active=False, skew_limit_pending=False)
            return (
                Signal(
                    self.strategy_id, "CLOSE_SKEW_ARB_LIMIT", 1.0,
                    f"SKEW:{skew};EXIT:{self.SKEW_EXIT};QTY:1",
                    execution_proposal=StrategyExecutionProposal(
                        proposed_quantity=self.insurance_qty, asset_type="OPTION", side="SELL",
                        track_id=self.strategy_id, tag_id="WEEKLY_SKEW_ARB_CLOSE",
                        option_type=long_type, strike=long_strike,
                    ),
                ),
            )
        return ()

    def build_execution_plan(self, group_id: str, *, proposal: StrategyExecutionProposal) -> MultiLegExecutionPlan:
        if proposal.option_type not in {"PUT", "CALL"} or proposal.strike is None:
            raise ValueError("TRACK7_EXECUTION_PROPOSAL_CONTRACT_REQUIRED")
        if self.state.put_strike <= 0 or self.state.call_strike <= 0:
            raise ValueError("TRACK7_OPTION_SELECTION_REQUIRED")
        primary_type=str(proposal.option_type).upper()
        primary_side=str(proposal.side or "").upper()
        if primary_side not in {"BUY","SELL"}:
            raise ValueError("TRACK7_EXECUTION_SIDE_REQUIRED")
        if self.state.insurance_active and not self.state.skew_active:
            if primary_type == "PUT" and primary_side == "BUY" and Decimal(str(proposal.strike)) == self.state.put_strike:
                return MultiLegExecutionPlan(
                    group_id=group_id, strategy_id=self.strategy_id, purpose="WEEKLY_INSURANCE_ENTRY",
                    legs=(
                        ExecutionLeg("put","BUY",self.insurance_qty,"PUT",self.state.put_strike),
                        ExecutionLeg("call","BUY",self.insurance_qty,"CALL",self.state.call_strike),
                    ),
                )
            if primary_type == "PUT" and primary_side == "SELL" and Decimal(str(proposal.strike)) == self.state.put_strike:
                plan = MultiLegExecutionPlan(
                    group_id=group_id, strategy_id=self.strategy_id, purpose="WEEKLY_INSURANCE_CLOSE",
                    legs=(
                        ExecutionLeg("put","SELL",self.insurance_qty,"PUT",self.state.put_strike),
                        ExecutionLeg("call","SELL",self.insurance_qty,"CALL",self.state.call_strike),
                    ),
                )
                self.reset()
                return plan
            raise ValueError("TRACK7_INSURANCE_EXECUTION_MUST_START_WITH_PUT")
        secondary_type="CALL" if primary_type=="PUT" else "PUT"
        secondary_side="SELL" if primary_side=="BUY" else "BUY"
        primary_strike=self.state.put_strike if primary_type=="PUT" else self.state.call_strike
        secondary_strike=self.state.call_strike if secondary_type=="CALL" else self.state.put_strike
        if Decimal(str(proposal.strike)) != primary_strike:
            raise ValueError("TRACK7_EXECUTION_STRIKE_MISMATCH")
        return MultiLegExecutionPlan(
            group_id=group_id, strategy_id=self.strategy_id, purpose="WEEKLY_SKEW_ARBITRAGE",
            legs=(
                ExecutionLeg("primary",primary_side,self.insurance_qty,primary_type,primary_strike),
                ExecutionLeg("secondary",secondary_side,self.insurance_qty,secondary_type,secondary_strike),
            ),
        )

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
            return (Signal(
                self.strategy_id, "PREEMPTIVE_LIMIT_TAKE_PROFIT", 0.8,
                f"MA_CROSS:{bullish_cross or bearish_cross};SUPPORT:{support};RESISTANCE:{resistance};PRICE:{price}",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=self.insurance_qty, asset_type="OPTION", side="SELL",
                    track_id=self.strategy_id, tag_id="WEEKLY_INSURANCE_CLOSE_PREEMPTIVE",
                    option_type="PUT", strike=self.state.put_strike,
                ),
            ),)
        return ()

    def evaluate_expiry_cutoff(self, context: StrategyContext) -> Sequence[Signal]:
        analytics = context.analytics
        if analytics is None or not self.state.insurance_active:
            return ()
        time_str = analytics.as_of.strftime("%H:%M:%S")
        expiry_active = self._metric(analytics, "calendar.is_expiry_day") is True or self._metric(analytics, "calendar.is_week_end") is True
        if self.expiry_mode == "D-4" and time_str >= MarketSessionPolicy.text(MarketSessionPolicy.LIMIT_CUTOFF):
            return (Signal(
                self.strategy_id, "CLOSE_WEEKLY_INSURANCE_PREEMPTIVE_D4", 1.0, "D4_PREEMPTIVE_CUTOFF",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=self.insurance_qty, asset_type="OPTION", side="SELL",
                    track_id=self.strategy_id, tag_id="WEEKLY_INSURANCE_CLOSE_D4",
                    option_type="PUT", strike=self.state.put_strike,
                ),
            ),)
        if not expiry_active:
            return ()
        if MarketSessionPolicy.text(MarketSessionPolicy.LIMIT_CUTOFF) <= time_str < MarketSessionPolicy.text(MarketSessionPolicy.MARKET_CUTOFF):
            return (Signal(
                self.strategy_id, "CLOSE_WEEKLY_INSURANCE_LIMIT", 1.0, "15:00_LIMIT_CUTOFF",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=self.insurance_qty, asset_type="OPTION", side="SELL",
                    track_id=self.strategy_id, tag_id="WEEKLY_INSURANCE_CLOSE_LIMIT",
                    option_type="PUT", strike=self.state.put_strike,
                ),
            ),)
        if time_str >= MarketSessionPolicy.text(MarketSessionPolicy.MARKET_CUTOFF):
            return (Signal(
                self.strategy_id, "CLOSE_WEEKLY_INSURANCE_FALLBACK_MARKET", 1.0, "15:15_FALLBACK_MARKET",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=self.insurance_qty, asset_type="OPTION", side="SELL",
                    track_id=self.strategy_id, tag_id="WEEKLY_INSURANCE_CLOSE_MARKET",
                    option_type="PUT", strike=self.state.put_strike,
                ),
            ),)
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
