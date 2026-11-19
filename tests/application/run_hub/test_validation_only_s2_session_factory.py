
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
    assert order == ["supervisor"]
    assert event["status"] == "EVIDENCE_VALIDATED_NO_EXECUTION"
    assert event["order_routing"] == "NOT_INVOKED"
