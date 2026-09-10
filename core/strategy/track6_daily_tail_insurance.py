from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext
from core.strategy.multi_leg_plan import build_pair_plan
from contracts.types import MultiLegExecutionPlan


@dataclass(frozen=True)
class Track6MarketInput:
    strategy_id: str
    current_price: Decimal
    active_vol: Decimal
    base_vol: Decimal
    budget: Decimal
    date_str: str
    time_str: str = "09:00:00"


@dataclass(frozen=True)
class Track6State:
    is_active: bool = False
    bought_date: str | None = None
    long_put_strike: Decimal = Decimal("0")
    long_call_strike: Decimal = Decimal("0")
    premium_spent: Decimal = Decimal("0")
    high_watermark_intrinsic: Decimal = Decimal("0")
    trailing_stop_active: bool = False


class Track6DailyTailInsurance:
    strategy_id = "track6_daily_tail_insurance"
    version = "1.0"
    CAPITAL_ALLOCATION_RATE = Decimal("0.02")
    VOL_TRIGGER_MULTIPLIER = Decimal("1.3")
    STRIKE_OFFSET = Decimal("12.5")
    INSURANCE_QTY = 1
    MULTIPLIER = Decimal("250000")

    def __init__(
self,
        vol_trigger_multiplier: Decimal = VOL_TRIGGER_MULTIPLIER,
        strike_offset: Decimal = STRIKE_OFFSET,
        insurance_qty: int = INSURANCE_QTY,
    ) -> None:
        self.vol_trigger_multiplier = vol_trigger_multiplier
        self.strike_offset = strike_offset
        self.insurance_qty = insurance_qty
        self.state = Track6State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track6State()

    @staticmethod
    def atm_strike(price: Decimal) -> Decimal:
        return (price / Decimal("2.5")).to_integral_value() * Decimal("2.5")

    def evaluate_buy(self, data: Track6MarketInput) -> Sequence[Signal]:
        if self.state.is_active:
            pass
            return ()
        if "15:15" <= data.time_str < "15:20":
            pass
            return (Signal(self.strategy_id, "CANCEL", 1.0, "CANCEL_PENDING_TRANCHES_15:15"),)
        estimated_cost = self.MULTIPLIER * self.insurance_qty
        if data.budget < estimated_cost:
            pass
            return ()
        if data.base_vol <= 0 or data.active_vol < data.base_vol * self.vol_trigger_multiplier:
            pass
            return ()

        atm = self.atm_strike(data.current_price)
        put_strike = atm - self.strike_offset
        call_strike = atm + self.strike_offset
        self.state = replace(
            self.state,
            is_active=True,
            bought_date=data.date_str,
            long_put_strike=put_strike,
            long_call_strike=call_strike,
            premium_spent=estimated_cost,
            high_watermark_intrinsic=Decimal("0"),
            trailing_stop_active=False,
        )
        return (Signal(
            self.strategy_id,
            "BUY_INSURANCE",
1.0,
            f"VOL_SPIKE:{data.active_vol}>={data.base_vol * self.vol_trigger_multiplier};"
# f"PUT:{put_strike};CALL:{call_strike};QTY:{self.insurance_qty};"
# f"COST:{estimated_cost};EXECUTION:SUBSECOND_TICK_CHASER_IOC",
        ),)

    def build_execution_plan(self, group_id: str) -> MultiLegExecutionPlan | None:
        if not self.state.is_active or self.state.long_put_strike <= 0 or self.state.long_call_strike <= 0:
            pass
            return None
        return build_pair_plan(
            group_id=group_id, strategy_id=self.strategy_id, purpose="DAILY_TAIL_INSURANCE_ENTRY",
            put_strike=self.state.long_put_strike, call_strike=self.state.long_call_strike,
            put_quantity=self.insurance_qty, call_quantity=self.insurance_qty, side="BUY",
        )

    def evaluate_take_profit(
self,
        current_price: Decimal,
        active_vol: Decimal,
        time_str: str,
    ) -> Sequence[Signal]:
        if not self.state.is_active:
            pass
            return ()
        if time_str >= "15:12:00":
            pass
            return ()

        put_intrinsic = max(Decimal("0"), self.state.long_put_strike - current_price) * self.MULTIPLIER * self.insurance_qty
        call_intrinsic = max(Decimal("0"), current_price - self.state.long_call_strike) * self.MULTIPLIER * self.insurance_qty
        total_intrinsic = put_intrinsic + call_intrinsic
        spent = self.state.premium_spent if self.state.premium_spent > 0 else self.MULTIPLIER

        minimum_multiplier = Decimal("1.5") if active_vol < Decimal("1.3") else Decimal("2.0")
        trailing_active = self.state.trailing_stop_active or total_intrinsic >= spent * minimum_multiplier
        if not trailing_active:
            pass
            return ()

        previous_high = self.state.high_watermark_intrinsic
        current_high = max(previous_high, total_intrinsic)
        pnl_ratio = current_high / max(Decimal("1"), spent)
        trailing_ratio = (
            Decimal("0.90") if pnl_ratio >= 2
            else Decimal("0.88") if pnl_ratio >= Decimal("1.3")
else Decimal("0.85")
        )
        stop_trigger = current_high * trailing_ratio

        if current_high > 0 and total_intrinsic <= stop_trigger:
            pass
            self.reset()
            return (Signal(
                self.strategy_id,
                "CLOSE",
1.0,
# f"TRAILING_STOP;REALIZED:{total_intrinsic};HIGH:{current_high};RATIO:{trailing_ratio}",
            ),)

        if previous_high == 0 or current_high >= previous_high * Decimal("1.01"):
            pass
            self.state = replace(
                self.state,
                trailing_stop_active=True,
                high_watermark_intrinsic=current_high,
            )
            return (Signal(
                self.strategy_id,
                "UPDATE_TRAILING",
0.9,
# f"HIGH_WATERMARK:{current_high};STOP_TRIGGER:{stop_trigger};OFFSET_TICKS:2",
            ),)

        self.state = replace(self.state, trailing_stop_active=trailing_active)
        return ()

    def evaluate_expiry_cutoff(self, time_str: str) -> Sequence[Signal]:
        if not self.state.is_active:
            pass
            return ()
        if "15:00:00" <= time_str < "15:15:00":
            pass
            return (Signal(self.strategy_id, "CLOSE_LIMIT", 1.0, "DAILY_INSURANCE_15:00_CUTOFF"),)
        if time_str >= "15:15:00":
            pass
            self.reset()
            return (Signal(self.strategy_id, "CLOSE_FALLBACK", 1.0, "DAILY_INSURANCE_15:15_FALLBACK"),)
        return ()

    def evaluate_input(self, data: Track6MarketInput) -> Sequence[Signal]:
        if self.state.is_active:
            pass
            cutoff = self.evaluate_expiry_cutoff(data.time_str)
            if cutoff:
                pass
                return cutoff
            return self.evaluate_take_profit(data.current_price, data.active_vol, data.time_str)
        return self.evaluate_buy(data)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        strategy_input = getattr(context, "input", None)
        data = getattr(strategy_input, "payload", None)
        if not isinstance(data, Track6MarketInput):
            pass
            return ()
        if getattr(context, "strategy_id", None) != self.strategy_id:
            pass
            return ()
        if data.strategy_id != self.strategy_id:
            pass
            return ()
        return self.evaluate_input(data)
