from __future__ import annotations

from datetime import date, datetime

from contracts.kis_index_price_source import KISIndexPriceObservation, KOSPI200_INDEX_CODE
from contracts.kis_index_price_websocket_adapter import KISIndexPriceWebSocketAdapter


class KISWebSocketIndexPriceSource:
    """Materialize authoritative H0UPCNT0 observations with source and collection timestamps."""

    SOURCE = "KIS:H0UPCNT0:2001"

    def __init__(self, *, session_date: date) -> None:
        self._session_date = session_date
        self._adapter = KISIndexPriceWebSocketAdapter()
        self._latest: KISIndexPriceObservation | None = None

    @staticmethod
    def _observed_at(session_date: date, observed_hour: str) -> datetime:
        if len(observed_hour) == 6:
            parsed = datetime.strptime(observed_hour, "%H%M%S")
        else:
            parsed = datetime.strptime(observed_hour, "%H%M%S%f")
        return datetime.combine(session_date, parsed.time())

    def update_frame(self, frame: str, *, received_at: datetime) -> KISIndexPriceObservation:
        if received_at.tzinfo is None:
            raise ValueError("RECEIVED_AT_MUST_BE_TIMEZONE_AWARE")
        adapted = self._adapter.adapt(frame, source="KIS:H0UPCNT0")
        observation = KISIndexPriceObservation(
            underlying_symbol="KOSPI200",
            index_code=KOSPI200_INDEX_CODE,
            price=adapted.price,
            observed_at=self._observed_at(self._session_date, adapted.observed_hour),
            source=self.SOURCE,
            tr_id="H0UPCNT0",
            collected_at=received_at,
        )
        self._latest = observation
        return observation

    def get_latest(self, underlying_symbol: str = "KOSPI200") -> KISIndexPriceObservation | None:
        if str(underlying_symbol).strip() != "KOSPI200":
            return None
        return self._latest
