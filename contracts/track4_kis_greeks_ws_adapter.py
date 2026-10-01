from __future__ import annotations

from typing import Any, Mapping

from .track4_kis_greeks_provider import KISIndexOptionGreeksProvider, Track4KisGreeksProvider


class Track4KisWebSocketAdapterInvalid(ValueError):
    """Raised when a KIS realtime wire frame cannot be adapted safely."""


_INSTRUMENT_INDEX = 0
_OBSERVED_HOUR_INDEX = 1
_DELTA_INDEX = 28
_GAMMA_INDEX = 29
_THETA_INDEX = 31
_IV_INDEX = 33
_RECORD_WIDTH = 58


class KISIndexOptionGreeksWebSocketAdapter:
    """Adapt KIS H0IOCNT0 wire records into authoritative Greeks providers."""

    TR_ID = "H0IOCNT0"

    def adapt(
        self,
        frame: str,
        *,
        observed_at: str,
        source: str = "KIS:H0IOCNT0",
    ) -> Track4KisGreeksProvider:
        parts = frame.split("|")
        if len(parts) < 4 or parts[0] not in {"0", "1"}:
            raise Track4KisWebSocketAdapterInvalid("invalid KIS realtime frame envelope")
        if parts[1] != self.TR_ID:
            raise Track4KisWebSocketAdapterInvalid("unexpected KIS TR ID")
        try:
            record_count = int(parts[2])
        except ValueError as exc:
            raise Track4KisWebSocketAdapterInvalid("invalid KIS record count") from exc
        values = parts[3].split("^")
        if record_count == 1 and len(values) == _RECORD_WIDTH:
            return self._adapt_values(values, observed_at=observed_at, source=source)
        if record_count > 0 and len(values) == _RECORD_WIDTH * record_count:
            return self._adapt_values(values[:_RECORD_WIDTH], observed_at=observed_at, source=source)
        if record_count == len(values):
            return self._adapt_values(values, observed_at=observed_at, source=source)
        raise Track4KisWebSocketAdapterInvalid("KIS realtime record layout mismatch")

    def adapt_many(
        self,
        frame: str,
        *,
        observed_at: str,
        source: str = "KIS:H0IOCNT0",
    ) -> tuple[Track4KisGreeksProvider, ...]:
        parts = frame.split("|")
        if len(parts) < 4 or parts[0] not in {"0", "1"}:
            raise Track4KisWebSocketAdapterInvalid("invalid KIS realtime frame envelope")
        if parts[1] != self.TR_ID:
            raise Track4KisWebSocketAdapterInvalid("unexpected KIS TR ID")
        try:
            record_count = int(parts[2])
        except ValueError as exc:
            raise Track4KisWebSocketAdapterInvalid("invalid KIS record count") from exc
        values = parts[3].split("^")
        if record_count == 1 and len(values) == _RECORD_WIDTH:
            return (self._adapt_values(values, observed_at=observed_at, source=source),)
        if record_count <= 0 or len(values) != _RECORD_WIDTH * record_count:
            raise Track4KisWebSocketAdapterInvalid("KIS realtime record layout mismatch")
        return tuple(
            self._adapt_values(
                values[index * _RECORD_WIDTH:(index + 1) * _RECORD_WIDTH],
                observed_at=observed_at,
                source=source,
            )
            for index in range(record_count)
        )

    def _adapt_values(
        self,
        values: list[str],
        *,
        observed_at: str,
        source: str,
    ) -> Track4KisGreeksProvider:
        required_max = max(
            _INSTRUMENT_INDEX,
            _OBSERVED_HOUR_INDEX,
            _DELTA_INDEX,
            _GAMMA_INDEX,
            _THETA_INDEX,
            _IV_INDEX,
        )
        if len(values) <= required_max:
            raise Track4KisWebSocketAdapterInvalid("KIS H0IOCNT0 payload is incomplete")
        instrument_id = values[_INSTRUMENT_INDEX].strip()
        if not instrument_id:
            raise Track4KisWebSocketAdapterInvalid("instrument id is missing")
        payload: Mapping[str, Any] = {
            "delta": values[_DELTA_INDEX],
            "gama": values[_GAMMA_INDEX],
            "theta": values[_THETA_INDEX],
            "hts_ints_vltl": values[_IV_INDEX],
        }
        return KISIndexOptionGreeksProvider.from_payload(
            payload,
            instrument_id=instrument_id,
            observed_at=observed_at,
            source=source,
        )
