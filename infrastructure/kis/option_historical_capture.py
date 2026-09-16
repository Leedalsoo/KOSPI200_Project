from __future__ import annotations

from datetime import date
from collections.abc import Callable
from typing import Protocol

from contracts.kis_index_option_market_ws_adapter import (
    KISIndexOptionMarketWebSocketAdapter,
    KisIndexOptionMarketObservation,
)
from infrastructure.kis.option_historical_recorder import KISOptionHistoricalRecorder
from infrastructure.kis.underlying_market_state import KISUnderlyingMarketState
from infrastructure.kis.option_orderbook_source import KISOptionOrderBookSource
from infrastructure.kis.track2_option_iv_observation_sink import KISTrack2OptionIVObservationSink


class OptionMarketWebSocketTransport(Protocol):
    async def connect(self) -> None: ...
    async def subscribe(self, tr_id: str, symbol: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


class KISOptionHistoricalCapture:
    """Connect a KIS option WebSocket transport to the historical recorder.

    This class owns the observation callback boundary only. It does not create
    contract identity, market values, or synthetic fallback data.
    """

    def __init__(
        self,
        transport: OptionMarketWebSocketTransport,
        recorder: KISOptionHistoricalRecorder,
        *,
        underlying_state: KISUnderlyingMarketState | None = None,
        adapter: KISIndexOptionMarketWebSocketAdapter | None = None,
        orderbook_source: KISOptionOrderBookSource | None = None,
        track2_option_iv_sink: KISTrack2OptionIVObservationSink | None = None,
    ) -> None:
        self._transport = transport
        self._recorder = recorder
        self._adapter = adapter or KISIndexOptionMarketWebSocketAdapter()
        self._underlying_state = underlying_state
        self._orderbook_source = orderbook_source
        self._track2_option_iv_sink = track2_option_iv_sink
        self._sequence = 0
        self._session_date: date | None = None

    @property
    def sequence(self) -> int:
        return self._sequence

    def start_session(self, session_date: str | date) -> None:
        self._session_date = (
            session_date
            if isinstance(session_date, date)
            else date.fromisoformat(str(session_date).replace("/", "-"))
        )
        self._sequence = 0

    async def connect_and_subscribe(self, symbol: str) -> None:
        if self._session_date is None:
            raise ValueError("HISTORICAL_CAPTURE_SESSION_DATE_REQUIRED")
        clean_symbol = str(symbol).strip()
        if not clean_symbol:
            raise ValueError("HISTORICAL_CAPTURE_SYMBOL_REQUIRED")
        await self._transport.connect()
        await self._transport.subscribe(self._adapter.TRADE_TR_ID, clean_symbol)
        await self._transport.subscribe(self._adapter.QUOTE_TR_ID, clean_symbol)

    def observe(
        self,
        frame: str,
        *,
        underlying_sequence: int = 0,
        validator: Callable[[KisIndexOptionMarketObservation], None] | None = None,
    ) -> KisIndexOptionMarketObservation:
        if self._session_date is None:
            raise ValueError("HISTORICAL_CAPTURE_SESSION_DATE_REQUIRED")
        observation = self._adapter.adapt(frame)
        if validator is not None:
            validator(observation)
        if self._track2_option_iv_sink is not None:
            self._track2_option_iv_sink.update(observation, session_date=self._session_date)
        if self._orderbook_source is not None and observation.order_book is not None:
            self._orderbook_source.update(observation)
        self._sequence += 1
        underlying_price = (
            self._underlying_state.price_for(required=False)
            if self._underlying_state is not None
            else None
        )
        self._recorder.record(
            observation,
            session_date=self._session_date,
            seq_id=self._sequence,
            source=observation.source,
            underlying_price=underlying_price,
            underlying_state=(self._underlying_state.state if self._underlying_state is not None else None),
            underlying_sequence=underlying_sequence,
        )
        return observation

    async def capture_one(
        self,
        *,
        underlying_sequence: int = 0,
        validator: Callable[[KisIndexOptionMarketObservation], None] | None = None,
    ) -> KisIndexOptionMarketObservation:
        frame = await self._transport.recv()
        return self.observe(
            frame,
            underlying_sequence=underlying_sequence,
            validator=validator,
        )

    async def close(self) -> None:
        await self._transport.close()
