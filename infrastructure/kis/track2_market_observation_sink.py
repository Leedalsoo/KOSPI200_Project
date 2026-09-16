from __future__ import annotations

from datetime import date

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from infrastructure.kis.basis_source import KISBasisSource
from infrastructure.kis.track2_market_metrics_source import KISTrack2MarketMetricsSource


class KISTrack2MarketObservationSink:
    """Connect each authoritative KIS futures trade observation to Track2 sources."""

    def __init__(self, *, basis_source: KISBasisSource, metrics_source: KISTrack2MarketMetricsSource, session_date: date | None = None) -> None:
        self.basis_source = basis_source
        self.metrics_source = metrics_source
        self.session_date = session_date

    def update(self, observation: KisIndexFuturesMarketObservation, *, session_date: date) -> None:
        self.basis_source.update_futures_observation(observation, session_date=session_date)
        self.metrics_source.update(observation)

    def on_observation(self, observation: KisIndexFuturesMarketObservation) -> None:
        if self.session_date is None:
            raise RuntimeError("TRACK2_SESSION_DATE_REQUIRED")
        self.update(observation, session_date=self.session_date)
