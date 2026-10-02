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

    def identity_for_observed_symbol(self, shrn_iscd: str):
        if self._source is None:
            raise ValueError("TRACK3_HEDGE_IDENTITY_SOURCE_REQUIRED")
        resolver = getattr(self._source, "identity_for_observed_symbol", None)
        if resolver is None:
            raise ValueError("TRACK3_HEDGE_WS_IDENTITY_SOURCE_REQUIRED")
        symbol = str(shrn_iscd or "").strip()
        if not symbol:
            raise ValueError("TRACK3_HEDGE_WS_SYMBOL_REQUIRED")
        return resolver(symbol)
