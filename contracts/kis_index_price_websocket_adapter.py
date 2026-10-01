from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class KISIndexPriceWebSocketAdapterInvalid(ValueError):
    """Raised when an authoritative KIS H0UPCNT0 frame is unusable."""


@dataclass(frozen=True)
class KisIndexPriceWebSocketObservation:
    index_code: str
    observed_hour: str
    price: Decimal
    source: str


_H0UPCNT0 = "H0UPCNT0"
_SYMBOL = 0
_TIME = 1
_PRICE = 2


def _decode_fields(frame: str) -> list[str]:
    parts = frame.split("|")
    if len(parts) < 4 or parts[0] not in {"0", "1"}:
        raise KISIndexPriceWebSocketAdapterInvalid("invalid KIS realtime frame envelope")
    if parts[1] != _H0UPCNT0:
        raise KISIndexPriceWebSocketAdapterInvalid("unexpected KIS TR ID")
    try:
        record_count = int(parts[2])
    except ValueError as exc:
        raise KISIndexPriceWebSocketAdapterInvalid("invalid KIS record count") from exc
    if record_count != 1:
        raise KISIndexPriceWebSocketAdapterInvalid("KIS H0UPCNT0 record count must be one")
    values = parts[3].split("^")
    if len(values) <= _PRICE:
        raise KISIndexPriceWebSocketAdapterInvalid("KIS H0UPCNT0 payload is incomplete")
    return values


class KISIndexPriceWebSocketAdapter:
    """Adapt KIS domestic-index realtime trade frames into typed observations."""

    TR_ID = _H0UPCNT0
    INDEX_CODE = "2001"

    def adapt(self, frame: str, *, source: str | None = None) -> KisIndexPriceWebSocketObservation:
        values = _decode_fields(frame)
        index_code = values[_SYMBOL].strip()
        observed_hour = values[_TIME].strip()
        if index_code != self.INDEX_CODE:
            raise KISIndexPriceWebSocketAdapterInvalid("KIS index identity mismatch")
        if len(observed_hour) not in {6, 9} or not observed_hour.isdigit():
            raise KISIndexPriceWebSocketAdapterInvalid("KIS H0UPCNT0 observed hour is invalid")
        try:
            price = Decimal(values[_PRICE])
        except Exception as exc:
            raise KISIndexPriceWebSocketAdapterInvalid("invalid H0UPCNT0 price") from exc
        if price <= 0:
            raise KISIndexPriceWebSocketAdapterInvalid("KIS H0UPCNT0 price is unavailable")
        return KisIndexPriceWebSocketObservation(
            index_code=index_code,
            observed_hour=observed_hour,
            price=price,
            source=source or "KIS:H0UPCNT0",
        )
