
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


def test_t10_u21_policy_adapter_accepts_manifest_bound_synthetic_quote_without_raw_hash():
    from application.composition.validation_only_u21_quote_policy_adapter import (
        ValidationOnlyU21QuotePolicyAdapter,
    )

    provider = _provider("2026-10-12T09:26:00+09:00")
    tick = provider.build_quote_only_tick(seq_id=29)
    adapter = ValidationOnlyU21QuotePolicyAdapter(provider)
    result = adapter.evaluate(tick)

    assert result.decision.value == "PRIMARY_QUOTE_ACCEPTED"
    assert result.order_submission_enabled is False
    assert adapter.order_submission_enabled is False
    assert len(adapter.last_quote_digest) == 64
    assert result.source == "SYNTHETIC:DERIVED_SCENARIO"


def test_t10_u21_policy_adapter_stale_quote_reports_fallback_unavailable():
    from dataclasses import replace
    from application.composition.validation_only_u21_quote_policy_adapter import (
        ValidationOnlyU21QuotePolicyAdapter,
    )

    provider = _provider("2026-10-12T09:26:00+09:00")
    tick = provider.build_quote_only_tick(seq_id=30)
    stale_tick = replace(tick, timestamp="2026-10-12T09:26:06+09:00")
    result = ValidationOnlyU21QuotePolicyAdapter(provider).evaluate(stale_tick)

    assert result.decision.value == "FALLBACK_UNAVAILABLE_BLOCKED"
    assert "PRIMARY_QUOTE_STALE" in result.reason
    assert "FALLBACK_QUOTE_MISSING" in result.reason
    assert result.order_submission_enabled is False


def test_t10_u21_policy_adapter_missing_identity_provenance_does_not_accept():
    from dataclasses import replace
    from application.composition.validation_only_u21_quote_policy_adapter import (
        ValidationOnlyU21QuotePolicyAdapter,
    )

    provider = _provider("2026-10-12T09:26:00+09:00")
    tick = provider.build_quote_only_tick(seq_id=31)
    incomplete = replace(tick, instrument_id="", symbol="")
    result = ValidationOnlyU21QuotePolicyAdapter(provider).evaluate(incomplete)

    assert result.decision.value == "POLICY_INPUT_BLOCKED"
    assert result.reason == "U21_EVALUATION_CONTEXT_UNVERIFIED"
    assert result.order_submission_enabled is False


def test_t10_quote_only_u21_adapter_exception_skips_strategy_and_orders():
    order = []

    class _BrokenAdapter:
        validation_only = True
        order_submission_enabled = False
        def evaluate(self, tick):
            raise RuntimeError("U21_POLICY_TEST_FAILURE")

    loop = _loop(None, order)
    loop.validation_only_u21_quote_policy_adapter = _BrokenAdapter()
    event = loop.on_quote_only_tick(_quote_tick())

    assert event["status"] == "U21_POLICY_EVALUATION_FAILED"
    assert "U21_POLICY_TEST_FAILURE" in event["reason"]
    assert order == []
    assert event["order_routing"] == "NOT_INVOKED"


def test_t10_quote_only_u21_adapter_rejects_order_enabled_result():
    order = []

    class _UnsafeAdapter:
        validation_only = True
        order_submission_enabled = False
        def evaluate(self, tick):
            return SimpleNamespace(
                decision=SimpleNamespace(value="PRIMARY_QUOTE_ACCEPTED"),
                reason="synthetic-test",
                source="SYNTHETIC:DERIVED_SCENARIO",
                spread_value=None,
                order_submission_enabled=True,
            )

    loop = _loop(None, order)
    loop.validation_only_u21_quote_policy_adapter = _UnsafeAdapter()
    event = loop.on_quote_only_tick(_quote_tick())

    assert event["status"] == "U21_POLICY_EVALUATION_FAILED"
    assert "ORDER_SUBMISSION_MUST_REMAIN_DISABLED" in event["reason"]
    assert order == []
    assert event["order_routing"] == "NOT_INVOKED"


def test_t10_u21_policy_adapter_gates_quote_only_strategy_until_policy_accepts():
    from application.composition.validation_only_u21_quote_policy_adapter import (
        ValidationOnlyU21QuotePolicyAdapter,
    )

    provider = _provider("2026-10-12T09:26:00+09:00")
    tick = provider.build_quote_only_tick(seq_id=32)
    order = []
    loop = _loop(None, order)
    loop.validation_only_u21_quote_policy_adapter = ValidationOnlyU21QuotePolicyAdapter(provider)
    event = loop.on_quote_only_tick(tick)

    assert order == ["context", "strategy"]
    assert event["status"] == "EVALUATED_NO_EXECUTION"
    assert event["u21_policy_decision"] == "PRIMARY_QUOTE_ACCEPTED"
    assert len(event["u21_derived_quote_digest"]) == 64
    assert event["order_routing"] == "NOT_INVOKED"


def test_t10_u21_policy_rejection_prevents_quote_only_strategy_evaluation():
    from dataclasses import replace
    from application.composition.validation_only_u21_quote_policy_adapter import (
        ValidationOnlyU21QuotePolicyAdapter,
    )

    provider = _provider("2026-10-12T09:26:00+09:00")
    tick = replace(
        provider.build_quote_only_tick(seq_id=33),
        timestamp="2026-10-12T09:26:06+09:00",
    )
    order = []
    loop = _loop(None, order)
    loop.validation_only_u21_quote_policy_adapter = ValidationOnlyU21QuotePolicyAdapter(provider)
    event = loop.on_quote_only_tick(tick)

    assert order == []
    assert event["status"] == "BLOCKED"
    assert event["u21_policy_decision"] == "FALLBACK_UNAVAILABLE_BLOCKED"
    assert "PRIMARY_QUOTE_STALE" in event["reason"]
    assert event["order_routing"] == "NOT_INVOKED"
