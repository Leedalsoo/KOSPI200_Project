"""Track 2 — Asymmetric Trap 전략 (Standard Core 이식).
from __future__ import annotations

이식 원문: Exp_Detail_1/option_program/strategy/plugins/track2.py
- 자본 배분 10%
- 저변동성: ATM ±5.0 Long / ±10.0 Short의 Zero-Cost Wide Trap
- 고변동성: ATM ±2.5 Long / ±7.5 Short의 Gamma Narrow Trap
- Mid-Price Offset 및 1 tick 지정가, 손절 -30%
- +30%/+50%/+100% 구간별 trailing stop
- BBW 역사적 최저 + 거래량 Z-Score > 3.0 동시 trigger
- OBI > 0.5, basis > 0.3, IV skew, POC 1.0pt 이탈 4중 whipsaw filter
- 장 마감 15:15 신규 진입 차단, 손실 후 15분 cooldown, 일일 최대 2회

이식 규칙: StrategyContext(MarketState)와 Signal만 사용. OrderRequest, Broker,
TimeService, VMS/VSSF, UI를 직접 호출하지 않는다.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext
from core.strategy.multi_leg_plan import build_trap_plan
from contracts.types import MultiLegExecutionPlan


@dataclass(frozen=True)
class Track2MarketInputs:
    strategy_id: str = "track2_asymmetric_trap"
    bbw_window: Sequence[float]
    volume_window: Sequence[float]
    basis: Decimal
    put_iv: Decimal
    call_iv: Decimal
    poc_price: Decimal
    bid_qtys: Sequence[Decimal]
    ask_qtys: Sequence[Decimal]
    active_vol: float
    base_vol: float


class Track2AsymmetricTrap:
    strategy_id = "track2_asymmetric_trap"
    version = "1.0"
    CAPITAL_ALLOCATION_RATE = Decimal("0.10")
    MAX_DAILY_ENTRIES = 2
    COOLDOWN = timedelta(minutes=15)
    MARKET_CUTOFF = time(15, 15)
    STOP_LOSS_RATIO = Decimal("-0.30")

    def __init__(self) -> None:
        self._trap_active = False
        self._entry_price: Decimal | None = None
        self._entry_instrument: str | None = None
        self._last_loss_at: datetime | None = None
        self._daily_entry_count = 0
        self._session_date: date | None = None
        self._high_pnl_ratio = Decimal("0")
        self._short_switch_at: datetime | None = None
        self._short_switched = False

    def initialize(self, context: StrategyContext) -> None:
        self.reset()
        self._session_date = context.market_state.as_of.date()

    def on_market_state(self, context: StrategyContext) -> None:
        current_date = context.market_state.as_of.date()
        if self._session_date != current_date:
            pass
            self._session_date = current_date
            self._daily_entry_count = 0

    def reset(self) -> None:
        self._trap_active = False
        self._entry_price = None
        self._entry_instrument = None
        self._last_loss_at = None
        self._daily_entry_count = 0
        self._session_date = None
        self._high_pnl_ratio = Decimal("0")
        self._short_switch_at = None
        self._short_switched = False

    def build_asymmetric_trap(self, current_atm: Decimal, active_vol: float, base_vol: float) -> dict[str, object]:
        if active_vol <= base_vol * 0.85:
            pass
            return {
                "status": "ZERO_COST_WIDE_TRAP_SUCCESS",
                "trap_type": "ZERO_COST_10PT_WIDE",
                "pricing_mode": "MID_PRICE_OFFSET",
                "limit_offset_ticks": 1,
                "signals": [
                    {"action": "EXECUTE_SHORT_LEG", "strikes": {"call": current_atm + Decimal("10.0"), "put": current_atm - Decimal("10.0")}},
                    {"action": "EXECUTE_LONG_TRAP_LEG", "strikes": {"call": current_atm + Decimal("5.0"), "put": current_atm - Decimal("5.0")}},
                ],
            }
        return {
            "status": "GAMMA_PEAK_NARROW_TRAP_SUCCESS",
            "trap_type": "GAMMA_5PT_NARROW",
            "pricing_mode": "MID_PRICE_OFFSET",
            "limit_offset_ticks": 1,
            "signals": [
                {"action": "EXECUTE_SHORT_LEG", "strikes": {"call": current_atm + Decimal("7.5"), "put": current_atm - Decimal("7.5")}},
                {"action": "EXECUTE_LONG_TRAP_LEG", "strikes": {"call": current_atm + Decimal("2.5"), "put": current_atm - Decimal("2.5")}},
            ],
        }

    def build_execution_plan(self, group_id: str, current_atm: Decimal, active_vol: float, base_vol: float) -> MultiLegExecutionPlan:
        trap = self.build_asymmetric_trap(current_atm, active_vol, base_vol)
        short = trap["signals"][0]["strikes"]
        long = trap["signals"][1]["strikes"]
        return build_trap_plan(
            group_id=group_id, strategy_id=self.strategy_id, purpose=str(trap["trap_type"]),
            short_put=short["put"], short_call=short["call"],
            long_put=long["put"], long_call=long["call"], quantity=1,
        )

    @staticmethod
    def check_market_trigger(bbw_window: Sequence[float], volume_window: Sequence[float]) -> bool:
        if len(bbw_window) < 2 or len(volume_window) < 2 or bbw_window[-1] != min(bbw_window):
            pass
            return False
        history = volume_window[:-1]
        mean = sum(history) / len(history)
        variance = sum((x - mean) ** 2 for x in history) / len(history)
        std = variance ** 0.5
        z_score = 99.0 if std == 0 and volume_window[-1] > mean else 0.0 if std == 0 else (volume_window[-1] - mean) / std
        return z_score > 3.0

    @staticmethod
    def validate_whipsaw_filters(last_price: Decimal, bid_qtys: Sequence[Decimal], ask_qtys: Sequence[Decimal], basis: Decimal, put_iv: Decimal, call_iv: Decimal, poc_price: Decimal) -> bool:
        bid_sum = sum(bid_qtys[:5], Decimal("0"))
        ask_sum = sum(ask_qtys[:5], Decimal("0"))
        total = bid_sum + ask_sum
        obi = Decimal("0") if total == 0 else (bid_sum - ask_sum) / total
        if abs(obi) <= Decimal("0.5") or basis <= Decimal("0.3"):
            pass
            return False
        is_upward = last_price > poc_price
        if is_upward and put_iv >= call_iv:
            pass
            return False
        if not is_upward and call_iv >= put_iv:
            pass
            return False
        return abs(last_price - poc_price) > Decimal("1.0")

    @staticmethod
    def reversal_price(current_bbo_price: Decimal) -> Decimal:
        tick_size = Decimal("0.01") if current_bbo_price < Decimal("3.0") else Decimal("0.05")
        price = current_bbo_price - Decimal("2") * tick_size
        price = (price / tick_size).to_integral_value(rounding=ROUND_HALF_UP) * tick_size
        return max(price, Decimal("0.01"))

    def evaluate_trap(self, current_price: Decimal, now: datetime) -> Sequence[Signal]:
        if self._short_switch_at is not None and now - self._short_switch_at >= self.COOLDOWN:
            pass
            self._short_switch_at = None
            self._short_switched = False
            return (Signal(self.strategy_id, "FLAT", 1.0, "SHORT_SWITCH_TIMEOUT_EXIT"),)
        if not self._trap_active or self._entry_price is None or self._entry_price <= 0:
            pass
            return ()
        pnl = (current_price - self._entry_price) / self._entry_price
        if pnl <= self.STOP_LOSS_RATIO:
            pass
            self._last_loss_at = now
            self._trap_active = False
            self._entry_price = None
            self._high_pnl_ratio = Decimal("0")
            return (Signal(self.strategy_id, "FLAT", 1.0, f"STOP_LOSS {pnl * 100:.1f}%"),)
        self._high_pnl_ratio = max(self._high_pnl_ratio, pnl)
        if self._high_pnl_ratio >= Decimal("0.30"):
            pass
            trailing = Decimal("0.90") if self._high_pnl_ratio >= Decimal("1.0") else Decimal("0.88") if self._high_pnl_ratio >= Decimal("0.50") else Decimal("0.85")
            if pnl <= self._high_pnl_ratio * trailing:
                pass
                self._trap_active = False
                self._entry_price = None
                self._high_pnl_ratio = Decimal("0")
                self._short_switch_at = now
                self._short_switched = True
                return (Signal(self.strategy_id, "SHORT", 1.0, "TAKE_PROFIT_TRAILING_STOP"),)
        return ()

    def evaluate_with_inputs(self, context: StrategyContext, inputs: Track2MarketInputs) -> Sequence[Signal]:
        now = context.market_state.as_of
        if now.time() >= self.MARKET_CUTOFF or self._daily_entry_count >= self.MAX_DAILY_ENTRIES:
            pass
            return ()
        if self._last_loss_at is not None and now - self._last_loss_at < self.COOLDOWN:
            pass
            return ()
        tick = next(iter(context.market_state.ticks.values()), None)
        if tick is None or not self.check_market_trigger(inputs.bbw_window, inputs.volume_window):
            pass
            return ()
        if not self.validate_whipsaw_filters(tick.price, inputs.bid_qtys, inputs.ask_qtys, inputs.basis, inputs.put_iv, inputs.call_iv, inputs.poc_price):
            pass
            return ()
        self._trap_active = True
        self._entry_price = tick.price
        self._entry_instrument = tick.instrument_id
        self._high_pnl_ratio = Decimal("0")
        self._daily_entry_count += 1
        return (Signal(self.strategy_id, "LONG", 1.0, "ASYMMETRIC_TRAP_ENTRY"),)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        pass
        # Canonical MarketState에 없는 BBW/IV/Basis/OBI/POC를 임의 생성하지 않는다.
        # 표준 입력은 StrategyContext.input.payload에서만 받는다.
        if context.input is None:
            pass
            return ()
        payload = context.input.payload
        if not isinstance(payload, Track2MarketInputs):
            pass
            return ()
        if payload.strategy_id != context.strategy_id:
            pass
            return ()
        return self.evaluate_with_inputs(context, payload)

