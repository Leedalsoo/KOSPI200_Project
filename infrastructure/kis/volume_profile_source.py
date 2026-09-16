from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation


class KISVolumeProfileSource:
    """Build a POC from KIS index-futures trade volume deltas."""

    def __init__(self) -> None:
        self._last_cumulative: dict[str, Decimal] = {}
        self._profile: dict[str, dict[Decimal, Decimal]] = defaultdict(dict)

    def update(self, observation: KisIndexFuturesMarketObservation) -> None:
        if observation.source != "KIS:H0IFCNT0":
            return
        if observation.price is None or observation.volume is None:
            return
        symbol = observation.shrn_iscd.strip()
        if not symbol:
            return
        cumulative = observation.volume
        previous = self._last_cumulative.get(symbol)
        if previous is None:
            delta = cumulative
        elif cumulative >= previous:
            delta = cumulative - previous
        else:
            raise ValueError("AUTHORITATIVE_VOLUME_PROFILE_CUMULATIVE_VOLUME_RESET")
        self._last_cumulative[symbol] = cumulative
        if delta <= 0:
            return
        profile = self._profile.setdefault(symbol, {})
        profile[observation.price] = profile.get(observation.price, Decimal("0")) + delta

    def get_poc(self, symbol: str) -> Decimal | None:
        profile = self._profile.get(str(symbol).strip())
        if not profile:
            return None
        return max(profile.items(), key=lambda item: (item[1], item[0]))[0]
