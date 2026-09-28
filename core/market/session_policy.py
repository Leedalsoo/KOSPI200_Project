"""Common market-session boundaries shared by strategies."""
from __future__ import annotations

from datetime import time


class MarketSessionPolicy:
    OPEN = time(9, 0)
    STABILIZATION_END = time(9, 5)
    ENTRY_WINDOW_END = time(9, 30)
    LIMIT_CUTOFF = time(15, 0)
    MARKET_CUTOFF = time(15, 15)
    CLOSE = time(15, 30)

    @classmethod
    def text(cls, value: time) -> str:
        return value.strftime("%H:%M:%S")
