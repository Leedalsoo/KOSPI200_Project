from datetime import datetime

from environments.virtual.broker.virtual_broker import VirtualBroker
from environments.virtual.broker.virtual_broker_api import VirtualBrokerApi
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from tests.support import build_test_option_master


class FakeExecution:
    def execute(self, command):
        return command
    def cancel(self, order_id):
        return order_id
    def query(self, order_id):
        return order_id


def test_virtual_exchange_feeds_virtual_broker_and_broker_api():
    exchange = VirtualMarketSimulatorRuntime(option_master=build_test_option_master())
    broker = VirtualBroker(FakeExecution(), market_data_handler=lambda tick: None)
    api = VirtualBrokerApi(broker, account=object())

    exchange.subscribe(lambda tick: broker.process_market_data(tick, option_quotes=exchange.option_quotes))
    ticks = list(exchange.generate_tick_stream(total_days=1, ticks_per_day=1))

    assert len(ticks) == 1
    snapshot = api.get_market_snapshot()
    assert snapshot["source"] == "VirtualBroker"
    assert snapshot["tick"] is ticks[0]
    quote = api.get_option_quote(option_type="CALL", strike=350.0, expiry="202609")
    assert quote is not None
    assert quote["contract_multiplier"] == 250000.0


def test_virtual_broker_requires_exchange_market_data_before_api_snapshot():
    broker = VirtualBroker(FakeExecution(), market_data_handler=lambda tick: None)
    api = VirtualBrokerApi(broker, account=object())
    try:
        api.get_market_snapshot()
    except RuntimeError as exc:
        assert str(exc) == "VIRTUAL_BROKER_MARKET_DATA_UNAVAILABLE"
    else:
        raise AssertionError("market snapshot must fail closed before exchange data arrives")
