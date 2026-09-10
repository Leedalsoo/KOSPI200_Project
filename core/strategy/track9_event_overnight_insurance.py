"""Track9 Event Overnight Insurance strategy."""
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext, StrategyInput
from core.strategy.multi_leg_plan import build_pair_plan
from contracts.types import MultiLegExecutionPlan


@dataclass(frozen=True)
class Track9MarketInput:
    strategy_id: str
    current_price: Decimal
    active_sell_qty: int
    current_insurance_qty: int
    date_str: str
    time_str: str = "09:00:00"
    is_event_upcoming: bool = False
    iv_spike: Decimal = Decimal("0")
    iv_crush: Decimal = Decimal("0")
    current_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    premium_spent: Decimal = Decimal("250000")
    target_insurance_qty: int | None = None
    market_stable: bool = True
    target_qty: int = 0
    existing_qty: int = 0
    margin_ratio: Decimal = Decimal("0")
    risk_guard_active: bool = False
    event_budget: Decimal = Decimal("0")
    estimated_event_cost: Decimal = Decimal("0")


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
    version = "1.0"
    STRIKE_OFFSET = Decimal("15")
    PREMIUM_COST = Decimal("0.15")
    EVENT_IV_SPIKE = Decimal("4")
    VOL_CRUSH = Decimal("-3")
    PROFIT_TARGET = Decimal("400000")

    def __init__(
        self,
        strike_offset: Decimal = STRIKE_OFFSET,
        early_profit_take_ratio: Decimal = Decimal("0.90"),
        profit_target: Decimal = PROFIT_TARGET,
    ) -> None:
        self.strike_offset = strike_offset
        self.early_profit_take_ratio = early_profit_take_ratio
        self.profit_target = profit_target
        self.state = Track9State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track9State()

    def _sync_date(self, date_str: str) -> None:
        if self.state.active_date is not None and self.state.active_date != date_str:
            self.reset()
        if self.state.active_date is None:
            self.state = replace(self.state, active_date=date_str)

    @staticmethod
    def atm_strike(price: Decimal) -> Decimal:
        return (price / Decimal("2.5")).to_integral_value() * Decimal("2.5")

    def target_overnight_insurance_qty(self, active_sell_qty: int) -> int:
        return max(1, int(Decimal(active_sell_qty) * Decimal("0.5")))

    def build_pair_execution_plan(self, group_id: str, purpose: str, current_price: Decimal, quantity: int) -> MultiLegExecutionPlan:
        atm = self.atm_strike(current_price)
        return build_pair_plan(
            group_id=group_id, strategy_id=self.strategy_id, purpose=purpose,
            put_strike=atm - self.strike_offset, call_strike=atm + self.strike_offset,
            put_quantity=quantity, call_quantity=quantity, side="BUY",
        )

    def evaluate_overnight_insurance(self, data: Track9MarketInput) -> Sequence[Signal]:
        self._sync_date(data.date_str)
        target = (
            data.target_insurance_qty
            if data.target_insurance_qty is not None
            else self.target_overnight_insurance_qty(data.active_sell_qty)
        )
        diff = target - data.current_insurance_qty
        if diff == 0:
            return (Signal(self.strategy_id, "HOLD_INSURANCE", 1.0, f"TARGET_QTY:{target}"),)

        if diff > 0:
            atm = self.atm_strike(data.current_price)
            return (
                Signal(
                    self.strategy_id,
                    "ADD_INSURANCE",
                    1.0,
                    f"TARGET_QTY:{target};DIFF:{diff};"
                    f"PUT:{atm-self.strike_offset};CALL:{atm+self.strike_offset};"
                    "PRICING:MID_PRICE_OFFSET;TICK:1;FALLBACK_SEC:2",
                ),
            )
        return (
            Signal(
                self.strategy_id,
                "REDUCE_INSURANCE",
                1.0,
                f"TARGET_QTY:{target};DIFF:{abs(diff)}",
            ),
        )

    def evaluate_early_profit_take(self, data: Track9MarketInput) -> Sequence[Signal]:
        if self.state.early_profit_take_executed_today:
            return ()
        if "09:00:00" <= data.time_str <= "09:05:00" and data.current_insurance_qty > 0:
            qty = max(1, int(Decimal(data.current_insurance_qty) * self.early_profit_take_ratio))
            self.state = replace(
                self.state,
                early_profit_take_executed_today=True,
                state="EARLY_PROFIT_TAKEN",
            )
            return (
                Signal(
                    self.strategy_id,
                    "EARLY_PROFIT_TAKE",
                    1.0,
                    f"QTY:{qty};RATIO:{self.early_profit_take_ratio};"
                    "PRICING:PREEMPTIVE_LIMIT_OR_MARKET",
                ),
            )
        if data.time_str > "09:05:00" and not self.state.early_profit_take_executed_today:
            self.state = replace(self.state, state="MARKET_STABILIZATION_MONITORING")
        return ()

    def evaluate_reentry(self, data: Track9MarketInput) -> Sequence[Signal]:
        if data.time_str < "09:30:00" or self.state.reentry_executed_today:
            return ()
        if data.market_stable and data.target_qty > data.existing_qty:
            qty = data.target_qty - data.existing_qty
            atm = self.atm_strike(data.current_price)
            self.state = replace(
                self.state,
                reentry_executed_today=True,
                state="REHEDGE_ACTIVE",
            )
            return (
                Signal(
                    self.strategy_id,
                    "REHEDGE_ENTRY",
                    1.0,
                    f"QTY:{qty};PUT:{atm-self.strike_offset};CALL:{atm+self.strike_offset};"
                    "PRICING:MID_PRICE_OFFSET;TICK:1",
                ),
            )
        return ()

    def evaluate_event_volatility(self, data: Track9MarketInput) -> Sequence[Signal]:
        self._sync_date(data.date_str)
        net_pnl = data.current_pnl - data.total_fees

        if not self.state.event_active:
            if not (data.is_event_upcoming or data.iv_spike >= self.EVENT_IV_SPIKE):
                return ()
            if data.event_budget > 0 and data.estimated_event_cost > data.event_budget:
                return (
                    Signal(
                        self.strategy_id,
                        "EVENT_BUDGET_BLOCKED",
                        1.0,
                        f"BUDGET:{data.event_budget};COST:{data.estimated_event_cost}",
                    ),
                )
            self.state = replace(
                self.state,
                event_active=True,
                event_high_pnl=max(Decimal("0"), net_pnl),
                state="EVENT_ACTIVE",
            )
            return (
                Signal(
                    self.strategy_id,
                    "ENTER_EVENT_STRANGLE",
                    1.0,
                    f"EVENT:{data.is_event_upcoming};IV_SPIKE:{data.iv_spike};"
                    "PRICING:MID_PRICE_OFFSET;TICK:1;FALLBACK_SEC:2;QTY:1",
                ),
            )

        high = max(self.state.event_high_pnl, net_pnl)
        spent = max(Decimal("1"), data.premium_spent)
        pnl_ratio = high / spent
        trailing_ratio = (
            Decimal("0.90") if pnl_ratio >= Decimal("2")
            else Decimal("0.88") if pnl_ratio >= Decimal("1.3")
            else Decimal("0.85")
        )

        if high > Decimal("50000") and net_pnl <= high * trailing_ratio:
            self.state = replace(self.state, event_active=False, state="EVENT_TRAILING_STOP")
            return (
                Signal(
                    self.strategy_id,
                    "CLOSE_EVENT_STRANGLE",
                    1.0,
                    f"TRAILING_STOP;HIGH:{high};RATIO:{trailing_ratio};"
                    "PRICING:PREEMPTIVE_STOP_LIMIT_QUEUE;OFFSET_TICKS:2",
                ),
            )

        if data.iv_crush <= self.VOL_CRUSH:
            self.state = replace(self.state, event_active=False, state="EVENT_CLOSED")
            return (
                Signal(
                    self.strategy_id,
                    "CLOSE_EVENT_STRANGLE",
                    1.0,
                    f"VOL_CRUSH:{data.iv_crush};PRICING:MID_PRICE_OFFSET;TICK:1",
                ),
            )

        self.state = replace(self.state, event_active=True, event_high_pnl=high)
        return ()

    def evaluate_dynamic_profit_rebuild(self, data: Track9MarketInput) -> Sequence[Signal]:
        if data.risk_guard_active or data.margin_ratio > Decimal("0.85"):
            return ()
        net_pnl = data.current_pnl - data.total_fees
        if net_pnl < self.profit_target:
            return ()

        call = self.atm_strike(data.current_price) + self.strike_offset
        put = self.atm_strike(data.current_price) - self.strike_offset
        qty = max(data.current_insurance_qty, data.target_qty, 1)
        self.state = replace(self.state, reentry_executed_today=True, state="REHEDGE_ACTIVE")
        return (
            Signal(
                self.strategy_id,
                "DYNAMIC_PROFIT_TAKE",
                1.0,
                f"NET_PNL:{net_pnl};QTY:{qty};TIME:{data.time_str}",
            ),
            Signal(
                self.strategy_id,
                "DYNAMIC_REBUILD_FENCE",
                1.0,
                f"CALL:{call};PUT:{put};QTY:{qty}",
            ),
        )

    def evaluate_input(self, data: Track9MarketInput) -> Sequence[Signal]:
        signals: list[Signal] = []
        signals.extend(self.evaluate_overnight_insurance(data))
        signals.extend(self.evaluate_early_profit_take(data))
        signals.extend(self.evaluate_reentry(data))
        signals.extend(self.evaluate_event_volatility(data))
        signals.extend(self.evaluate_dynamic_profit_rebuild(data))
        return tuple(signals)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id:
            return ()
        data = context.input.payload
        if not isinstance(data, Track9MarketInput):
            return ()
        if data.strategy_id != self.strategy_id:
            return ()
        return self.evaluate_input(data)
