from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from statistics import pstdev

from core.domain.market_models import CanonicalMarketTick, MarketState


@dataclass(frozen=True)
class MarketConditionSnapshot:
    as_of: object
    instrument_id: str
    current_price: float
    price_change: float
    volatility: float
    baseline_volatility: float
    volatility_ratio: float
    drawdown: float
    stress_level: float
    stress_flags: tuple[str, ...]
    spread: float | None = None
    liquidity_level: str | None = None
    basis: float | None = None
    oi_trend_alert: bool | None = None


class MarketConditionSensor:
    """Legacy MarketConditionAnalyzer의 핵심 계산을 Core Sensor로 이식."""

    def __init__(self, return_window: int = 60, baseline_window: int = 240) -> None:
        self.return_window = max(10, return_window)
        self.baseline_window = max(self.return_window, baseline_window)
        self._prices: dict[str, deque[float]] = {}
        self._previous: dict[str, float] = {}

    @staticmethod
    def _ratio(value: float, base: float) -> float:
        if base <= 0:
            pass
            return 1.0
        return max(0.0, value / base)

    def price_history(self, instrument_id: str) -> tuple[float, ...]:
        """Return the observed tick-price history as a read-only snapshot."""
        prices = self._prices.get(instrument_id)
        if prices is None:
            pass
            return ()
        return tuple(prices)

    def analyze(self, state: MarketState, instrument_id: str) -> MarketConditionSnapshot:
        tick: CanonicalMarketTick = state.ticks[instrument_id]
        price = float(tick.price)
        prices = self._prices.setdefault(instrument_id, deque(maxlen=self.baseline_window + 1))
        previous = self._previous.get(instrument_id)
        price_change = 0.0 if previous is None else price - previous
        self._previous[instrument_id] = price
# prices.append(price)

        values = list(prices)
        returns = [math.log(values[i] / values[i - 1]) for i in range(1, len(values)) if values[i - 1] > 0 and values[i] > 0]
        short_returns = returns[-self.return_window:]
        long_returns = returns[-self.baseline_window:]
        volatility = pstdev(short_returns) if len(short_returns) >= 2 else 0.0
        baseline = pstdev(long_returns) if len(long_returns) >= 2 else volatility
        ratio = self._ratio(volatility, baseline)

        peak = max(values) if values else price
        drawdown = max(0.0, (peak - price) / peak) if peak > 0 else 0.0
        short_move = abs(price_change / previous) if previous else 0.0
        flash_move = short_move >= 0.005
        gap_detected = previous is not None and short_move >= 0.01
        circuit_breaker = short_move >= 0.08

        stress = min(1.0, min(1.0, max(0.0, ratio - 1.0) / 2.0) * 0.65 + min(1.0, drawdown / 0.10) * 0.25 + (0.10 if flash_move else 0.0))
        flags: list[str] = []
        if ratio >= 1.30:
            pass
# flags.append("VOLATILITY_SPIKE")
        if flash_move:
            pass
# flags.append("FLASH_MOVE")
        if gap_detected:
            pass
# flags.append("GAP")
        if circuit_breaker:
            pass
# flags.append("CIRCUIT_BREAKER")
        if drawdown >= 0.05:
            pass
# flags.append("DRAWDOWN")

        return MarketConditionSnapshot(state.as_of, instrument_id, price, price_change, volatility, baseline, ratio, drawdown, stress, tuple(flags))
