from __future__ import annotations

from collections.abc import Awaitable, Callable

from contracts.kis_index_futures_market_ws_adapter import (
    KISIndexFuturesMarketWebSocketAdapter,
    KisIndexFuturesMarketObservation,
)
from infrastructure.kis.futures_market_transport import FuturesMarketTransport

ObservationCallback = Callable[[KisIndexFuturesMarketObservation], Awaitable[None] | None]


class KISIndexFuturesMarketConsumer:
    TRADE_TR_ID = "H0IFCNT0"
    QUOTE_TR_ID = "H0IFASP0"

    def __init__(
        self,
        transport: FuturesMarketTransport,
        adapter: KISIndexFuturesMarketWebSocketAdapter,
        on_observation: ObservationCallback,
    ) -> None:
        self._transport = transport
        self._adapter = adapter
        self._on_observation = on_observation

    async def start(self, symbol: str, *, include_quote: bool = True) -> None:
        await self._transport.connect()
        await self._transport.subscribe(self.TRADE_TR_ID, symbol)
        if include_quote:
            await self._transport.subscribe(self.QUOTE_TR_ID, symbol)

    async def receive_once(self) -> KisIndexFuturesMarketObservation:
        observation = self._adapter.adapt(await self._transport.recv())
        result = self._on_observation(observation)
        if result is not None:
            await result
        return observation

    async def close(self) -> None:
        await self._transport.close()
