from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Sequence
from core.strategy.contracts import Signal, StrategyContext
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal

@dataclass(frozen=True)
class Track4MarketInput:
    """Runtime materialized Track4 input.

    Required fields are authoritative same-tick observations. Attribution fields are
    optional because their production source is not yet available; consumers that
    require them must fail closed rather than receive a fabricated default.
    """
    observed_at: datetime
    current_price: Decimal
    active_vol: Decimal
    base_vol: Decimal
    time_str: str
    current_delta: Decimal
    current_gamma: Decimal
    current_pnl: Decimal
    current_equity: Decimal
    price_history: Sequence[Decimal]
    premium_spent: Optional[Decimal] = None
    accumulated_gamma_profit: Optional[Decimal] = None
    theta_decay_cost: Optional[Decimal] = None

@dataclass
class Track4State:
    basecamp_active: bool = False
    active_hedge_qty: int = 0
    scalp_high_pnl: Decimal = Decimal("0")
    is_active: bool = False

class Track4GammaScalping:
    strategy_id = "track4_gamma_scalping"
    version = "1.0"

    def __init__(self, equity_threshold: Decimal = Decimal("0")):
        self.equity_threshold = equity_threshold
        self.state = Track4State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    @staticmethod
    def atm_strike(price: Decimal) -> Decimal:
        return (price / Decimal("2.5")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("2.5")

    def evaluate_basecamp(self, data: Track4MarketInput) -> Sequence[Signal]:
        if self.state.basecamp_active or data.time_str >= "15:15:00":
            return ()
        atm = self.atm_strike(data.current_price)
        if data.active_vol <= data.base_vol * Decimal("0.85"):
            self.state.basecamp_active = True
            return (Signal(self.strategy_id, "BUILD", 1.0, f"WIDE_BASECAMP call={atm + Decimal('2.5')} put={atm - Decimal('2.5')}"),)
        if data.active_vol >= data.base_vol * Decimal("1.30"):
            self.state.basecamp_active = True
            return (Signal(self.strategy_id, "BUILD", 1.0, f"ATM_BASECAMP call={atm} put={atm}"),)
        return ()

    @staticmethod
    def calculate_observed_tick_deadband(price_history: Sequence[Decimal]) -> Decimal:
        """Observed tick-price movement 기반 deadband. OHLC가 없는 현재 입력계약에서 ATR을 가장 가깝게 보존한다."""
        if not price_history:
            return Decimal("0")
        last = price_history[-1]
        if len(price_history) >= 2:
            movements = [abs(price_history[i] - price_history[i - 1]) for i in range(1, len(price_history))]
            movement = sum(movements, Decimal("0")) / Decimal(len(movements))
        else:
            movement = Decimal("0")
        normalized = Decimal("0") if last == 0 else movement / last
        return max(Decimal("0.2"), min(normalized * Decimal("5.0"), Decimal("0.6")))

    def evaluate_delta_hedge(self, data: Track4MarketInput) -> Sequence[Signal]:
        self.state.is_active = data.current_equity >= self.equity_threshold
        if not self.state.is_active:
            if self.state.active_hedge_qty:
                side = "SELL" if self.state.active_hedge_qty > 0 else "BUY"
                qty = abs(self.state.active_hedge_qty)
                self.state.active_hedge_qty = 0
                return (Signal(self.strategy_id, side, 1.0, f"UNWIND_FUT_HEDGE qty={qty}"),)
            return ()
        if not data.price_history:
            return ()
        band = self.calculate_observed_tick_deadband(data.price_history)
        if abs(data.current_delta) <= band:
            return ()
        if data.current_delta > 0:
            hedge_side = "SELL"
        else:
            hedge_side = "BUY"
        from core.risk.delta_hedge_quantity import delta_to_mini_futures_qty
        qty = delta_to_mini_futures_qty(data.current_delta)
        qty = min(qty, 100)
        if qty == 0:
            return ()
        signed_qty = qty if hedge_side == "BUY" else -qty
        self.state.active_hedge_qty += signed_qty
        return (Signal(self.strategy_id, hedge_side, 1.0, f"GAMMA_REBALANCE qty={qty} delta={data.current_delta} band={band}", execution_proposal=StrategyExecutionProposal(
            proposed_quantity=qty,
            asset_type="FUTURES",
            requested_price=None,
            side=hedge_side,
            track_id=self.strategy_id,
            tag_id=None,
            option_type=None,
            strike=None,
        )),)

    @staticmethod
    def theta_guard(accumulated_gamma_profit: Decimal, theta_decay_cost: Decimal) -> bool:
        return accumulated_gamma_profit > theta_decay_cost

    def evaluate_profit_trailing(self, data: Track4MarketInput) -> Sequence[Signal]:
        self.state.scalp_high_pnl = max(self.state.scalp_high_pnl, data.current_pnl)
        high = self.state.scalp_high_pnl
        if high <= Decimal("30000"):
            return ()
        if data.premium_spent is None:
            return ()
        ratio = high / max(Decimal("1"), data.premium_spent)
        trailing = Decimal("0.90") if ratio >= Decimal("2.0") else Decimal("0.88") if ratio >= Decimal("1.3") else Decimal("0.85")
        if data.current_pnl <= high * trailing:
            self.state.scalp_high_pnl = Decimal("0")
            # trailing close 이후 strategy-local hedge state도 stale 상태로 남기지 않는다.
            self.state.active_hedge_qty = 0
            self.state.is_active = False
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"PROFIT_TAKEN_TRAILING_STOP high={high} ratio={trailing}"),)
        return ()

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        strategy_input = context.input
        if strategy_input is None:
            return ()
        data = strategy_input.payload
        if not isinstance(data, Track4MarketInput):
            return ()
        if context.strategy_id != self.strategy_id:
            return ()
        # Track4MarketInput에는 strategy_id 필드가 없으므로
        # Strategy identity는 StrategyContext에서만 검증한다.
        signals = list(self.evaluate_basecamp(data))
        signals.extend(self.evaluate_delta_hedge(data))
        signals.extend(self.evaluate_profit_trailing(data))
        return tuple(signals)

    def reset(self) -> None:
        self.state = Track4State()
