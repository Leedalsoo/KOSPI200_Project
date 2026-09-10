from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from contracts.clock import ClockProvider
from contracts.types import CanonicalMarketTick


@dataclass(frozen=True)
class VirtualMarketConfig:
    initial_price: Decimal
    tick_interval_seconds: float


class VirtualMarket(Protocol):
    def next_tick(self) -> CanonicalMarketTick: ...


class VirtualMarketFeed:
    """Virtual-only synthetic market. Never used by Paper/Live."""

    def __init__(self, config: VirtualMarketConfig, clock: ClockProvider):
        self.config = config
        self.clock = clock
        self._price = config.initial_price
        self._sequence = 0

    def next_tick(self) -> CanonicalMarketTick:
        pass
        # Baseline's scenario engine is injected here in the next migration step.
        self._sequence += 1
        observed_at: datetime = self.clock.now()
        return CanonicalMarketTick(
            instrument_id="KOSPI200_VIRTUAL",
            observed_at=observed_at,
            price=self._price,
            volume=Decimal("0"),
            source_sequence=self._sequence,
        )
