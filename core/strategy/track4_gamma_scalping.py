from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Sequence

from contracts.analytics import AnalyticsStatus
from core.strategy.contracts import Signal, StrategyContext, StrategyFeatureRequirement, validate_strategy_features
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


@dataclass(frozen=True)
class Track4MarketInput:
    """Strategy-specific context; common observations are consumed from AnalyticsSnapshot."""
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
    current_theta: Optional[Decimal] = None


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

    def feature_requirements(self):
        return tuple(
            StrategyFeatureRequirement(key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
            for key in (
                "volatility.active",
                "volatility.base",
                "volatility.ratio",
                "options.delta",
                "portfolio.current_pnl",
                "portfolio.equity",
                "price.tick_deadband",
            )
        )

    @staticmethod
    def atm_strike(price: Decimal) -> Decimal:
        return (price / Decimal("2.5")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("2.5")

    def evaluate_basecamp(self, data: Track4MarketInput, *, active_vol: Decimal, base_vol: Decimal) -> Sequence[Signal]:
        if self.state.basecamp_active or data.time_str >= "15:15:00":
            return ()
        atm = self.atm_strike(data.current_price)
        if active_vol <= base_vol * Decimal("0.85"):
            self.state.basecamp_active = True
            return (Signal(self.strategy_id, "BUILD", 1.0, f"WIDE_BASECAMP call={atm + Decimal('2.5')} put={atm - Decimal('2.5')}"),)
        if active_vol >= base_vol * Decimal("1.30"):
            self.state.basecamp_active = True
            return (Signal(self.strategy_id, "BUILD", 1.0, f"ATM_BASECAMP call={atm} put={atm}"),)
        return ()

    def evaluate_delta_hedge(self, data: Track4MarketInput, *, delta: Decimal, deadband: Decimal, equity: Decimal) -> Sequence[Signal]:
        self.state.is_active = equity >= self.equity_threshold
        if not self.state.is_active:
            if self.state.active_hedge_qty:
                side = "SELL" if self.state.active_hedge_qty > 0 else "BUY"
                qty = abs(self.state.active_hedge_qty)
                self.state.active_hedge_qty = 0
                return (Signal(self.strategy_id, side, 1.0, f"UNWIND_FUT_HEDGE qty={qty}"),)
            return ()
        if abs(delta) <= deadband:
            return ()
        hedge_side = "SELL" if delta > 0 else "BUY"
        from core.risk.delta_hedge_quantity import delta_to_mini_futures_qty
        qty = min(delta_to_mini_futures_qty(delta), 100)
        if qty == 0:
            return ()
        signed_qty = qty if hedge_side == "BUY" else -qty
        self.state.active_hedge_qty += signed_qty
        return (Signal(self.strategy_id, hedge_side, 1.0, f"GAMMA_REBALANCE qty={qty} delta={delta} band={deadband}", execution_proposal=StrategyExecutionProposal(proposed_quantity=qty, asset_type="FUTURES", requested_price=None, side=hedge_side, track_id=self.strategy_id, tag_id=None, option_type=None, strike=None)),)

    def evaluate_profit_trailing(self, data: Track4MarketInput, *, current_pnl: Decimal, premium_spent: Optional[Decimal]) -> Sequence[Signal]:
        self.state.scalp_high_pnl = max(self.state.scalp_high_pnl, current_pnl)
        high = self.state.scalp_high_pnl
        if high <= Decimal("30000") or premium_spent is None:
            return ()
        ratio = high / max(Decimal("1"), premium_spent)
        trailing = Decimal("0.90") if ratio >= Decimal("2.0") else Decimal("0.88") if ratio >= Decimal("1.3") else Decimal("0.85")
        if current_pnl <= high * trailing:
            self.state.scalp_high_pnl = Decimal("0")
            self.state.active_hedge_qty = 0
            self.state.is_active = False
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"PROFIT_TAKEN_TRAILING_STOP high={high} ratio={trailing}"),)
        return ()

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        data = context.input.payload if context.input is not None else None
        analytics = context.analytics
        if not isinstance(data, Track4MarketInput) or analytics is None or context.strategy_id != self.strategy_id:
            return ()
        metrics = validate_strategy_features(self.feature_requirements(), analytics)
        if any(metric.status is not AnalyticsStatus.AVAILABLE or metric.value is None for metric in metrics):
            return ()
        active_vol = Decimal(str(analytics.get("volatility.active").value))
        base_vol = Decimal(str(analytics.get("volatility.base").value))
        delta = Decimal(str(analytics.get("options.delta").value))
        deadband = Decimal(str(analytics.get("price.tick_deadband").value))
        equity = Decimal(str(analytics.get("portfolio.equity").value))
        current_pnl = Decimal(str(analytics.get("portfolio.current_pnl").value))
        premium_metric = analytics.get("portfolio.premium_spent")
        premium_spent = None if premium_metric is None or premium_metric.value is None else Decimal(str(premium_metric.value))
        signals = list(self.evaluate_basecamp(data, active_vol=active_vol, base_vol=base_vol))
        signals.extend(self.evaluate_delta_hedge(data, delta=delta, deadband=deadband, equity=equity))
        signals.extend(self.evaluate_profit_trailing(data, current_pnl=current_pnl, premium_spent=premium_spent))
        return tuple(signals)

    def reset(self) -> None:
        self.state = Track4State()
