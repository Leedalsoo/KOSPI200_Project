from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence
from contracts.analytics import AnalyticsSnapshot, AnalyticsStatus
from contracts.types import MultiLegExecutionPlan
from core.strategy.contracts import Signal, StrategyContext, StrategyFeatureRequirement
from core.strategy.multi_leg_plan import ExecutionLeg
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal

@dataclass(frozen=True)
class Track7ExecutionInput:
    strategy_id: str
    expiry: str
    reference_price: Decimal
    put_strike: Decimal
    call_strike: Decimal
    contract_multiplier: Decimal

@dataclass(frozen=True)
class Track7State:
    insurance_active: bool = False
    bought_date: str | None = None
    expiry: str | None = None
    reference_price: Decimal = Decimal("0")
    put_strike: Decimal = Decimal("0")
    call_strike: Decimal = Decimal("0")
    contract_multiplier: Decimal = Decimal("0")
    peak_profit: Decimal = Decimal("0")

class Track7VolatilitySkewWeeklyInsurance:
    strategy_id = "track7_volatility_skew_weekly_insurance"
    version = "1.0"
    INSURANCE_QTY = 1
    STRIKE_OFFSET = Decimal("12.5")
    TRAILING_DRAWDOWN = Decimal("0.20")

    def __init__(self, insurance_qty: int = INSURANCE_QTY) -> None:
        self.insurance_qty = insurance_qty
        self.state = Track7State()

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        return tuple(StrategyFeatureRequirement(k, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
                     for k in ("price.last", "calendar.is_new_week_start", "calendar.is_expiry_day",
                               "options.track7_put_mark_price", "options.track7_call_mark_price"))

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track7State()

    @staticmethod
    def _metric(snapshot: AnalyticsSnapshot, key: str):
        m = snapshot.get(key)
        if m is None or m.status is not AnalyticsStatus.AVAILABLE:
            return None
        return m.value

    @staticmethod
    def _execution_input(context: StrategyContext) -> Track7ExecutionInput | None:
        payload = getattr(getattr(context, "input", None), "payload", None)
        return payload if isinstance(payload, Track7ExecutionInput) else None

    def _close_signal(self, reason: str) -> Signal:
        return Signal(self.strategy_id, "CLOSE_WEEKLY_INSURANCE", 1.0, reason,
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=self.insurance_qty, asset_type="OPTION", side="SELL",
                track_id=self.strategy_id, tag_id="WEEKLY_INSURANCE_CLOSE",
                option_type="PUT", strike=self.state.put_strike))

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.analytics is None:
            return ()
        if self.state.insurance_active:
            put_mark = self._metric(context.analytics, "options.track7_put_mark_price")
            call_mark = self._metric(context.analytics, "options.track7_call_mark_price")
            peak = self.state.peak_profit
            current = None
            if isinstance(put_mark, Decimal) and isinstance(call_mark, Decimal) and self.state.contract_multiplier > 0 and put_mark >= 0 and call_mark >= 0:
                current = (put_mark + call_mark) * self.state.contract_multiplier
                if current > peak:
                    self.state = replace(self.state, peak_profit=current)
                    peak = current
            if peak > 0 and current is not None and current <= peak * (Decimal("1")-self.TRAILING_DRAWDOWN):
                return (self._close_signal(f"TRAILING_20PCT;CURRENT:{current};PEAK:{peak}"),)
            # The stream may contain multiple contract families and expiries.
            # Close only when this position's own authoritative weekly expiry arrives.
            if self.state.expiry == context.analytics.as_of.date().isoformat():
                hhmm = context.analytics.as_of.hour * 100 + context.analytics.as_of.minute
                if hhmm >= 1500:
                    return (self._close_signal("WEEKLY_EXACT_EXPIRY_15:00"),)
            return ()
        if self._metric(context.analytics, "calendar.is_new_week_start") is not True:
            return ()
        contract = self._execution_input(context)
        if contract is None or contract.contract_multiplier <= 0:
            return ()
        self.state = replace(self.state, insurance_active=True,
            bought_date=context.analytics.as_of.date().isoformat(), expiry=contract.expiry,
            reference_price=contract.reference_price, put_strike=contract.put_strike,
            call_strike=contract.call_strike, contract_multiplier=contract.contract_multiplier,
            peak_profit=Decimal("0"))
        return (Signal(self.strategy_id, "BUY_WEEKLY_INSURANCE", 1.0,
            f"NEW_WEEK:{self.state.bought_date};REF:{contract.reference_price};PUT:{contract.put_strike};CALL:{contract.call_strike}",
            execution_proposal=StrategyExecutionProposal(
                proposed_quantity=self.insurance_qty, asset_type="OPTION", side="BUY",
                track_id=self.strategy_id, tag_id="WEEKLY_INSURANCE_ENTRY",
                option_type="PUT", strike=contract.put_strike)),)

    def build_execution_plan(self, group_id: str, *, proposal: StrategyExecutionProposal) -> MultiLegExecutionPlan:
        if proposal.option_type != "PUT" or proposal.strike is None:
            raise ValueError("TRACK7_EXECUTION_PROPOSAL_CONTRACT_REQUIRED")
        if Decimal(str(proposal.strike)) != self.state.put_strike:
            raise ValueError("TRACK7_EXECUTION_STRIKE_MISMATCH")
        side = str(proposal.side).upper()
        if side == "BUY":
            return MultiLegExecutionPlan(group_id=group_id, strategy_id=self.strategy_id,
                purpose="WEEKLY_INSURANCE_ENTRY",
                legs=(ExecutionLeg("put","BUY",self.insurance_qty,"PUT",self.state.put_strike),
                      ExecutionLeg("call","BUY",self.insurance_qty,"CALL",self.state.call_strike)))
        if side == "SELL":
            plan=MultiLegExecutionPlan(group_id=group_id, strategy_id=self.strategy_id,
                purpose="WEEKLY_INSURANCE_CLOSE",
                legs=(ExecutionLeg("put","SELL",self.insurance_qty,"PUT",self.state.put_strike),
                      ExecutionLeg("call","SELL",self.insurance_qty,"CALL",self.state.call_strike)))
            self.reset()
            return plan
        raise ValueError("TRACK7_EXECUTION_SIDE_REQUIRED")
