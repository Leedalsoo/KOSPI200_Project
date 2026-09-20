"""Track9 Event Overnight Insurance strategy."""
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from contracts.analytics import AnalyticsStatus
from core.strategy.contracts import Signal, StrategyContext, StrategyFeatureRequirement
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


@dataclass(frozen=True)
class Track9State:
    event_active: bool = False
    early_profit_take_executed_today: bool = False
    reentry_executed_today: bool = False
    state: str = "OVERNIGHT_HEDGE"
    event_high_pnl: Decimal = Decimal("0")
    active_date: str | None = None


class Track9EventOvernightInsurance:
    strategy_id = "track9_event_overnight_insurance"
    version = "2.0"
    EVENT_IV_SPIKE = Decimal("4")
    VOL_CRUSH = Decimal("-3")
    PROFIT_TARGET = Decimal("400000")

    def __init__(
        self,
        early_profit_take_ratio: Decimal = Decimal("0.90"),
        profit_target: Decimal = PROFIT_TARGET,
    ) -> None:
        self.early_profit_take_ratio = early_profit_take_ratio
        self.profit_target = profit_target
        self.state = Track9State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track9State()

    @staticmethod
    def _requirement(key: str) -> StrategyFeatureRequirement:
        return StrategyFeatureRequirement(
            key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE})
        )

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        return tuple(self._requirement(key) for key in (
            "portfolio.active_sell_qty", "portfolio.insurance_qty", "events.upcoming",
            "options.iv_spike", "options.iv_crush", "portfolio.current_pnl",
            "portfolio.total_fees", "portfolio.net_pnl", "portfolio.margin_ratio",
            "risk.guard_active", "portfolio.event_budget", "portfolio.estimated_event_cost",
            "options.atm_call_strike", "options.atm_put_strike",
            "options.contract_multiplier", "portfolio.premium_spent",
        ))

    @staticmethod
    def _metric(context: StrategyContext, key: str):
        if context.analytics is None:
            return None
        metric = context.analytics.get(key)
        if metric is None or metric.status is not AnalyticsStatus.AVAILABLE:
            return None
        return metric.value

    def _sync_date(self, date_str: str) -> None:
        if self.state.active_date is not None and self.state.active_date != date_str:
            self.reset()
        if self.state.active_date is None:
            self.state = replace(self.state, active_date=date_str)

    def target_overnight_insurance_qty(self, active_sell_qty: int) -> int:
        return max(1, int(Decimal(active_sell_qty) * Decimal("0.5")))

    def evaluate_overnight_insurance(self, context: StrategyContext) -> Sequence[Signal]:
        date_str = context.input.common.date_str if context.input and context.input.common else None
        if not date_str:
            return ()
        self._sync_date(date_str)
        active_sell = self._metric(context, "portfolio.active_sell_qty")
        insurance_qty = self._metric(context, "portfolio.insurance_qty")
        target = self.target_overnight_insurance_qty(int(active_sell)) if active_sell is not None else None
        put = self._metric(context, "options.atm_put_strike")
        call = self._metric(context, "options.atm_call_strike")
        multiplier = self._metric(context, "options.contract_multiplier")
        if target is None or insurance_qty is None or put is None or call is None or multiplier is None:
            return ()
        if multiplier <= 0:
            return ()
        diff = target - int(insurance_qty)
        if diff == 0:
            return (Signal(self.strategy_id, "HOLD_INSURANCE", 1.0, f"TARGET_QTY:{target}"),)
        if diff < 0:
            return (Signal(self.strategy_id, "REDUCE_INSURANCE", 1.0, f"TARGET_QTY:{target};DIFF:{abs(diff)}"),)
        return (
            Signal(
                self.strategy_id, "ADD_INSURANCE", 1.0,
                f"TARGET_QTY:{target};DIFF:{diff};PUT:{put};CALL:{call};MULTIPLIER:{multiplier}",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=diff, asset_type="OPTION", side="BUY",
                    track_id=self.strategy_id, tag_id="OVERNIGHT_INSURANCE_ADD_PUT",
                    option_type="PUT", strike=put,
                ),
            ),
        )

    def evaluate_early_profit_take(self, context: StrategyContext) -> Sequence[Signal]:
        if self.state.early_profit_take_executed_today:
            return ()
        common = context.input.common if context.input else None
        if common is None or common.time_str is None:
            return ()
        insurance_qty = self._metric(context, "portfolio.insurance_qty")
        if insurance_qty is None:
            return ()
        if "09:00:00" <= common.time_str <= "09:05:00" and insurance_qty > 0:
            qty = max(1, int(Decimal(str(insurance_qty)) * self.early_profit_take_ratio))
            self.state = replace(
                self.state,
                early_profit_take_executed_today=True,
                state="EARLY_PROFIT_TAKEN",
            )
            return (Signal(
                self.strategy_id, "EARLY_PROFIT_TAKE", 1.0,
                f"QTY:{qty};RATIO:{self.early_profit_take_ratio};PRICING:PREEMPTIVE_LIMIT_OR_MARKET",
            ),)
        if common.time_str > "09:05:00" and not self.state.early_profit_take_executed_today:
            self.state = replace(self.state, state="MARKET_STABILIZATION_MONITORING")
        return ()

    def evaluate_reentry(self, context: StrategyContext) -> Sequence[Signal]:
        common = context.input.common if context.input else None
        if common is None or common.time_str is None or common.time_str < "09:30:00":
            return ()
        if self.state.reentry_executed_today:
            return ()
        market_stable = self._metric(context, "market.stable")
        target_qty = self._metric(context, "portfolio.target_qty")
        existing_qty = self._metric(context, "portfolio.existing_qty")
        if market_stable is not True or target_qty is None or existing_qty is None:
            return ()
        if target_qty <= existing_qty:
            return ()
        put = self._metric(context, "options.atm_put_strike")
        call = self._metric(context, "options.atm_call_strike")
        if put is None or call is None:
            return ()
        qty = int(target_qty - existing_qty)
        self.state = replace(self.state, reentry_executed_today=True, state="REHEDGE_ACTIVE")
        return (Signal(
            self.strategy_id, "REHEDGE_ENTRY", 1.0,
            f"QTY:{qty};PUT:{put};CALL:{call};PRICING:MID_PRICE_OFFSET;MULTI_LEG_AUTHORITATIVE",
        ),)

    def evaluate_event_volatility(self, context: StrategyContext) -> Sequence[Signal]:
        common = context.input.common if context.input else None
        date_str = common.date_str if common else None
        if not date_str:
            return ()
        self._sync_date(date_str)
        upcoming = self._metric(context, "events.upcoming")
        spike = self._metric(context, "options.iv_spike")
        crush = self._metric(context, "options.iv_crush")
        budget = self._metric(context, "portfolio.event_budget")
        estimated_cost = self._metric(context, "portfolio.estimated_event_cost")
        if upcoming is None or spike is None or crush is None:
            return ()
        if not self.state.event_active:
            if not (upcoming or spike >= self.EVENT_IV_SPIKE):
                return ()
            if budget is None or estimated_cost is None:
                return ()
            if estimated_cost > budget:
                return (Signal(
                    self.strategy_id, "EVENT_BUDGET_BLOCKED", 1.0,
                    f"BUDGET:{budget};COST:{estimated_cost}",
                ),)
            net_pnl = self._metric(context, "portfolio.net_pnl")
            if net_pnl is None:
                return ()
            self.state = replace(
                self.state, event_active=True,
                event_high_pnl=max(Decimal("0"), Decimal(str(net_pnl))),
                state="EVENT_ACTIVE",
            )
            return (Signal(
                self.strategy_id, "ENTER_EVENT_STRANGLE", 1.0,
                f"EVENT:{upcoming};IV_SPIKE:{spike};PRICING:MID_PRICE_OFFSET;QTY_REQUIRES_AUTHORITATIVE_SELECTION",
            ),)
        net_pnl = self._metric(context, "portfolio.net_pnl")
        premium = self._metric(context, "portfolio.premium_spent")
        if net_pnl is None or premium is None or premium <= 0:
            return ()
        high = max(self.state.event_high_pnl, Decimal(str(net_pnl)))
        pnl_ratio = high / Decimal(str(premium))
        trailing_ratio = Decimal("0.90") if pnl_ratio >= 2 else Decimal("0.88") if pnl_ratio >= Decimal("1.3") else Decimal("0.85")
        if high > Decimal("50000") and Decimal(str(net_pnl)) <= high * trailing_ratio:
            self.state = replace(self.state, event_active=False, state="EVENT_TRAILING_STOP")
            return (Signal(
                self.strategy_id, "CLOSE_EVENT_STRANGLE", 1.0,
                f"TRAILING_STOP;HIGH:{high};RATIO:{trailing_ratio}",
            ),)
        if crush <= self.VOL_CRUSH:
            self.state = replace(self.state, event_active=False, state="EVENT_CLOSED")
            return (Signal(
                self.strategy_id, "CLOSE_EVENT_STRANGLE", 1.0,
                f"VOL_CRUSH:{crush};PRICING:MID_PRICE_OFFSET",
            ),)
        self.state = replace(self.state, event_high_pnl=high)
        return ()

    def evaluate_expiry_cutoff(self, context: StrategyContext) -> Sequence[Signal]:
        if not self.state.event_active:
            return ()
        common = context.input.common if context.input else None
        if common is None or common.time_str is None:
            return ()
        if "15:15:00" <= common.time_str < "15:20:00":
            return (Signal(self.strategy_id, "CANCEL_PENDING_TRANCHES", 1.0, "15:15_CANCEL_PENDING_TRANCHES"),)
        return ()

    def evaluate_dynamic_profit_rebuild(self, context: StrategyContext) -> Sequence[Signal]:
        risk_guard = self._metric(context, "risk.guard_active")
        margin_ratio = self._metric(context, "portfolio.margin_ratio")
        net_pnl = self._metric(context, "portfolio.net_pnl")
        if risk_guard is None or margin_ratio is None or net_pnl is None:
            return ()
        if risk_guard or margin_ratio > Decimal("0.85") or net_pnl < self.profit_target:
            return ()
        call = self._metric(context, "options.atm_call_strike")
        put = self._metric(context, "options.atm_put_strike")
        multiplier = self._metric(context, "options.contract_multiplier")
        insurance_qty = self._metric(context, "portfolio.insurance_qty")
        if call is None or put is None or multiplier is None or insurance_qty is None:
            return ()
        qty = max(int(insurance_qty), 1)
        self.state = replace(self.state, reentry_executed_today=True, state="REHEDGE_ACTIVE")
        return (
            Signal(self.strategy_id, "DYNAMIC_PROFIT_TAKE", 1.0, f"NET_PNL:{net_pnl};QTY:{qty}"),
            Signal(self.strategy_id, "DYNAMIC_REBUILD_FENCE", 1.0,
                   f"CALL:{call};PUT:{put};QTY:{qty};MULTIPLIER:{multiplier}"),
        )

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.analytics is None:
            return ()
        return (
            self.evaluate_overnight_insurance(context)
            + self.evaluate_early_profit_take(context)
            + self.evaluate_reentry(context)
            + self.evaluate_event_volatility(context)
            + self.evaluate_expiry_cutoff(context)
            + self.evaluate_dynamic_profit_rebuild(context)
        )


__all__ = ("Track9EventOvernightInsurance", "Track9State")
