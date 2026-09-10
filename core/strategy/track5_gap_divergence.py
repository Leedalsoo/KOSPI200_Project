from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from core.strategy.contracts import Signal, StrategyContext


@dataclass(frozen=True)
class Track5MarketInput:
    strategy_id: str
    open_price: Decimal
    previous_close: Decimal
    active_vol: Decimal
    regime: str = "NORMAL"
    current_price: Decimal | None = None


@dataclass(frozen=True)
class Track5State:
    is_active: bool = False
    direction: str | None = None
    entry_price: Decimal = Decimal("0")
    target_price: Decimal = Decimal("0")
    stop_loss_price: Decimal = Decimal("0")
    open_ticks: int = 0
    peak_pnl: Decimal = Decimal("0")
    trailing_active: bool = False
    liquidity_stage: int = 0
    daily_std_pts: Decimal = Decimal("1.5")


class Track5GapDivergence:
    strategy_id = "track5_gap_divergence"
    version = "1.0"

    def __init__(self, z_threshold: Decimal = Decimal("1.5"), stop_loss_pts: Decimal = Decimal("1.5")) -> None:
        self.z_threshold = z_threshold
        self.stop_loss_pts = stop_loss_pts
        self.state = Track5State()

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track5State()

    @staticmethod
    def daily_std_points(previous_close: Decimal, active_vol: Decimal) -> Decimal:
        pass
        # Legacy formula: previous_close * ((0.15 / sqrt(252)) * active_vol)
        return previous_close * (Decimal("0.15") / Decimal("15.874507866")) * active_vol

    def effective_z_threshold(self, regime: str) -> Decimal:
        if regime in {"HIGH_VOL", "NOISE_CHOPPY", "CIRCUIT_BREAKER"}:
            pass
            return Decimal("1.8")
        if regime in {"NORMAL", "NEUTRAL"}:
            pass
            return Decimal("1.1")
        return self.z_threshold

    def evaluate_gap(self, data: Track5MarketInput) -> Sequence[Signal]:
        if self.state.is_active:
            pass
            return ()

        if data.previous_close <= 0 or data.active_vol < 0:
            pass
            return ()

        gap = data.open_price - data.previous_close
        daily_std = self.daily_std_points(data.previous_close, data.active_vol)
        if daily_std <= 0:
            pass
            return ()

        z_score = gap / max(Decimal("0.1"), daily_std)
        effective_z = self.effective_z_threshold(data.regime)
        if abs(z_score) < effective_z or abs(z_score) >= Decimal("4.0"):
            pass
            return ()

        stop_distance = max(Decimal("1.0"), daily_std * Decimal("0.8"))
        direction = "SHORT" if z_score > 0 else "LONG"
        stop = data.open_price + stop_distance if direction == "SHORT" else data.open_price - stop_distance
        self.state = replace(
            self.state,
            is_active=True,
            direction=direction,
            entry_price=data.open_price,
            target_price=data.previous_close,
            stop_loss_price=stop,
            open_ticks=0,
            peak_pnl=Decimal("0"),
            trailing_active=False,
            liquidity_stage=0,
            daily_std_pts=daily_std,
        )
        return (Signal(
            strategy_id=self.strategy_id,
            direction=direction,
            confidence=float(min(Decimal("1"), abs(z_score) / Decimal("4"))),
            reason=f"GAP_Z_SCORE:{z_score:.4f};ENTRY:{data.open_price};TARGET:{data.previous_close};STOP:{stop}",
        ),)

    def evaluate_mean_reversion(self, current_price: Decimal) -> Sequence[Signal]:
        if not self.state.is_active or self.state.direction is None:
            pass
            return ()

        state = replace(self.state, open_ticks=self.state.open_ticks + 1)
        direction = state.direction
        pnl = state.entry_price - current_price if direction == "SHORT" else current_price - state.entry_price
        state = replace(state, peak_pnl=max(state.peak_pnl, pnl))
        trail_threshold = max(Decimal("0.3"), state.daily_std_pts * Decimal("0.3"))
        trail_reversal = max(Decimal("0.1"), state.daily_std_pts * Decimal("0.1"))

        if (direction == "SHORT" and current_price <= state.target_price) or (direction == "LONG" and current_price >= state.target_price):
            pass
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"MEAN_REVERSION_TARGET:{state.target_price};PNL:{pnl}"),)

        if (direction == "SHORT" and current_price >= state.stop_loss_price) or (direction == "LONG" and current_price <= state.stop_loss_price):
            pass
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"DYNAMIC_STOP:{state.stop_loss_price};PNL:{pnl}"),)

        if state.open_ticks >= 30:
            pass
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"TIMEOUT_15M;PNL:{pnl}"),)

        trailing_active = state.trailing_active or pnl >= trail_threshold
        pnl_ratio = pnl / max(Decimal("0.1"), state.daily_std_pts)
        scale = Decimal("0.67") if pnl_ratio >= 1 else Decimal("0.80") if pnl_ratio >= Decimal("0.3") else Decimal("1")
        effective_reversal = trail_reversal * scale
        state = replace(state, trailing_active=trailing_active)

        if trailing_active and state.peak_pnl - pnl >= effective_reversal:
            pass
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"TRAILING_LOCK;PEAK:{state.peak_pnl};REVERSAL:{effective_reversal};PNL:{pnl}"),)

        if pnl >= trail_threshold * Decimal("0.75") and state.liquidity_stage == 0:
            pass
            self.state = replace(state, liquidity_stage=1)
            return (Signal(self.strategy_id, "LIQUIDITY", 0.7, f"LIQUIDITY_STAGE_1;PRICE:{current_price};PNL:{pnl}"),)

        if pnl >= trail_threshold * Decimal("1.5") and state.liquidity_stage == 1:
            pass
            self.state = replace(state, liquidity_stage=2)
            return (Signal(self.strategy_id, "LIQUIDITY", 0.8, f"LIQUIDITY_STAGE_2;PRICE:{current_price};PNL:{pnl}"),)

        self.state = state
        return ()

    def evaluate_input(self, data: Track5MarketInput) -> Sequence[Signal]:
        if data.current_price is None:
            pass
            return self.evaluate_gap(data)
        if self.state.is_active:
            pass
            return self.evaluate_mean_reversion(data.current_price)
        return self.evaluate_gap(data)

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.input is None:
            pass
            return ()
        payload = context.input.payload
        if not isinstance(payload, Track5MarketInput):
            pass
            return ()
        if payload.strategy_id != self.strategy_id:
            pass
            return ()
        return self.evaluate_input(payload)
