import asyncio
from datetime import datetime
from decimal import Decimal

from contracts.kis_index_futures_market_ws_adapter import KISIndexFuturesMarketWebSocketAdapter
from environments.live.market.kis_futures_market_data import KISFuturesMarketDataProvider
from infrastructure.kis.futures_market_consumer import KISIndexFuturesMarketConsumer


class FakeTransport:
    def __init__(self, frame: str):
        self.frame = frame
        self.calls = []

    async def connect(self):
        self.calls.append(("connect",))

    async def subscribe(self, tr_id: str, symbol: str):
        self.calls.append(("subscribe", tr_id, symbol))

    async def recv(self):
        return self.frame

    async def close(self):
        self.calls.append(("close",))


def trade_frame() -> str:
    values = [""] * 37
    values[0] = "101S12"
    values[1] = "093000"
    values[5] = "350.10"
    values[10] = "1234"
    values[35] = "350.20"
    values[36] = "350.00"
    return "0|H0IFCNT0|37|" + "^".join(values)


def test_kis_consumer_callback_reaches_live_market_provider_without_identity_synthesis():
    transport = FakeTransport(trade_frame())
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: "FUT-AUTH-1" if symbol == "101S12" else "",
        observed_at_resolver=lambda _: datetime(2026, 9, 6, 9, 30, 0),
    )

    def on_observation(observation):
        provider.publish(observation)
        return None

    consumer = KISIndexFuturesMarketConsumer(
        transport,
        KISIndexFuturesMarketWebSocketAdapter(),
        on_observation,
    )

    asyncio.run(consumer.start("101S12"))
    observation = asyncio.run(consumer.receive_once())
    state = provider.snapshot()

    assert observation.shrn_iscd == "101S12"
    assert state.ticks["FUT-AUTH-1"].price == Decimal("350.10")
# assert state.ticks["FUT-AUTH-1"].source_sequence is None
    assert transport.calls == [
        ("connect",),
        ("subscribe", "H0IFCNT0", "101S12"),
        ("subscribe", "H0IFASP0", "101S12"),
    ]
