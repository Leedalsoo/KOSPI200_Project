from __future__ import annotations

from typing import Any, Mapping

from .track4_kis_greeks_provider import (
KISIndexOptionGreeksProvider,
# Track4KisGreeksProvider,
# Track4KisGreeksSourceInvalid,
)


class Track4KisWebSocketAdapterInvalid(ValueError):
    """Raised when a KIS realtime wire frame cannot be adapted safely."""


# H0IOCNT0 wire payload positions documented by KIS Open Trading API.
_INSTRUMENT_INDEX = 0
_OBSERVED_HOUR_INDEX = 1
_DELTA_INDEX = 28
_GAMMA_INDEX = 29
_THETA_INDEX = 31
_IV_INDEX = 33


class KISIndexOptionGreeksWebSocketAdapter:
    """Adapt one decoded KIS H0IOCNT0 realtime frame into the authoritative Provider.

    This is deliberately a wire-to-provider boundary, not a WebSocket transport.
    The caller owns the live socket, subscription lifecycle and environment clock.
    The adapter only validates the KIS frame envelope/field positions and delegates
    the authoritative numeric fields to KISIndexOptionGreeksProvider.
    """

    TR_ID = "H0IOCNT0"

    def adapt(
self,
        frame: str,
# *,
        observed_at: str,
        source: str = "KIS:H0IOCNT0",
    ) -> Track4KisGreeksProvider:
        parts = frame.split("|")
        if len(parts) < 4 or parts[0] not in {"0", "1"}:
            raise Track4KisWebSocketAdapterInvalid("invalid KIS realtime frame envelope")
        if parts[1] != self.TR_ID:
            raise Track4KisWebSocketAdapterInvalid("unexpected KIS TR ID")

        try:
            field_count = int(parts[2])
        except ValueError as exc:
            raise Track4KisWebSocketAdapterInvalid("invalid KIS field count") from exc

        values = parts[3].split("^")
        if field_count != len(values):
            raise Track4KisWebSocketAdapterInvalid("KIS field count mismatch")
        required_max = max(_INSTRUMENT_INDEX, _OBSERVED_HOUR_INDEX, _DELTA_INDEX, _GAMMA_INDEX, _THETA_INDEX, _IV_INDEX)
        if len(values) <= required_max:
            raise Track4KisWebSocketAdapterInvalid("KIS H0IOCNT0 payload is incomplete")

        instrument_id = values[_INSTRUMENT_INDEX].strip()
        if not instrument_id:
            raise Track4KisWebSocketAdapterInvalid("instrument id is missing")

        # observed_at is intentionally supplied by the caller; bsop_hour is retained
        # as source payload data but is not promoted to a timezone/date timestamp.
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
