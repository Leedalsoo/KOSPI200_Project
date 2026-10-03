"""Track7 Classic Floor Pivot provider backed by historical daily OHLC."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from contracts.historical_market_ohlc import HistoricalDailyOHLCProvider
from contracts.track7_support_resistance_source import Track7SupportResistanceObservation


class Track7ClassicPivotProvider:
    """Calculate deterministic intraday S/R from the prior completed daily bar."""

    definition = "CLASSIC_FLOOR_PIVOT_PREVIOUS_COMPLETED_DAILY_OHLC"
    window = "PREVIOUS_COMPLETED_TRADING_DAY_1_DAILY_BAR"
    calculation_version = "TRACK7-CLASSIC-PIVOT-v1"
    source_name = "KRX:KOSPI200:CanonicalDailyOHLC"
    underlying_identity = "KOSPI200"
    tick_size = Decimal("0.05")

    def __init__(self, historical_ohlc: HistoricalDailyOHLCProvider) -> None:
        if historical_ohlc is None:
            raise ValueError("TRACK7_HISTORICAL_OHLC_PROVIDER_REQUIRED")
        self.historical_ohlc = historical_ohlc

    @classmethod
    def _tick(cls, value: Decimal) -> Decimal:
        return (value / cls.tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * cls.tick_size

    @classmethod
    def _levels(cls, bar) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        pivot = (bar.high + bar.low + bar.close) / Decimal("3")
        r1 = Decimal("2") * pivot - bar.low
        s1 = Decimal("2") * pivot - bar.high
        r2 = pivot + (bar.high - bar.low)
        s2 = pivot - (bar.high - bar.low)
        return tuple(cls._tick(x) for x in (pivot, r1, s1, r2, s2))

    def get_support_resistance(self, *, symbol: str, observed_at: datetime, current_price: Decimal) -> Track7SupportResistanceObservation | None:
        price = Decimal(str(current_price))
        if price <= 0:
            raise ValueError("TRACK7_CURRENT_PRICE_REQUIRED")
        bar = self.historical_ohlc.get_previous_completed_day(symbol=self.underlying_identity, observed_at=observed_at)
        if bar is None:
            return None
        pivot, r1, s1, r2, s2 = self._levels(bar)
        # Pivot levels are fixed reference levels for the session:
        # S2 < S1 < P < R1 < R2.  When price moves outside the ladder,
        # keep the nearest boundary level on that side rather than making
        # the source unavailable.
        support = max((level for level in (s2, s1, pivot) if level <= price), default=s2)
        resistance = min((level for level in (pivot, r1, r2) if level >= price), default=r2)
        return Track7SupportResistanceObservation(
            support=support,
            resistance=resistance,
            observed_at=bar.observed_at,
            source=f"{self.source_name}:{bar.source}",
            definition=self.definition,
            window=self.window,
            calculation_version=self.calculation_version,
        )
