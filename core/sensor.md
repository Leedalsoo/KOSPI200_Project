폴더: 기존 option_program/market_analysis 기능을 환경 독립 Sensor 책임으로 이식하는 공간.

## 이식 원칙

- 기존 파일을 복사하지 않고 기능 단위로 재구현한다.

- 입력은 core.domain.market_models.MarketState / CanonicalMarketTick만 사용한다.

- KIS/VMS/VSSF/Broker/UI/Legacy Runtime을 직접 import하지 않는다.

- 실제 입력에 존재하지 않는 bid/ask/OI/basis 값은 임의값으로 만들지 않는다.

- 기존 MarketConditionAnalyzer의 핵심 계산인 가격변화·단기/장기 변동성·변동성 비율·drawdown·stress/flags를 우선 이식한다.

[Child Page] market_condition_sensor.py
```python
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
            return 1.0
        return max(0.0, value / base)

    def price_history(self, instrument_id: str) -> tuple[float, ...]:
        """Return the observed tick-price history as a read-only snapshot."""
        prices = self._prices.get(instrument_id)
        if prices is None:
            return ()
        return tuple(prices)

    def analyze(self, state: MarketState, instrument_id: str) -> MarketConditionSnapshot:
        tick: CanonicalMarketTick = state.ticks[instrument_id]
        price = float(tick.price)
        prices = self._prices.setdefault(instrument_id, deque(maxlen=self.baseline_window + 1))
        previous = self._previous.get(instrument_id)
        price_change = 0.0 if previous is None else price - previous
        self._previous[instrument_id] = price
        prices.append(price)

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
            flags.append("VOLATILITY_SPIKE")
        if flash_move:
            flags.append("FLASH_MOVE")
        if gap_detected:
            flags.append("GAP")
        if circuit_breaker:
            flags.append("CIRCUIT_BREAKER")
        if drawdown >= 0.05:
            flags.append("DRAWDOWN")

        return MarketConditionSnapshot(state.as_of, instrument_id, price, price_change, volatility, baseline, ratio, drawdown, stress, tuple(flags))
```
## Legacy 대응
    - MarketConditionAnalyzer.analyze() → MarketConditionSensor.analyze()
    - 가격변화, 단기/장기 변동성, 변동성 비율, flash/gap/circuit-breaker/drawdown, stress/flags를 이식했다.
    - RegimeDetector는 Legacy import를 그대로 끌어오지 않고 별도 이식 대상으로 보류한다.
    - spread/basis/OI는 현재 Canonical 입력에 실제 필드가 없으므로 임의값을 만들지 않고 None으로 유지한다.
    - 이 단계는 Legacy 파일 삭제나 Runtime 교체가 아니라 기능 단위 1차 이식이다.