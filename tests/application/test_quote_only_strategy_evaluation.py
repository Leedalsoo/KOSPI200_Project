from __future__ import annotations

from types import SimpleNamespace

from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop


class _Hub:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or SimpleNamespace(signals=(), failures=())

    def run(self, contexts):
        self.calls.append(contexts)
        return self.result


def _tick(**overrides):
    values = {
        "timestamp": "2026-10-20T10:00:00+09:00",
        "seq_id": 7,
        "symbol": "KIS-OPTION-TEST",
        "option_source": "SYNTHETIC",
        "bid_price": 10.0,
        "ask_price": 11.0,
        "underlying_price": 350.0,
        "last_price": None,
        "volume": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _loop(hub):
    loop = AutomatedVirtualTradingLoop.__new__(AutomatedVirtualTradingLoop)
    loop._quote_only_events = []
    loop.strategy_hub = hub
    loop.context_builder = lambda tick, state: {"S1": SimpleNamespace(strategy_id="S1", market_state=state)}
    return loop


def test_quote_only_event_evaluates_strategies_without_trade_field_inference_or_routing():
    hub = _Hub(SimpleNamespace(signals=(SimpleNamespace(strategy_id="S1"),), failures=()))
    loop = _loop(hub)

    event = loop.on_quote_only_tick(_tick())

    assert event["status"] == "EVALUATED_NO_EXECUTION"
    assert event["evaluation_mode"] == "QUOTE_ONLY_NO_EXECUTION"
    assert event["order_routing"] == "NOT_INVOKED"
    assert event["last_price"] is None
    assert event["volume"] is None
    assert event["strategy_results"]["S1"]["signals"] == 1
    assert len(hub.calls) == 1
    state = hub.calls[0]["S1"].market_state
    assert state.ticks["KOSPI200"].price == 350.0
    assert state.ticks["KOSPI200"].volume is None


def test_quote_only_event_blocks_when_authoritative_underlying_price_is_missing():
    hub = _Hub()
    loop = _loop(hub)

    event = loop.on_quote_only_tick(_tick(underlying_price=None))

    assert event["status"] == "BLOCKED"
    assert event["reason"] == "AUTHORITATIVE_UNDERLYING_PRICE_UNAVAILABLE"
    assert hub.calls == []


def test_quote_only_strategy_exception_is_recorded_without_execution():
    hub = _Hub()
    def fail(_contexts):
        raise RuntimeError("TEST_INPUT_FAILURE")
    hub.run = fail
    loop = _loop(hub)

    event = loop.on_quote_only_tick(_tick())

    assert event["status"] == "EVALUATION_FAILED"
    assert event["reason"] == "RuntimeError:TEST_INPUT_FAILURE"
    assert event["order_routing"] == "NOT_INVOKED"


def test_quote_only_event_blocks_invalid_two_sided_quote_before_strategy_evaluation():
    hub = _Hub()
    loop = _loop(hub)

    event = loop.on_quote_only_tick(_tick(bid_price=0.0))

    assert event["status"] == "BLOCKED"
    assert event["reason"] == "AUTHORITATIVE_TWO_SIDED_QUOTE_UNAVAILABLE"
    assert hub.calls == []