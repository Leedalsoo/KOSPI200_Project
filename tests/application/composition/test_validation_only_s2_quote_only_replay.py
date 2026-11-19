
from datetime import datetime
from types import SimpleNamespace

from application.composition.automated_virtual_trading_loop import (
    AutomatedVirtualTradingLoop,
)
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from tests.application.composition.test_validation_only_s2_scenario_alternative_provider import (
    _provider,
)


def _quote_tick():
    return SimpleNamespace(
        timestamp="2026-10-12T09:26:00+09:00",
        seq_id=1,
        symbol="SYNTHETIC_CONTRACT:S2:QUOTE_ONLY",
        option_source="SYNTHETIC:DERIVED_SCENARIO",
        bid_price=39.60,
        ask_price=41.50,
        underlying_price=1034.62,
        last_price=None,
        volume=None,
    )


def _loop(supervisor, order):
    loop = AutomatedVirtualTradingLoop.__new__(AutomatedVirtualTradingLoop)
    loop.runtime_evidence_supervisor = supervisor
    loop.last_runtime_evidence_supervision = None
    loop._quote_only_events = []
    loop.context_builder = lambda tick, state: order.append("context") or {}
    loop.strategy_hub = SimpleNamespace(
        run=lambda contexts: (
            order.append("strategy"),
            SimpleNamespace(failures=(), signals=()),
        )[1]
    )
    loop.runtime_stop_switch = SimpleNamespace(
        trip=lambda reason: order.append(("trip", reason))
    )
    return loop


def test_t10_quote_only_tick_runs_evidence_supervisor_before_strategy_without_orders():
    order = []

    class _Supervisor:
        def evaluate(self, tick):
            order.append("supervisor")
            return SimpleNamespace(
                candidate_source="PROVENANCE_PRESERVING_ALTERNATIVE",
                stop_snapshot=SimpleNamespace(status="ARMED"),
            )

    loop = _loop(_Supervisor(), order)
    event = loop.on_quote_only_tick(_quote_tick())

    assert order == ["supervisor", "context", "strategy"]
    assert event["status"] == "EVALUATED_NO_EXECUTION"
    assert event["order_routing"] == "NOT_INVOKED"
    assert event["evidence_candidate_source"] == "PROVENANCE_PRESERVING_ALTERNATIVE"
    assert event["evidence_stop_status"] == "ARMED"


def test_t10_quote_only_tick_blocks_when_x2_is_not_armed():
    order = []

    class _Supervisor:
        def evaluate(self, tick):
            order.append("supervisor")
            return SimpleNamespace(
                candidate_source=None,
                stop_snapshot=SimpleNamespace(status="TRIPPED"),
            )

    loop = _loop(_Supervisor(), order)
    event = loop.on_quote_only_tick(_quote_tick())

    assert order == ["supervisor"]
    assert event["status"] == "BLOCKED"
    assert event["reason"] == "X2_RUNTIME_STOP_LATCH_NOT_ARMED"


def test_t10_quote_only_supervisor_exception_latches_x2_and_skips_strategy():
    order = []

    class _Supervisor:
        def evaluate(self, tick):
            order.append("supervisor")
            raise RuntimeError("EVIDENCE_SOURCE_FAILURE")

    loop = _loop(_Supervisor(), order)
    event = loop.on_quote_only_tick(_quote_tick())

    assert order[0] == "supervisor"
    assert order[1][0] == "trip"
    assert event["status"] == "EVIDENCE_SUPERVISION_FAILED"
    assert event["order_routing"] == "NOT_INVOKED"


def test_t10_s2_sidecar_quotes_publish_to_virtual_market_quote_only_path():
    provider = _provider("2026-10-12T09:26:00+09:00")
    tick = provider.build_quote_only_tick(seq_id=17)
    quote_payload = provider.option_quotes_at(
        datetime.fromisoformat("2026-10-12T09:26:00+09:00")
    )
    assert len(quote_payload) == 4
    assert tick.last_price is None
    assert tick.volume is None
    assert tick.validation_only is True

    market = VirtualMarketSimulatorRuntime(option_master=None)
    received = []
    market.set_authoritative_option_quote_provider(provider.option_quotes_at)
    market.subscribe_quote_only(received.append)

    published = market.publish_replay_tick(tick)

    assert published is tick
    assert received == [tick]
    assert len(market.option_quotes) == 4
    assert all(
        quote["source"] == "SYNTHETIC:DERIVED_SCENARIO"
        and quote["contract_identity_authority"] == "SYNTHETIC_ONLY_NOT_KIS_MASTER"
        for quote in market.option_quotes.values()
    )





def test_t10_s2_evidence_only_mode_skips_strategy_and_decision_context():
    calls = []

    class _Supervisor:
        def evaluate(self, tick):
            calls.append("supervisor")
            return SimpleNamespace(
                candidate_source="PROVENANCE_PRESERVING_ALTERNATIVE",
                stop_snapshot=SimpleNamespace(status="ARMED"),
            )

    loop = AutomatedVirtualTradingLoop.__new__(AutomatedVirtualTradingLoop)
    loop.runtime_evidence_supervisor = _Supervisor()
    loop.last_runtime_evidence_supervision = None
    loop._quote_only_events = []
    loop.validation_only_s2_replay = True
    loop.context_builder = lambda *_: (_ for _ in ()).throw(
        AssertionError("S2 evidence-only replay must not invoke strategy context")
    )
    loop.strategy_hub = SimpleNamespace(
        run=lambda *_: (_ for _ in ()).throw(
            AssertionError("S2 evidence-only replay must not invoke strategies")
        )
    )
    tick = SimpleNamespace(
        timestamp="2026-10-12T09:26:00+09:00",
        seq_id=1,
        symbol="SYNTHETIC_CONTRACT:S2:QUOTE_ONLY",
        option_source="SYNTHETIC:DERIVED_SCENARIO",
        bid_price=39.60,
        ask_price=41.50,
        underlying_price=1034.62,
        last_price=None,
        volume=None,
    )

    event = loop.on_quote_only_tick(tick)

    assert calls == ["supervisor"]
    assert event["status"] == "EVIDENCE_VALIDATED_NO_EXECUTION"
    assert event["order_routing"] == "NOT_INVOKED"
    assert "NO STRATEGY/DECISION/ORDER PATH" in event["reason"]
