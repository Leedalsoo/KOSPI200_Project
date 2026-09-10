import asyncio

from contracts.kis_index_futures_market_ws_adapter import KISIndexFuturesMarketWebSocketAdapter
from infrastructure.kis.futures_market_consumer import KISIndexFuturesMarketConsumer


class FakeTransport:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    async def connect(self):
        self.calls.append(("connect",))

    async def subscribe(self, tr_id, symbol):
        self.calls.append(("subscribe", tr_id, symbol))

    async def unsubscribe(self, tr_id, symbol):
        self.calls.append(("unsubscribe", tr_id, symbol))

    async def recv(self):
        return self.frame

    async def close(self):
        self.calls.append(("close",))


def _trade_frame():
    values = [""] * 37
    values[0] = "101S12"
    values[1] = "093000"
    values[5] = "350.10"
    values[10] = "1234"
    values[35] = "350.20"
    values[36] = "350.00"
    return "0|H0IFCNT0|37|" + "^".join(values)


def test_consumer_connects_subscribes_and_adapts_trade_frame():
    transport = FakeTransport(_trade_frame())
    received = []
    consumer = KISIndexFuturesMarketConsumer(transport, KISIndexFuturesMarketWebSocketAdapter(), received.append)

    asyncio.run(consumer.start("101S12"))
    observation = asyncio.run(consumer.receive_once())

    assert transport.calls == [
        ("connect",),
        ("subscribe", "H0IFCNT0", "101S12"),
        ("subscribe", "H0IFASP0", "101S12"),
    ]
    assert observation.shrn_iscd == "101S12"
    assert str(observation.price) == "350.10"
    assert received == [observation]
