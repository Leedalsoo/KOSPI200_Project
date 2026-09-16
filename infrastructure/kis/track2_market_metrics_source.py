from __future__ import annotations

from collections import defaultdict, deque
from decimal import Decimal, localcontext

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from contracts.track2_market_metrics_source import Track2MarketMetrics


class KISTrack2MarketMetricsSource:
    """Derive Track2 BBW/volume windows only from KIS futures trade observations."""

    def __init__(self, *, price_window: int = 20, stddev_multiplier: Decimal = Decimal("2"), history_size: int = 80) -> None:
        if price_window < 2 or history_size < price_window:
            raise ValueError("TRACK2_METRICS_WINDOW_CONFIGURATION_INVALID")
        if stddev_multiplier <= 0:
            raise ValueError("TRACK2_BBW_STDDEV_MULTIPLIER_INVALID")
        self.price_window = price_window
        self.stddev_multiplier = stddev_multiplier
        self.history_size = history_size
        self._prices: dict[str, deque[Decimal]] = defaultdict(lambda: deque(maxlen=history_size))
        self._volumes: dict[str, deque[Decimal]] = defaultdict(lambda: deque(maxlen=history_size))
        self._last_cumulative: dict[str, Decimal] = {}
        self._latest_symbol: str | None = None

    def update(self, observation: KisIndexFuturesMarketObservation) -> None:
        if observation.source != "KIS:H0IFCNT0":
            return
        symbol = observation.shrn_iscd.strip()
        if not symbol or observation.price is None or observation.volume is None:
            return
        if observation.price <= 0 or observation.volume < 0:
            raise ValueError("AUTHORITATIVE_TRACK2_FUTURES_OBSERVATION_INVALID")
        previous = self._last_cumulative.get(symbol)
        if previous is not None and observation.volume < previous:
            raise ValueError("AUTHORITATIVE_TRACK2_VOLUME_CUMULATIVE_RESET")
        delta = observation.volume if previous is None else observation.volume - previous
        self._last_cumulative[symbol] = observation.volume
        self._latest_symbol = symbol
        self._prices[symbol].append(observation.price)
        self._volumes[symbol].append(delta)

    @staticmethod
    def _bbw(prices: list[Decimal], multiplier: Decimal) -> Decimal:
        if len(prices) < 2:
            raise ValueError("TRACK2_BBW_WINDOW_TOO_SHORT")
        with localcontext() as ctx:
            ctx.prec = 28
            mean = sum(prices, Decimal("0")) / Decimal(len(prices))
            variance = sum((price - mean) ** 2 for price in prices) / Decimal(len(prices))
            stddev = variance.sqrt()
            if mean == 0:
                raise ValueError("TRACK2_BBW_MIDDLE_BAND_ZERO")
            return ((multiplier * stddev) / mean).copy_abs()

    def get_metrics(self, symbol: str) -> Track2MarketMetrics | None:
        key = str(symbol).strip()
        if key == "KOSPI200" and key not in self._prices and self._latest_symbol is not None:
            key = self._latest_symbol
        prices = list(self._prices.get(key, ()))
        volumes = list(self._volumes.get(key, ()))
        if len(prices) < self.price_window or len(volumes) < 2:
            return None
        bbw_window = tuple(
            self._bbw(prices[index - self.price_window:index], self.stddev_multiplier)
            for index in range(self.price_window, len(prices) + 1)
        )
        if len(bbw_window) < 2:
            return None
        volume_window = tuple(volumes[-min(len(volumes), self.price_window):])
        if len(volume_window) < 2:
            return None
        returns = [abs(prices[i] / prices[i - 1] - Decimal("1")) for i in range(1, len(prices)) if prices[i - 1] > 0]
        if len(returns) < 2:
            return None
        split = max(1, len(returns) // 2)
        active = sum(returns[-split:], Decimal("0")) / Decimal(split)
        base = (sum(returns[:-split], Decimal("0")) / Decimal(len(returns[:-split]))) if len(returns) > split else active
        return Track2MarketMetrics(
            bbw_window=bbw_window,
            volume_window=volume_window,
            active_vol=active,
            base_vol=base,
        )
