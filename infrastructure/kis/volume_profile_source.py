from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation


class KISVolumeProfileSource:
    """Build a POC from KIS index-futures trade volume deltas."""

    def __init__(self) -> None:
        self._last_cumulative: dict[str, Decimal] = {}
        self._last_observed_hour: dict[str, str] = {}
        self._profile: dict[str, dict[Decimal, Decimal]] = defaultdict(dict)
        self._latest_symbol: str | None = None

    def update(self, observation: KisIndexFuturesMarketObservation) -> None:
        if observation.source != "KIS:H0IFCNT0":
            return
        if observation.price is None or observation.volume is None:
            return
        symbol = observation.shrn_iscd.strip()
        if not symbol:
            return
        cumulative = observation.volume
        observed_hour = str(observation.observed_hour).strip()
        previous = self._last_cumulative.get(symbol)
        last_observed_hour = self._last_observed_hour.get(symbol)
        if previous is None:
            delta = cumulative
        elif cumulative >= previous:
            delta = cumulative - previous
        elif last_observed_hour is not None and observed_hour <= last_observed_hour:
            return
        else:
            raise ValueError("AUTHORITATIVE_VOLUME_PROFILE_CUMULATIVE_VOLUME_RESET")
        self._last_cumulative[symbol] = cumulative
        if observed_hour:
            self._last_observed_hour[symbol] = observed_hour
        if delta <= 0:
            return
        self._latest_symbol = symbol
        profile = self._profile.setdefault(symbol, {})
        profile[observation.price] = profile.get(observation.price, Decimal("0")) + delta

    def get_poc(self, symbol: str) -> Decimal | None:
        key = str(symbol).strip()
        if key == "KOSPI200" and key not in self._profile and self._latest_symbol is not None:
            key = self._latest_symbol
        profile = self._profile.get(key)
        if not profile:
            return None
        return max(profile.items(), key=lambda item: (item[1], item[0]))[0]
