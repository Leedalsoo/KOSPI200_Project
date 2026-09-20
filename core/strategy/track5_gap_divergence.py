from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from contracts.analytics import AnalyticsSnapshot, AnalyticsStatus
from core.strategy.contracts import Signal, StrategyContext, StrategyFeatureRequirement


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
    expected_move_pts: Decimal = Decimal("0")


class Track5GapDivergence:
    strategy_id = "track5_gap_divergence"
    version = "1.0"

    def __init__(self, z_threshold: Decimal = Decimal("1.5")) -> None:
        self.z_threshold = z_threshold
        self.state = Track5State()

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        return tuple(
            StrategyFeatureRequirement(key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
            for key in (
                "price.open", "price.gap", "price.last", "price.previous_close",
                "volatility.expected_move", "stats.z_score", "regime.market",
            )
        )

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.state = Track5State()

    def effective_z_threshold(self, regime: str) -> Decimal:
        if regime in {"HIGH_VOL", "NOISE_CHOPPY", "CIRCUIT_BREAKER"}:
            return Decimal("1.8")
        if regime in {"NORMAL", "NEUTRAL"}:
            return Decimal("1.1")
        return self.z_threshold

    @staticmethod
    def _metric(snapshot: AnalyticsSnapshot, key: str):
        metric = snapshot.get(key)
        if metric is None or metric.status is not AnalyticsStatus.AVAILABLE:
            return None
        return metric.value

    def _required(self, snapshot: AnalyticsSnapshot):
        values = tuple(self._metric(snapshot, key) for key in (
            "price.open", "price.last", "price.previous_close",
            "volatility.expected_move", "stats.z_score", "regime.market",
        ))
        open_price, last, previous_close, expected_move, z_score, regime = values
        if not all(isinstance(value, Decimal) for value in (open_price, last, previous_close, expected_move, z_score)):
            return None
        if not isinstance(regime, str) or previous_close <= 0 or expected_move <= 0:
            return None
        return open_price, last, previous_close, expected_move, z_score, regime
    def evaluate_gap(self, snapshot: AnalyticsSnapshot) -> Sequence[Signal]:
        if self.state.is_active:
            return ()
        required = self._required(snapshot)
        if required is None:
            return ()
        open_price, _, previous_close, expected_move, z_score, regime = required
        gap = self._metric(snapshot, "price.gap")
        if not isinstance(gap, Decimal):
            return ()
        effective_z = self.effective_z_threshold(regime)
        if abs(z_score) < effective_z or abs(z_score) >= Decimal("4.0"):
            return ()

        stop_distance = max(Decimal("1.0"), expected_move * Decimal("0.8"))
        direction = "SHORT" if z_score > 0 else "LONG"
        stop = open_price + stop_distance if direction == "SHORT" else open_price - stop_distance
        self.state = replace(
            self.state, is_active=True, direction=direction,
            entry_price=open_price, target_price=previous_close,
            stop_loss_price=stop, open_ticks=0, peak_pnl=Decimal("0"),
            trailing_active=False, liquidity_stage=0,
            expected_move_pts=expected_move,
        )
        return (Signal(
            strategy_id=self.strategy_id, direction=direction,
            confidence=float(min(Decimal("1"), abs(z_score) / Decimal("4"))),
            reason=f"GAP:{gap};GAP_Z_SCORE:{z_score:.4f};ENTRY:{open_price};TARGET:{previous_close};STOP:{stop}",
        ),)

    def evaluate_mean_reversion(self, current_price: Decimal) -> Sequence[Signal]:
        if not self.state.is_active or self.state.direction is None:
            return ()
        state = replace(self.state, open_ticks=self.state.open_ticks + 1)
        direction = state.direction
        pnl = state.entry_price - current_price if direction == "SHORT" else current_price - state.entry_price
        state = replace(state, peak_pnl=max(state.peak_pnl, pnl))
        trail_threshold = max(Decimal("0.3"), state.expected_move_pts * Decimal("0.3"))
        trail_reversal = max(Decimal("0.1"), state.expected_move_pts * Decimal("0.1"))
        if (direction == "SHORT" and current_price <= state.target_price) or (direction == "LONG" and current_price >= state.target_price):
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"MEAN_REVERSION_TARGET:{state.target_price};PNL:{pnl}"),)
        if (direction == "SHORT" and current_price >= state.stop_loss_price) or (direction == "LONG" and current_price <= state.stop_loss_price):
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"DYNAMIC_STOP:{state.stop_loss_price};PNL:{pnl}"),)
        if state.open_ticks >= 30:
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"TIMEOUT_15M;PNL:{pnl}"),)

        trailing_active = state.trailing_active or pnl >= trail_threshold
        pnl_ratio = pnl / max(Decimal("0.1"), state.expected_move_pts)
        scale = Decimal("0.67") if pnl_ratio >= 1 else Decimal("0.80") if pnl_ratio >= Decimal("0.3") else Decimal("1")
        effective_reversal = trail_reversal * scale
        state = replace(state, trailing_active=trailing_active)
        if trailing_active and state.peak_pnl - pnl >= effective_reversal:
            self.reset()
            return (Signal(self.strategy_id, "CLOSE", 1.0, f"TRAILING_LOCK;PEAK:{state.peak_pnl};REVERSAL:{effective_reversal};PNL:{pnl}"),)
        if pnl >= trail_threshold * Decimal("0.75") and state.liquidity_stage == 0:
            self.state = replace(state, liquidity_stage=1)
            return (Signal(self.strategy_id, "LIQUIDITY", 0.7, f"LIQUIDITY_STAGE_1;PRICE:{current_price};PNL:{pnl}"),)
        if pnl >= trail_threshold * Decimal("1.5") and state.liquidity_stage == 1:
            self.state = replace(state, liquidity_stage=2)
            return (Signal(self.strategy_id, "LIQUIDITY", 0.8, f"LIQUIDITY_STAGE_2;PRICE:{current_price};PNL:{pnl}"),)
        self.state = state
        return ()

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        if context.strategy_id != self.strategy_id or context.analytics is None:
            return ()
        if self.state.is_active:
            current_price = self._metric(context.analytics, "price.last")
            if not isinstance(current_price, Decimal):
                return ()
            return self.evaluate_mean_reversion(current_price)
        return self.evaluate_gap(context.analytics)
