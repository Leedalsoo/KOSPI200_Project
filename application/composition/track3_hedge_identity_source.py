from __future__ import annotations

from contracts.futures_identity_source_port import FuturesIdentitySourcePort


class Track3HedgeIdentitySource:
    """Named Track3 hedge contract source backed by the authoritative futures source."""

    def __init__(self, source: FuturesIdentitySourcePort | None):
        self._source = source

    def current_identity(self):
        if self._source is None:
            raise ValueError("TRACK3_HEDGE_IDENTITY_SOURCE_REQUIRED")
        return self._source.current_identity()
