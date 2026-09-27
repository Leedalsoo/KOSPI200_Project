from __future__ import annotations

from datetime import datetime

from contracts.track4_kis_greeks_provider import Track4KisGreeksProvider
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
    def provider(self) -> Track4KisGreeksProvider | None:
        return self._provider
