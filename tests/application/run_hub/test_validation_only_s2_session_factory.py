
import pytest

from application.run_hub.contracts import RunContext
from application.run_hub.virtual_session_factory import create_virtual_run_session


def _context(*, environment="VIRTUAL", scenario="CALM"):
    return RunContext(
        run_id="SYNTHETIC:T10:SESSION-GUARD",
        environment=environment,
        scenario=scenario,
    )


def test_t10_s2_replay_requires_virtual_environment_before_startup(tmp_path):
    with pytest.raises(ValueError, match="T10_S2_REPLAY_VIRTUAL_ENVIRONMENT_REQUIRED"):
        create_virtual_run_session(
            _context(environment="LIVE"),
            option_master=object(),
            validation_only_s2_replay=True,
            validation_only_s2_original_source_root=tmp_path,
        )


def test_t10_s2_replay_requires_explicit_scenario_before_startup(tmp_path):
    with pytest.raises(ValueError, match="T10_S2_REPLAY_CALM_SCENARIO_REQUIRED"):
        create_virtual_run_session(
            _context(scenario="HIGH_VOLATILITY"),
            option_master=object(),
            validation_only_s2_replay=True,
            validation_only_s2_original_source_root=tmp_path,
        )


def test_t10_s2_replay_requires_original_source_root_before_startup():
    with pytest.raises(ValueError, match="T10_S2_REPLAY_ORIGINAL_SOURCE_ROOT_REQUIRED"):
        create_virtual_run_session(
            _context(),
            option_master=None,
            validation_only_s2_replay=True,
        )


def test_t10_s2_replay_owns_supervisor_factory_before_startup(tmp_path):
    with pytest.raises(ValueError, match="T10_S2_REPLAY_SUPERVISOR_IS_FACTORY_MANAGED"):
        create_virtual_run_session(
            _context(),
            option_master=object(),
            runtime_evidence_supervisor=object(),
            validation_only_s2_replay=True,
            validation_only_s2_original_source_root=tmp_path,
        )


def test_t10_original_source_root_requires_explicit_replay_mode(tmp_path):
    with pytest.raises(ValueError, match="T10_S2_SOURCE_ROOT_REQUIRES_EXPLICIT_REPLAY_MODE"):
        create_virtual_run_session(
            _context(),
            option_master=object(),
            validation_only_s2_original_source_root=tmp_path,
        )


def test_t10_s2_replay_rejects_external_option_master_to_prevent_lookahead(tmp_path):
    with pytest.raises(ValueError, match="T10_S2_REPLAY_EXTERNAL_OPTION_MASTER_FORBIDDEN"):
        create_virtual_run_session(
            _context(),
            option_master=object(),
            validation_only_s2_replay=True,
            validation_only_s2_original_source_root=tmp_path,
        )


def test_t10_s2_replay_rejects_unscoped_historical_store(tmp_path):
    context = RunContext(
        run_id="SYNTHETIC:T10:SESSION-GUARD",
        environment="VIRTUAL",
        scenario="CALM",
        historical_store_path=str(tmp_path / "historical.observations.jsonl"),
    )
    with pytest.raises(ValueError, match="T10_S2_REPLAY_USES_PINNED_SCENARIO_TICK_ONLY"):
        create_virtual_run_session(
            context,
            option_master=None,
            validation_only_s2_replay=True,
            validation_only_s2_original_source_root=tmp_path,
        )


def test_t10_s2_replay_rejects_strategy_execution_configuration(tmp_path):
    context = RunContext(
        run_id="SYNTHETIC:T10:SESSION-GUARD",
        environment="VIRTUAL",
        scenario="CALM",
        strategy_keys=(("strategy", "example"),),
    )
    with pytest.raises(ValueError, match="T10_S2_REPLAY_STRATEGIES_MUST_BE_EMPTY"):
        create_virtual_run_session(
            context,
            option_master=None,
            validation_only_s2_replay=True,
            validation_only_s2_original_source_root=tmp_path,
        )


from types import SimpleNamespace

from application.run_hub.virtual_session_factory import (
    attach_validation_only_s2_quote_only_replay,
)
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from tests.application.composition.test_validation_only_s2_quote_only_replay import (
    _loop,
)
from tests.application.composition.test_validation_only_s2_scenario_alternative_provider import (
    _provider,
)


def test_t10_session_attachment_publishes_one_evidence_only_s2_candidate():
    order = []

    class _Supervisor:
        def evaluate(self, tick):
            order.append("supervisor")
            return SimpleNamespace(
                candidate_source="PROVENANCE_PRESERVING_ALTERNATIVE",
                stop_snapshot=SimpleNamespace(status="ARMED"),
            )

    alternative = _provider("2026-10-12T09:26:00+09:00")
    chain = SimpleNamespace(
        supervisor=_Supervisor(),
        alternative_provider=alternative,
    )
    market = VirtualMarketSimulatorRuntime(option_master=None)
    bundle = SimpleNamespace(market=market)
    loop = _loop(chain.supervisor, order)
    market.subscribe_quote_only(loop.on_quote_only_tick)

    tick = attach_validation_only_s2_quote_only_replay(loop, bundle, chain)
    event = loop.replay_validation_only_s2_candidate()

    assert tick.last_price is None and tick.volume is None
    assert loop.validation_only_s2_replay is True
    assert loop.signal_observation_only is True
    assert len(market.option_quotes) == 4
    assert order == ["supervisor"] * 4
    assert len(event) == 4
    assert {item["u21_leg_role"] for item in event} == {
        "inner_put", "inner_call", "outer_put", "outer_call",
    }
    assert {item["u21_quote_side"] for item in event} == {"BUY", "SELL"}
    assert all(item["u21_policy_decision"] == "PRIMARY_QUOTE_ACCEPTED" for item in event)
    assert all(item["status"] == "EVIDENCE_VALIDATED_NO_EXECUTION" for item in event)
    assert all(item["order_routing"] == "NOT_INVOKED" for item in event)
    assert len({item["u21_derived_quote_digest"] for item in event}) == 4


def test_t10_session_attachment_replays_four_contract_events_with_individual_policy_diagnostics():
    order = []

    class _Supervisor:
        def evaluate(self, tick):
            order.append(("supervisor", tick.leg_role))
            return SimpleNamespace(
                candidate_source="PROVENANCE_PRESERVING_ALTERNATIVE",
                stop_snapshot=SimpleNamespace(status="ARMED"),
            )

    alternative = _provider("2026-10-12T09:26:00+09:00")
    chain = SimpleNamespace(supervisor=_Supervisor(), alternative_provider=alternative)
    market = VirtualMarketSimulatorRuntime(option_master=None)
    bundle = SimpleNamespace(market=market)
    loop = _loop(chain.supervisor, order)
    market.subscribe_quote_only(loop.on_quote_only_tick)

    attach_validation_only_s2_quote_only_replay(loop, bundle, chain)
    events = loop.replay_validation_only_s2_candidate()

    assert len(events) == 4
    assert [event["u21_leg_role"] for event in events] == [
        "inner_put", "inner_call", "outer_put", "outer_call",
    ]
    assert [event["u21_quote_side"] for event in events] == ["BUY", "BUY", "SELL", "SELL"]
    assert all(event["u21_policy_decision"] == "PRIMARY_QUOTE_ACCEPTED" for event in events)
    assert all(event["u21_policy_reason"] == "PRIMARY_QUOTE_WITHIN_EXPLICIT_VALIDATION_POLICY" for event in events)
    assert all(event["order_routing"] == "NOT_INVOKED" for event in events)
    assert len({event["u21_derived_quote_digest"] for event in events}) == 4
    assert len(order) == 4
    assert {event["run_id"] for event in events} == {loop.run_id}
    assert len({event["replay_run_id"] for event in events}) == 1
    assert {event["replay_invocation"] for event in events} == {1}


def test_t10_s2_replay_rejects_missing_quote_only_subscriber_events():
    alternative = _provider("2026-10-12T09:26:00+09:00")
    chain = SimpleNamespace(
        supervisor=SimpleNamespace(evaluate=lambda tick: SimpleNamespace(
            candidate_source="PROVENANCE_PRESERVING_ALTERNATIVE",
            stop_snapshot=SimpleNamespace(status="ARMED"),
        )),
        alternative_provider=alternative,
    )
    market = VirtualMarketSimulatorRuntime(option_master=None)
    loop = _loop(chain.supervisor, [])
    attach_validation_only_s2_quote_only_replay(loop, SimpleNamespace(market=market), chain)

    with pytest.raises(ValueError, match="T10_S2_QUOTE_ONLY_REPLAY_EVENT_COUNT_MISMATCH"):
        loop.replay_validation_only_s2_candidate()
    assert loop.quote_only_events == ()


def test_t10_s2_replay_rejects_duplicate_quote_only_subscriber_delivery():
    alternative = _provider("2026-10-12T09:26:00+09:00")
    chain = SimpleNamespace(
        supervisor=SimpleNamespace(evaluate=lambda tick: SimpleNamespace(
            candidate_source="PROVENANCE_PRESERVING_ALTERNATIVE",
            stop_snapshot=SimpleNamespace(status="ARMED"),
        )),
        alternative_provider=alternative,
    )
    market = VirtualMarketSimulatorRuntime(option_master=None)
    loop = _loop(chain.supervisor, [])
    market.subscribe_quote_only(loop.on_quote_only_tick)
    market.subscribe_quote_only(loop.on_quote_only_tick)
    attach_validation_only_s2_quote_only_replay(loop, SimpleNamespace(market=market), chain)

    with pytest.raises(ValueError, match="T10_S2_QUOTE_ONLY_REPLAY_EVENT_COUNT_MISMATCH"):
        loop.replay_validation_only_s2_candidate()
    assert len(loop.quote_only_events) == 8


def test_t10_s2_replay_rejects_event_identity_or_order_mismatch(monkeypatch):
    alternative = _provider("2026-10-12T09:26:00+09:00")
    chain = SimpleNamespace(
        supervisor=SimpleNamespace(evaluate=lambda tick: SimpleNamespace(
            candidate_source="PROVENANCE_PRESERVING_ALTERNATIVE",
            stop_snapshot=SimpleNamespace(status="ARMED"),
        )),
        alternative_provider=alternative,
    )
    market = VirtualMarketSimulatorRuntime(option_master=None)
    loop = _loop(chain.supervisor, [])
    market.subscribe_quote_only(loop.on_quote_only_tick)
    attach_validation_only_s2_quote_only_replay(loop, SimpleNamespace(market=market), chain)
    original = loop.on_quote_only_tick

    def altered(tick):
        event = original(tick)
        event["instrument_id"] = "TAMPERED_INSTRUMENT"
        return event

    market._quote_only_subscribers = [altered]
    with pytest.raises(ValueError, match="T10_S2_QUOTE_ONLY_REPLAY_EVENT_IDENTITY_OR_ORDER_MISMATCH"):
        loop.replay_validation_only_s2_candidate()


def test_t10_s2_explicit_replay_invocations_have_distinct_run_identity():
    alternative = _provider("2026-10-12T09:26:00+09:00")
    chain = SimpleNamespace(
        supervisor=SimpleNamespace(evaluate=lambda tick: SimpleNamespace(
            candidate_source="PROVENANCE_PRESERVING_ALTERNATIVE",
            stop_snapshot=SimpleNamespace(status="ARMED"),
        )),
        alternative_provider=alternative,
    )
    market = VirtualMarketSimulatorRuntime(option_master=None)
    loop = _loop(chain.supervisor, [])
    market.subscribe_quote_only(loop.on_quote_only_tick)
    attach_validation_only_s2_quote_only_replay(loop, SimpleNamespace(market=market), chain)

    first = loop.replay_validation_only_s2_candidate()
    second = loop.replay_validation_only_s2_candidate()

    assert len(first) == len(second) == 4
    assert {event["replay_invocation"] for event in first} == {1}
    assert {event["replay_invocation"] for event in second} == {2}
    assert len({event["replay_run_id"] for event in first + second}) == 2
    assert {event["run_id"] for event in first + second} == {loop.run_id}
    assert len(loop.quote_only_events) == 8


def test_t10_s2_restart_uses_new_session_run_id_and_does_not_restore_ephemeral_quote_diagnostics():
    alternative = _provider("2026-10-12T09:26:00+09:00")
    chain = SimpleNamespace(
        supervisor=SimpleNamespace(evaluate=lambda tick: SimpleNamespace(
            candidate_source="PROVENANCE_PRESERVING_ALTERNATIVE",
            stop_snapshot=SimpleNamespace(status="ARMED"),
        )),
        alternative_provider=alternative,
    )
    first_market = VirtualMarketSimulatorRuntime(option_master=None)
    first_loop = _loop(chain.supervisor, [])
    first_loop.run_id = "SYNTHETIC:T10:SESSION-A"
    first_market.subscribe_quote_only(first_loop.on_quote_only_tick)
    attach_validation_only_s2_quote_only_replay(first_loop, SimpleNamespace(market=first_market), chain)
    first_events = first_loop.replay_validation_only_s2_candidate()

    restarted_market = VirtualMarketSimulatorRuntime(option_master=None)
    restarted_loop = _loop(chain.supervisor, [])
    restarted_loop.run_id = "SYNTHETIC:T10:SESSION-B"
    restarted_market.subscribe_quote_only(restarted_loop.on_quote_only_tick)
    attach_validation_only_s2_quote_only_replay(
        restarted_loop, SimpleNamespace(market=restarted_market), chain,
    )
    assert restarted_loop.quote_only_events == ()
    restarted_events = restarted_loop.replay_validation_only_s2_candidate()

    assert len(first_events) == len(restarted_events) == 4
    assert {event["run_id"] for event in first_events} == {"SYNTHETIC:T10:SESSION-A"}
    assert {event["run_id"] for event in restarted_events} == {"SYNTHETIC:T10:SESSION-B"}
    assert {event["replay_run_id"] for event in first_events}.isdisjoint(
        {event["replay_run_id"] for event in restarted_events}
    )
    assert restarted_loop.quote_only_events == restarted_events
