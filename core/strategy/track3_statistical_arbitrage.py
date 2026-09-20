"""Track3 Statistical Arbitrage strategy and strategy-specific state/rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Mapping

from contracts.analytics import AnalyticsStatus
from core.strategy.contracts import Signal, StrategyContext, StrategyFeatureRequirement, validate_strategy_features
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


@dataclass(frozen=True)
class Track3MarketInput:
    """Track3가 필요로 하는 비표준 시장 입력을 명시적으로 전달한다."""
    spread_history: tuple[float, ...] = ()
    active_vol: float = 1.0
    base_vol: float = 1.0
    price_change_rate: float = 0.0
    bid_ask_spread: float = 0.0
    gap_pct: float = 0.0
    is_gap: bool = False
    time_str: str = "09:00:00"
    market_stable: bool = False
    spread_normalizing: bool = False
    allow_size_up: bool = False
    current_pnl: float = 0.0
    total_fees: float = 0.0
    premium_spent: float = 0.0
    current_price: float = 0.0
    options_legs: tuple[Mapping[str, object], ...] = ()
    contract_multiplier: float | None = None
    regime: str | None = None
    date_str: str = ""


@dataclass(frozen=True)
class Track3Result:
    status: str
    regime: str
    z_score: float
    signals: tuple[Signal, ...] = ()


@dataclass
class Track3StatisticalArbitrage:
    strategy_id: str = "Strategy_3_StatArb"
    version: str = "1.0"
    z_entry_threshold: float = 2.0
    z_exit_threshold: float = 0.2
    z_stop_loss_threshold: float = 3.5
    max_holding_ticks: int = 300
    min_required_profit: float = 15_000.0
    base_round_trip_cost: float = 10_000.0
    active_position: str | None = None
    active_group_id: str | None = None
    group_sequence: int = 0
    cooldown_ticks: int = 0
    holding_ticks: int = 0
    last_exit_z_score: float | None = None
    group_integrity: bool = True
    position_group_legs: list[Mapping[str, object]] = field(default_factory=list)
    _arb_high_pnl: float = 0.0
    _current_date: str = ""

    def initialize(self, context: StrategyContext) -> None:
        self.reset()

    def on_market_state(self, context: StrategyContext) -> None:
        return None

    def reset(self) -> None:
        self.active_position = None
        self.active_group_id = None
        self.group_sequence = 0
        self.cooldown_ticks = 0
        self.holding_ticks = 0
        self.last_exit_z_score = None
        self.group_integrity = True
        self.position_group_legs = []
        self._arb_high_pnl = 0.0
        self._current_date = ""

    @staticmethod
    def detect_market_regime(
        data: Track3MarketInput,
        *,
        vol_ratio: float,
        price_change_rate: float,
        bid_ask_spread: float,
        gap_pct: float,
    ) -> str:
        explicit = data.regime
        if explicit in {"HIGH_VOL", "HIGH_VOLATILITY"}:
            return "HIGH_VOLATILITY"
        if explicit in {"EXTREME_MOVE", "CIRCUIT_BREAKER", "CRASH"}:
            return "EXTREME_MOVE"
        if explicit in {"GAP", "GAP_OPEN"}:
            return "GAP"
        gap = data.is_gap or (data.time_str < "09:05:00" and abs(gap_pct) >= 0.008)
        if gap:
            return "GAP"
        if abs(price_change_rate) >= 0.02 or vol_ratio >= 2.5:
            return "EXTREME_MOVE"
        if vol_ratio >= 1.4 or bid_ask_spread > 0.3:
            return "HIGH_VOLATILITY"
        return "NORMAL"

    def estimate_round_trip_cost(
        self, regime: str, qty: int, *, bid_ask_spread: float, contract_multiplier: float | None
    ) -> float:
        if contract_multiplier is None or not isfinite(contract_multiplier) or contract_multiplier <= 0:
            raise ValueError("TRACK3_CONTRACT_MULTIPLIER_UNAVAILABLE")
        spread_cost = bid_ask_spread * contract_multiplier
        fee_per_leg = 3_000.0
        slippage_ticks = 1.0 if regime == "NORMAL" else 2.0 if regime == "HIGH_VOLATILITY" else 3.0
        slippage = slippage_ticks * 0.05 * contract_multiplier * qty
        return (fee_per_leg * 2 * qty) + slippage + (spread_cost * qty) + self.base_round_trip_cost

    def _signal(self, action: str, position: str, reason: str, **details: object) -> Signal:
        payload = {"action": action, "position": position, **details}
        quantity = int(details.get("qty", 0) or 0)
        if quantity <= 0:
            raise ValueError("TRACK3_EXECUTION_QTY_REQUIRED")
        if action == "EXECUTE_STAT_ARB":
            side = "SELL" if position == "SHORT_SPREAD" else "BUY"
        elif action == "CLOSE_STAT_ARB":
            side = "BUY" if position == "CLOSE_SHORT_SPREAD" else "SELL"
        else:
            raise ValueError("TRACK3_EXECUTION_ACTION_UNSUPPORTED")
        proposal = StrategyExecutionProposal(
            proposed_quantity=quantity,
            asset_type="FUTURES",
            side=side,
            track_id=self.strategy_id,
            tag_id=action,
        )
        return Signal(
            strategy_id=self.strategy_id,
            direction=position,
            confidence=1.0,
            reason=f"{reason} | {payload}",
            execution_proposal=proposal,
        )

    def feature_requirements(self):
        return tuple(
            StrategyFeatureRequirement(key, "tick", 1.0, frozenset({AnalyticsStatus.AVAILABLE}))
            for key in (
                "spread.z_score",
                "spread.std",
                "volatility.ratio",
                "microstructure.spread",
                "price.change_rate",
                "market.gap_pct",
                "cost.fees",
                "portfolio.current_pnl",
                "portfolio.options_pnl",
                "portfolio.premium_spent",
            )
        )

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        data = context.input.payload if context.input is not None else None
        analytics = context.analytics
        if not isinstance(data, Track3MarketInput) or analytics is None or context.strategy_id != self.strategy_id:
            return ()
        metrics = validate_strategy_features(self.feature_requirements(), analytics)
        if any(m.status is not AnalyticsStatus.AVAILABLE or m.value is None for m in metrics):
            return ()
        result = self.evaluate_input(data, analytics)
        return result.signals

    def evaluate_input(self, data: Track3MarketInput, analytics) -> Track3Result:
        if data.date_str and data.date_str != self._current_date:
            self._current_date = data.date_str
            self.cooldown_ticks = 0
            self.holding_ticks = 0
            self.active_position = None
            self.active_group_id = None
            self.last_exit_z_score = None
            self.position_group_legs = []
            self.group_integrity = True

        z_score = float(analytics.get("spread.z_score").value)
        spread_std = float(analytics.get("spread.std").value)
        vol_ratio = float(analytics.get("volatility.ratio").value)
        bid_ask_spread = float(analytics.get("microstructure.spread").value)
        price_change_rate = float(analytics.get("price.change_rate").value)
        gap_pct = float(analytics.get("market.gap_pct").value)
        regime = self.detect_market_regime(
            data,
            vol_ratio=vol_ratio,
            price_change_rate=price_change_rate,
            bid_ask_spread=bid_ask_spread,
            gap_pct=gap_pct,
        )
        total_fees = float(analytics.get("cost.fees").value)
        effective_pnl = float(analytics.get("portfolio.current_pnl").value) + float(analytics.get("portfolio.options_pnl").value)
        premium_spent = float(analytics.get("portfolio.premium_spent").value)
        if self.cooldown_ticks > 0:
            self.cooldown_ticks -= 1

        if regime == "HIGH_VOLATILITY":
            threshold = max(2.2, self.z_entry_threshold * vol_ratio * 1.2)
            min_profit = self.min_required_profit * 1.5
            qty = 1
        elif regime == "EXTREME_MOVE":
            threshold = 999.0
            min_profit = self.min_required_profit * 3.0
            qty = 0
        elif regime == "GAP":
            threshold = max(2.0, self.z_entry_threshold * 1.1)
            min_profit = self.min_required_profit * 1.3
            qty = 1
        else:
            threshold = max(1.5, self.z_entry_threshold * vol_ratio)
            min_profit = self.min_required_profit
            qty = 2 if abs(z_score) >= 2.5 and data.allow_size_up else 1

        signals: list[Signal] = []

        if self.active_position is None:
            if data.time_str >= "15:00:00" or regime == "EXTREME_MOVE" or self.cooldown_ticks > 0:
                return Track3Result("ENTRY_BLOCK", regime, z_score)
            if regime == "GAP" and not (data.market_stable and data.spread_normalizing):
                return Track3Result("GAP_UNSTABLE_HOLD", regime, z_score)
            if self.last_exit_z_score is not None and abs(z_score - self.last_exit_z_score) < 0.8:
                return Track3Result("OLD_DISLOCATION_BLOCK", regime, z_score)

            cost = self.estimate_round_trip_cost(
                regime, qty, bid_ask_spread=bid_ask_spread, contract_multiplier=data.contract_multiplier
            )
            gross = abs(z_score) * spread_std * 0.8 * data.contract_multiplier * qty
            net = gross - cost
            if net < min_profit:
                return Track3Result("PROFITABILITY_BLOCK", regime, z_score)
            if z_score >= threshold:
                position = "SHORT_SPREAD"
            elif z_score <= -threshold:
                position = "LONG_SPREAD"
            else:
                return Track3Result("HOLD", regime, z_score)

            self.group_sequence += 1
            self.active_group_id = f"ARB-GROUP-{data.date_str or 'UNKNOWN'}-TRACK3-{self.group_sequence:04d}"
            self.active_position = position
            self.holding_ticks = 0
            self._arb_high_pnl = 0.0
            self.group_integrity = True
            self.position_group_legs = [
                {"group_id": self.active_group_id, "leg_type": "FUTURES_SHORT" if position == "SHORT_SPREAD" else "FUTURES_LONG", "qty": qty},
                {"group_id": self.active_group_id, "leg_type": "HEDGE_LEG", "qty": qty},
            ]
            signals.append(self._signal("EXECUTE_STAT_ARB", position, "Z-score entry and expected net profit satisfied", group_id=self.active_group_id, qty=qty, expected_net_pnl=net))
            return Track3Result("ENTER", regime, z_score, tuple(signals))

        self.holding_ticks += 1
        action_type = "CLOSE_SHORT_SPREAD" if self.active_position == "SHORT_SPREAD" else "CLOSE_LONG_SPREAD"
        if data.time_str >= "15:15:00":
            signals.append(self._signal("CLOSE_STAT_ARB", action_type, "15:15 atomic position-group close", group_id=self.active_group_id, qty=1))
            return self._close("MARKET_CLOSE_FLATTEN", z_score, tuple(signals), cooldown=20)

        self._arb_high_pnl = max(self._arb_high_pnl, effective_pnl)
        spent = max(1.0, premium_spent)
        if self._arb_high_pnl > 30_000.0:
            ratio = self._arb_high_pnl / spent
            trailing = 0.90 if ratio >= 2.0 else 0.88 if ratio >= 1.3 else 0.85
            if effective_pnl <= self._arb_high_pnl * trailing:
                signals.append(self._signal("CLOSE_STAT_ARB", action_type, "high-watermark trailing profit lock", group_id=self.active_group_id, qty=1))
                return self._close("TRAILING_PROFIT_LOCK", z_score, tuple(signals), cooldown=20)

        stop = (self.active_position == "SHORT_SPREAD" and z_score >= self.z_stop_loss_threshold) or (self.active_position == "LONG_SPREAD" and z_score <= -self.z_stop_loss_threshold)
        if stop:
            signals.append(self._signal("CLOSE_STAT_ARB", action_type, "extreme Z-score stop loss", group_id=self.active_group_id, qty=1))
            return self._close("STOP_LOSS", z_score, tuple(signals), cooldown=40)
        if self.holding_ticks >= self.max_holding_ticks:
            signals.append(self._signal("CLOSE_STAT_ARB", action_type, "maximum holding time reached", group_id=self.active_group_id, qty=1))
            return self._close("TIMEOUT_EXIT", z_score, tuple(signals), cooldown=20)

        converged = (self.active_position == "SHORT_SPREAD" and z_score <= self.z_exit_threshold) or (self.active_position == "LONG_SPREAD" and z_score >= -self.z_exit_threshold)
        cost = self.estimate_round_trip_cost(
            regime, 1, bid_ask_spread=bid_ask_spread, contract_multiplier=data.contract_multiplier
        )
        net_exit = effective_pnl - total_fees - cost
        profitable = net_exit >= -5_000.0
        if regime == "HIGH_VOLATILITY" and effective_pnl > 10_000.0:
            profitable = True
        if regime == "GAP" and converged and effective_pnl > 5_000.0:
            profitable = True
        if converged and profitable and self.group_integrity:
            signals.append(self._signal("CLOSE_STAT_ARB", action_type, "convergence + profitability + integrity", group_id=self.active_group_id, expected_net_pnl=net_exit, qty=1))
            return self._close("CLOSED", z_score, tuple(signals), cooldown=20)
        return Track3Result("HOLD", regime, z_score)

    def _close(self, status: str, z_score: float, signals: tuple[Signal, ...], cooldown: int) -> Track3Result:
        self.last_exit_z_score = z_score
        self.active_position = None
        self.active_group_id = None
        self.position_group_legs = []
        self.cooldown_ticks = cooldown
        self.holding_ticks = 0
        return Track3Result(status, "", z_score, signals)
