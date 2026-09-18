from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext, StrategyInput
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.multi_leg_plan import build_pair_plan
from contracts.types import MultiLegExecutionPlan


@dataclass(frozen=True)
class Track8MarketInput:
    strategy_id: str
    dte: Decimal
    budget: Decimal
    current_price: Decimal
    current_regime: str
    date_str: str
    current_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    time_str: str = "09:00:00"
    active_vol: Decimal = Decimal("1")
    margin_ratio: Decimal = Decimal("0")
    risk_guard_active: bool = False


@dataclass(frozen=True)
class Track8State:
    is_active: bool = False
    premium_spent: Decimal = Decimal("0")
    call_strike: Decimal = Decimal("0")
    put_strike: Decimal = Decimal("0")
    qty_call: int = 0
    qty_put: int = 0
    entry_date: str | None = None
    high_watermark_intrinsic: Decimal = Decimal("0")
    trailing_stop_active: bool = False
    hysteresis_hold_counter: int = 0


class Track8MacroRegimeMonthlyStrangle:
    strategy_id = "track8_macro_regime_monthly_strangle"
    version = "1.0"
    MIN_BUDGET = Decimal("200000")
    DTE_ENTRY = Decimal("15")
    STRIKE_OFFSET = Decimal("15")
    MULTIPLIER = Decimal("250000")
    PROFIT_TARGET = Decimal("300000")

    def __init__(self, profit_target: Decimal = PROFIT_TARGET) -> None:
        self.profit_target = profit_target
        self.state = Track8State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track8State()

    @staticmethod
    def atm_strike(price: Decimal) -> Decimal:
        return (price / Decimal("2.5")).to_integral_value() * Decimal("2.5")

    def evaluate_entry(self, data: Track8MarketInput) -> Sequence[Signal]:
        if self.state.entry_date is not None and self.state.entry_date != data.date_str:
            self.reset()
        if self.state.is_active:
            return ()
        if data.dte < self.DTE_ENTRY or data.budget < self.MIN_BUDGET:
            return ()

        skew_ratio = Decimal("2") if data.current_regime == "HIGH_VOL" else Decimal("1.5")
        atm = self.atm_strike(data.current_price)
        call_strike = atm + self.STRIKE_OFFSET
        put_strike = atm - self.STRIKE_OFFSET
        unit_cost = (Decimal("1.20") + skew_ratio * Decimal("1.50")) * self.MULTIPLIER
        base_qty = max(1, int(data.budget / max(Decimal("1"), unit_cost)))
        qty_call = base_qty
        qty_put = int(Decimal(base_qty) * skew_ratio)
        estimated_cost = (Decimal(qty_call) * Decimal("1.20") + Decimal(qty_put) * Decimal("1.50")) * self.MULTIPLIER
        if data.budget < estimated_cost:
            return ()

        self.state = replace(
            self.state,
            is_active=True,
            premium_spent=estimated_cost,
            call_strike=call_strike,
            put_strike=put_strike,
            qty_call=qty_call,
            qty_put=qty_put,
            entry_date=data.date_str,
        )
        return (
            Signal(
                self.strategy_id,
                "BUY_LIMIT_TRANCHE",
                1.0,
                f"DTE:{data.dte};CALL:{call_strike};PUT:{put_strike};QTY_CALL:{qty_call};QTY_PUT:{qty_put};PRICING:MID_PRICE_OFFSET;TICK:1;FALLBACK_SEC:5",
                execution_proposal=StrategyExecutionProposal(
                    proposed_quantity=qty_call,
                    asset_type="OPTION",
                    side="BUY",
                    track_id=self.strategy_id,
                    tag_id="MONTHLY_STRANGLE_ENTRY_CALL",
                    option_type="CALL",
                    strike=call_strike,
                ),
            ),
        )

    def build_execution_plan(self, group_id: str) -> MultiLegExecutionPlan | None:
        if not self.state.is_active or self.state.call_strike <= 0 or self.state.put_strike <= 0:
            return None
        return build_pair_plan(
            group_id=group_id, strategy_id=self.strategy_id, purpose="MONTHLY_STRANGLE_ENTRY",
            put_strike=self.state.put_strike, call_strike=self.state.call_strike,
            put_quantity=self.state.qty_put, call_quantity=self.state.qty_call, side="BUY",
        )

    def evaluate_take_profit(self, data: Track8MarketInput) -> Sequence[Signal]:
        if not self.state.is_active:
            return ()

        qty = max(self.state.qty_call, self.state.qty_put, 1)
        put_intrinsic = max(Decimal("0"), self.state.put_strike - data.current_price) * self.MULTIPLIER * qty
        call_intrinsic = max(Decimal("0"), data.current_price - self.state.call_strike) * self.MULTIPLIER * qty
        intrinsic = put_intrinsic + call_intrinsic
        min_multiplier = Decimal("1.8") if data.active_vol < Decimal("1.3") else Decimal("2.5")

        if intrinsic < self.state.premium_spent * min_multiplier:
            return ()

        prev_high = self.state.high_watermark_intrinsic
        high = max(prev_high, intrinsic)
        pnl_ratio = high / max(Decimal("1"), self.state.premium_spent)
        ratio = (
            Decimal("0.90") if pnl_ratio >= Decimal("2")
            else Decimal("0.88") if pnl_ratio >= Decimal("1.3")
            else Decimal("0.85")
        )
        stop = high * ratio

        if intrinsic <= stop:
            self.reset()
            return (
                Signal(
                    self.strategy_id,
                    "TAKE_PROFIT_HYBRID_TRAILING_STOP",
                    1.0,
                    f"REALIZED:{intrinsic};HIGH:{high};RATIO:{ratio}",
                ),
            )

        self.state = replace(
            self.state,
            trailing_stop_active=True,
            high_watermark_intrinsic=high,
        )
        if prev_high == 0 or high >= prev_high * Decimal("1.01"):
            return (
                Signal(
                    self.strategy_id,
                    "UPDATE_TRAILING",
                    0.9,
                    f"HIGH:{high};STOP:{stop};OFFSET_TICKS:2;FALLBACK_SEC:2",
                ),
            )
        return ()

    def evaluate_macro_regime_protection(self, data: Track8MarketInput) -> Sequence[Signal]:
        if data.current_regime in {"HIGH_VOL", "CIRCUIT_BREAKER", "CRASH"}:
            return (
                Signal(
                    self.strategy_id,
                    "MACRO_HEDGE_SCALE_UP",
                    1.0,
                    f"REGIME:{data.current_regime};HEDGE_MULTIPLIER:1.5",
                ),
            )
        return ()

    def evaluate_profit_rebuild(self, data: Track8MarketInput) -> Sequence[Signal]:
        if not self.state.is_active:
            return ()
        if data.risk_guard_active or data.margin_ratio > Decimal("0.85"):
            return ()

        net_pnl = data.current_pnl - data.total_fees
        if net_pnl < self.profit_target:
            return ()

        old_call, old_put = self.state.call_strike, self.state.put_strike
        atm = self.atm_strike(data.current_price)
        new_call, new_put = atm + self.STRIKE_OFFSET, atm - self.STRIKE_OFFSET
        qty = max(self.state.qty_call, self.state.qty_put, 1)

        self.state = replace(
            self.state,
            is_active=True,
            call_strike=new_call,
            put_strike=new_put,
            high_watermark_intrinsic=Decimal("0"),
            trailing_stop_active=False,
        )
        return (
            Signal(
                self.strategy_id,
                "DYNAMIC_PROFIT_TAKE",
                1.0,
                f"OLD_CALL:{old_call};OLD_PUT:{old_put};NET_PNL:{net_pnl}",
            ),
            Signal(
                self.strategy_id,
                "DYNAMIC_REBUILD_FENCE",
                1.0,
                f"CALL:{new_call};PUT:{new_put};QTY:{qty}",
            ),
        )

    def evaluate_expiry_cutoff(self, data: Track8MarketInput) -> Sequence[Signal]:
        if not self.state.is_active:
            return ()

        if "15:15" <= data.time_str < "15:20":
            return (
                Signal(
                    self.strategy_id,
                    "CANCEL_PENDING_TRANCHES",
                    1.0,
                    "15:15_CANCEL_PENDING_TRANCHES",
                ),
            )

        if data.dte > Decimal("4"):
            return ()

        call_k, put_k = self.state.call_strike, self.state.put_strike
        near_call = call_k > 0 and abs(data.current_price - call_k) / max(Decimal("1"), call_k) <= Decimal("0.03")
        near_put = put_k > 0 and abs(data.current_price - put_k) / max(Decimal("1"), put_k) <= Decimal("0.03")
        iv_expanded = data.active_vol >= Decimal("1.5")

        if near_call or near_put or iv_expanded:
            self.state = replace(
                self.state,
                hysteresis_hold_counter=self.state.hysteresis_hold_counter + 1,
            )
            return (
                Signal(
                    self.strategy_id,
                    "HOLD_LONG_ATTACK",
                    0.9,
                    "D4_D0_MONEYNESS_OR_IV_EXPANSION",
                ),
            )

        if self.state.hysteresis_hold_counter > 0:
            self.state = replace(
                self.state,
                hysteresis_hold_counter=self.state.hysteresis_hold_counter - 1,
            )
            return (
                Signal(
                    self.strategy_id,
                    "HOLD_HYSTERESIS",
                    0.8,
                    "TIME_WEIGHTED_HYSTERESIS",
                ),
            )

        spent, qty_call, qty_put = (
            self.state.premium_spent,
            self.state.qty_call,
            self.state.qty_put,
        )
        self.reset()
        return (
            Signal(
                self.strategy_id,
                "FLAT_STRANGLE",
                1.0,
                f"DTE:{data.dte};QTY_CALL:{qty_call};QTY_PUT:{qty_put};SPENT:{spent}",
            ),
        )

    def evaluate_input(self, data: Track8MarketInput) -> Sequence[Signal]:
        signals: list[Signal] = []
        signals.extend(self.evaluate_entry(data))
        signals.extend(self.evaluate_macro_regime_protection(data))
        signals.extend(self.evaluate_take_profit(data))
        signals.extend(self.evaluate_profit_rebuild(data))
        signals.extend(self.evaluate_expiry_cutoff(data))
        return tuple(signals)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id:
            return ()
        data = context.input.payload
        if not isinstance(data, Track8MarketInput):
            return ()
        if data.strategy_id != self.strategy_id:
            return ()
        return self.evaluate_input(data)
