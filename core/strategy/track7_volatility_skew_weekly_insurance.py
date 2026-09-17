from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext


@dataclass(frozen=True)
class Track7MarketInput:
    strategy_id: str
    current_price: Decimal
    budget: Decimal
    date_str: str
    is_new_week_start: bool
    active_vol: Decimal
    call_iv: Decimal | None = None
    put_iv: Decimal | None = None
    skew_limit_timeout: bool = False
    ma_1m: Decimal | None = None
    ma_3m: Decimal | None = None
    ma_5m: Decimal | None = None
    ma_10m: Decimal | None = None
    support: Decimal | None = None
    resistance: Decimal | None = None
    time_str: str = "09:00:00"
    is_expiry_day: bool = False
    is_week_end: bool = False


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
    STRIKE_OFFSET = Decimal("15.0")
    INSURANCE_QTY = 1
    MULTIPLIER = Decimal("250000")
    SKEW_ENTRY = Decimal("3.0")
    SKEW_STOP = Decimal("8.0")
    SKEW_EXIT = Decimal("0.5")
    FALLBACK_TIMEOUT_SEC = Decimal("5.0")

    def __init__(self, strike_offset: Decimal = STRIKE_OFFSET, insurance_qty: int = INSURANCE_QTY, expiry_mode: str = "D-0 CUTOFF") -> None:
        self.strike_offset = strike_offset
        self.insurance_qty = insurance_qty
        self.expiry_mode = expiry_mode
        self.state = Track7State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track7State()

    @staticmethod
    def atm_strike(price: Decimal) -> Decimal:
        return (price / Decimal("2.5")).to_integral_value() * Decimal("2.5")

    def insurance_cost(self, active_vol: Decimal) -> Decimal:
        vol_scale = Decimal("0.5") if active_vol < Decimal("1") else Decimal("1")
        return Decimal("1.4") * self.MULTIPLIER * self.insurance_qty * vol_scale

    def evaluate_insurance_buy(self, data: Track7MarketInput) -> Sequence[Signal]:
        if data.date_str != self.state.bought_date and self.state.bought_date is not None:
            self.reset()
        if self.state.insurance_active:
            return ()
        if "15:15" <= data.time_str < "15:20":
            return (Signal(self.strategy_id, "CANCEL", 1.0, "CANCEL_PENDING_TRANCHES_15:15"),)
        if not data.is_new_week_start:
            return ()
        cost = self.insurance_cost(data.active_vol)
        if data.budget < cost:
            return ()
        atm = self.atm_strike(data.current_price)
        put_strike = atm - self.strike_offset
        call_strike = atm + self.strike_offset
        self.state = replace(self.state, insurance_active=True, bought_date=data.date_str, put_strike=put_strike, call_strike=call_strike, premium_spent=cost)
        return (Signal(self.strategy_id, "BUY_LIMIT_WEEKLY_INSURANCE", 1.0, f"PUT:{put_strike};CALL:{call_strike};QTY:{self.insurance_qty};PRICING:MID_PRICE_OFFSET;TICK_OFFSET:1;FALLBACK_TIMEOUT_SEC:{self.FALLBACK_TIMEOUT_SEC};COST:{cost}"),)

    def evaluate_skew_arbitrage(self, data: Track7MarketInput) -> Sequence[Signal]:
        if data.call_iv is None or data.put_iv is None:
            return ()
        skew = data.put_iv - data.call_iv
        if not self.state.skew_active:
            if abs(skew) < self.SKEW_ENTRY:
                return ()
            self.state = replace(self.state, skew_active=True, skew_limit_pending=True)
            direction = "LONG_PUT_SHORT_CALL" if skew > 0 else "LONG_CALL_SHORT_PUT"
            return (Signal(self.strategy_id, "ENTER_SKEW_ARB_LIMIT", 1.0, f"TYPE:{direction};SKEW:{skew};QTY:1"),)
        if self.state.skew_limit_pending and data.skew_limit_timeout:
            self.state = replace(self.state, skew_limit_pending=False)
            return (Signal(self.strategy_id, "ENTER_SKEW_ARB_FALLBACK_MARKET", 1.0, f"SKEW:{skew};TIMEOUT_SEC:{self.FALLBACK_TIMEOUT_SEC};QTY:1"),)
        if abs(skew) > self.SKEW_STOP:
            self.state = replace(self.state, skew_active=False, skew_limit_pending=False)
            return (Signal(self.strategy_id, "CLOSE_SKEW_ARB_STOP_LOSS", 1.0, f"SKEW:{skew};STOP:{self.SKEW_STOP};QTY:1"),)
        if abs(skew) <= self.SKEW_EXIT:
            self.state = replace(self.state, skew_active=False, skew_limit_pending=False)
            return (Signal(self.strategy_id, "CLOSE_SKEW_ARB_LIMIT", 1.0, f"SKEW:{skew};EXIT:{self.SKEW_EXIT};QTY:1"),)
        return ()

    def evaluate_preemptive_take_profit(self, data: Track7MarketInput) -> Sequence[Signal]:
        required = (data.ma_1m, data.ma_3m, data.ma_5m, data.ma_10m)
        if any(value is None for value in required):
            return ()
        bullish_cross = data.ma_1m > data.ma_3m > data.ma_5m > data.ma_10m
        bearish_cross = data.ma_1m < data.ma_3m < data.ma_5m < data.ma_10m
        near_resistance = data.resistance is not None and data.current_price >= data.resistance
        near_support = data.support is not None and data.current_price <= data.support
        if bullish_cross or bearish_cross or near_resistance or near_support:
            return (Signal(self.strategy_id, "PREEMPTIVE_LIMIT_TAKE_PROFIT", 0.8, f"MA_CROSS:{bullish_cross or bearish_cross};SUPPORT:{data.support};RESISTANCE:{data.resistance};PRICE:{data.current_price}"),)
        return ()

    def evaluate_expiry_cutoff(self, data: Track7MarketInput) -> Sequence[Signal]:
        if not self.state.insurance_active:
            return ()
        if self.expiry_mode == "D-4" and self.state.bought_date == data.date_str and data.time_str >= "15:00:00":
            self.reset()
            return (Signal(self.strategy_id, "CLOSE_WEEKLY_INSURANCE_PREEMPTIVE_D4", 1.0, "D4_PREEMPTIVE_CUTOFF"),)
        expiry_active = data.is_expiry_day or data.is_week_end
        if not expiry_active:
            return ()
        if "15:00:00" <= data.time_str < "15:15:00":
            return (Signal(self.strategy_id, "CLOSE_WEEKLY_INSURANCE_LIMIT", 1.0, "15:00_LIMIT_CUTOFF"),)
        if data.time_str >= "15:15:00":
            self.reset()
            return (Signal(self.strategy_id, "CLOSE_WEEKLY_INSURANCE_FALLBACK_MARKET", 1.0, "15:15_FALLBACK_MARKET"),)
        return ()

    def evaluate_input(self, data: Track7MarketInput) -> Sequence[Signal]:
        if self.state.insurance_active:
            cutoff = self.evaluate_expiry_cutoff(data)
            if cutoff:
                return cutoff
        signals: list[Signal] = []
        if not self.state.insurance_active:
            signals.extend(self.evaluate_insurance_buy(data))
        signals.extend(self.evaluate_skew_arbitrage(data))
        if self.state.insurance_active:
            signals.extend(self.evaluate_preemptive_take_profit(data))
        return tuple(signals)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        strategy_input = getattr(context, "input", None)
        data = getattr(strategy_input, "payload", None)
        if not isinstance(data, Track7MarketInput):
            return ()
        if getattr(context, "strategy_id", None) != self.strategy_id:
            return ()
        if data.strategy_id != self.strategy_id:
            return ()
        return self.evaluate_input(data)
