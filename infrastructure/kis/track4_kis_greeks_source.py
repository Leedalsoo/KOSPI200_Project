from __future__ import annotations

from datetime import datetime

from contracts.track4_kis_greeks_provider import Track4KisGreeksProvider, Track4KisGreeksSourceInvalid
from contracts.track4_kis_greeks_ws_adapter import KISIndexOptionGreeksWebSocketAdapter


class KISTrack4GreeksRealtimeSource:
    """Hold the latest authoritative Track4 Greeks projection from KIS frames."""

    source_name = "KIS:H0IOCNT0"

    def __init__(self, adapter: KISIndexOptionGreeksWebSocketAdapter | None = None) -> None:
        self._adapter = adapter or KISIndexOptionGreeksWebSocketAdapter()
        self._provider: Track4KisGreeksProvider | None = None

    def accept_frame(self, frame: str, *, observed_at: datetime) -> Track4KisGreeksProvider | None:
        parts = frame.split("|", 2)
        if len(parts) < 2 or parts[1] != self._adapter.TR_ID:
            return self._provider
        self._provider = self._adapter.adapt(
            frame,
            observed_at=observed_at.isoformat(),
            source=self.source_name,
        )
        return self._provider

    @property
    def snapshot(self):
        if self._provider is None:
            raise Track4KisGreeksSourceInvalid("TRACK4_KIS_GREEKS_UNAVAILABLE")
        return self._provider.snapshot

    def current_delta(self):
        return self._require_provider().current_delta()

    def current_gamma(self):
        return self._require_provider().current_gamma()

    def current_theta(self):
        return self._require_provider().current_theta()

    def active_vol(self):
        return self._require_provider().active_vol()

    def _require_provider(self):
        if self._provider is None:
            raise Track4KisGreeksSourceInvalid("TRACK4_KIS_GREEKS_UNAVAILABLE")
        return self._provider

    @property
    def provider(self) -> Track4KisGreeksProvider | None:
        return self._provider
