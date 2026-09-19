from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Protocol

from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore


class RealtimeTransport(Protocol):
    async def connect(self) -> None: ...
    async def subscribe(self, tr_id: str, symbol: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


class KISRealtimeCollector:
    """Capture raw KIS realtime frames before any canonical adaptation."""

    def __init__(
        self,
        transport: RealtimeTransport,
        raw_store: KISRealtimeRawStore,
        *,
        max_reconnects: int = 1,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_reconnects < 0:
            raise ValueError("MAX_RECONNECTS_MUST_BE_NON_NEGATIVE")
        self._transport = transport
        self._raw_store = raw_store
        self._max_reconnects = max_reconnects
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._trading_date: str | None = None
        self._subscriptions: list[tuple[str, str]] = []
        self._sequence = 0

    async def start(self, trading_date: str, subscriptions: Sequence[tuple[str, str]]) -> None:
        clean_date = str(trading_date).strip()
        if not clean_date:
            raise ValueError("TRADING_DATE_REQUIRED")
        clean_subscriptions: list[tuple[str, str]] = []
        for tr_id, symbol in subscriptions:
            clean_tr_id = str(tr_id).strip()
            clean_symbol = str(symbol).strip()
            if not clean_tr_id or not clean_symbol:
                raise ValueError("TR_ID_AND_SYMBOL_REQUIRED")
            clean_subscriptions.append((clean_tr_id, clean_symbol))
        if not clean_subscriptions:
            raise ValueError("SUBSCRIPTIONS_REQUIRED")

        self._trading_date = clean_date
        self._subscriptions = clean_subscriptions
        self._sequence = 0
        await self._connect_and_subscribe()

    async def _connect_and_subscribe(self) -> None:
        await self._transport.connect()
        for tr_id, symbol in self._subscriptions:
            await self._transport.subscribe(tr_id, symbol)

    async def capture_one(self) -> dict:
        if self._trading_date is None:
            raise ValueError("COLLECTOR_SESSION_REQUIRED")
        attempts = 0
        while True:
            try:
                payload = await self._transport.recv()
                break
            except Exception:
                if attempts >= self._max_reconnects:
                    raise
                attempts += 1
                await self._connect_and_subscribe()

        parts = payload.split("|")
        if len(parts) < 2 or not parts[1].strip():
            raise ValueError("RAW_FRAME_TR_ID_REQUIRED")
        tr_id = parts[1].strip()
        symbol = ""
        if len(parts) >= 4:
            symbol = parts[3].split("^", 1)[0].strip()
        if not symbol:
            raise ValueError("RAW_FRAME_SYMBOL_REQUIRED")
        self._sequence += 1
        return self._raw_store.append(
            received_at=self._clock(),
            trading_date=self._trading_date,
            instrument=symbol,
            tr_id=tr_id,
            payload=payload,
            sequence=self._sequence,
        )

    async def close(self) -> None:
        await self._transport.close()
