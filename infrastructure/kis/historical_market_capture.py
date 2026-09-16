from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from contracts.kis_index_futures_market_ws_adapter import (
    KISIndexFuturesMarketWebSocketAdapter,
    KisIndexFuturesMarketObservation,
)
from infrastructure.kis.futures_market_transport import FuturesMarketTransport
from infrastructure.kis.option_historical_capture import KISOptionHistoricalCapture
from infrastructure.kis.option_historical_recorder import KISOptionHistoricalRecorder
from infrastructure.kis.underlying_market_state import KISUnderlyingMarketState


@dataclass(frozen=True)
class HistoricalCaptureSession:
    session_date: date
    option_symbol: str
    underlying_symbol: str


class KISHistoricalMarketCapture:
    """Compose option and underlying KIS WebSocket capture boundaries."""

    def __init__(
        self,
        option_capture: KISOptionHistoricalCapture,
        underlying_transport: FuturesMarketTransport,
        *,
        underlying_state: KISUnderlyingMarketState,
        underlying_adapter: KISIndexFuturesMarketWebSocketAdapter | None = None,
        max_underlying_age_seconds: float = 2.0,
    ) -> None:
        if max_underlying_age_seconds < 0:
            raise ValueError("HISTORICAL_CAPTURE_INVALID_UNDERLYING_AGE")
        self._option_capture = option_capture
        self._underlying_transport = underlying_transport
        self._underlying_state = underlying_state
        self._underlying_adapter = underlying_adapter or KISIndexFuturesMarketWebSocketAdapter()
        self._max_underlying_age_seconds = max_underlying_age_seconds
        self._underlying_sequence = 0
        self._session: HistoricalCaptureSession | None = None

    @property
    def session(self) -> HistoricalCaptureSession | None:
        return self._session

    @property
    def underlying_sequence(self) -> int:
        return self._underlying_sequence

    def start_session(self, session_date: str | date, *, option_symbol: str, underlying_symbol: str) -> None:
        parsed_date = session_date if isinstance(session_date, date) else date.fromisoformat(str(session_date).replace("/", "-"))
        if not option_symbol.strip():
            raise ValueError("HISTORICAL_CAPTURE_OPTION_SYMBOL_REQUIRED")
        if not underlying_symbol.strip():
            raise ValueError("HISTORICAL_CAPTURE_UNDERLYING_SYMBOL_REQUIRED")
        self._session = HistoricalCaptureSession(parsed_date, option_symbol.strip(), underlying_symbol.strip())
        self._underlying_sequence = 0
        self._option_capture.start_session(parsed_date)

    @staticmethod
    def _observation_seconds(observed_hour: str) -> float:
        raw = str(observed_hour).strip()
        if len(raw) == 6:
            parsed = datetime.strptime(raw, "%H%M%S")
        elif len(raw) == 9:
            parsed = datetime.strptime(raw, "%H%M%S%f")
        else:
            raise ValueError("INVALID_KIS_OBSERVED_TIME")
        return (
            parsed.hour * 3600
            + parsed.minute * 60
            + parsed.second
            + parsed.microsecond / 1_000_000
        )

    def _require_temporally_valid_underlying(self, option_observed_hour: str) -> None:
        state = self._underlying_state.state
        if state is None:
            raise ValueError("AUTHORITATIVE_UNDERLYING_PRICE_REQUIRED")
        option_seconds = self._observation_seconds(option_observed_hour)
        underlying_seconds = self._observation_seconds(state.observed_hour)
        age = option_seconds - underlying_seconds
        if age < 0 or age > self._max_underlying_age_seconds:
            raise ValueError("AUTHORITATIVE_UNDERLYING_STALE")

    async def connect(self) -> None:
        if self._session is None:
            raise ValueError("HISTORICAL_CAPTURE_SESSION_DATE_REQUIRED")
        await self._option_capture.connect_and_subscribe(self._session.option_symbol)
        await self._underlying_transport.connect()
        await self._underlying_transport.subscribe(self._underlying_adapter.TRADE_TR_ID, self._session.underlying_symbol)
        await self._underlying_transport.subscribe(self._underlying_adapter.QUOTE_TR_ID, self._session.underlying_symbol)

    async def capture_underlying_once(self) -> KisIndexFuturesMarketObservation:
        if self._session is None:
            raise ValueError("HISTORICAL_CAPTURE_SESSION_DATE_REQUIRED")
        observation = self._underlying_adapter.adapt(await self._underlying_transport.recv())
        if observation.shrn_iscd != self._session.underlying_symbol:
            raise ValueError("HISTORICAL_CAPTURE_UNEXPECTED_UNDERLYING_SYMBOL")
        self._underlying_sequence += 1
        self._underlying_state.update(observation)
        return observation

    async def capture_option_once(self):
        if self._session is None:
            raise ValueError("HISTORICAL_CAPTURE_SESSION_DATE_REQUIRED")
        return await self._option_capture.capture_one(
            underlying_sequence=self._underlying_sequence,
            validator=lambda observation: self._require_temporally_valid_underlying(
                observation.observed_hour
            ),
        )

    async def close(self) -> None:
        await self._option_capture.close()
        await self._underlying_transport.close()
