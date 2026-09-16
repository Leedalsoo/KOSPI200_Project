from application.bootstrap import create_virtual_runtime_bootstrap
from application.run_hub.contracts import RunContextFactory
from application.strategy_hub.hub import StrategyHub
from core.strategy.standard_registry import build_standard_strategy_registry, STANDARD_STRATEGY_KEYS


def test_strategy_hub_owns_nine_strategy_selection_without_runtime_dependency():
    hub = StrategyHub(build_standard_strategy_registry(), STANDARD_STRATEGY_KEYS)
    assert len(hub.strategy_keys) == 9
    key = hub.strategy_keys[0]
    assert hub.is_enabled(*key)
    hub.set_enabled(*key, enabled=False)
    assert not hub.is_enabled(*key)
    hub.set_enabled(*key, enabled=True)


def test_virtual_bootstrap_exposes_runtime_and_control_tower_hubs():
    bootstrap = create_virtual_runtime_bootstrap()
    assert bootstrap.strategy_hub is bootstrap.automated_loop.strategy_hub
    assert bootstrap.runtime_hub.loop is bootstrap.automated_loop
    assert bootstrap.control_tower_hub.strategy_hub is bootstrap.strategy_hub
    assert bootstrap.control_tower_hub.run_context.run_id
    assert bootstrap.runtime_controller.environment_hub.active is bootstrap.bundle
    bootstrap.runtime_controller.stop()


def test_run_context_factory_requires_independent_run_identity():
    factory = RunContextFactory()
    first = factory.create(run_id="RUN-1", environment="virtual")
    second = factory.create(run_id="RUN-2", environment="virtual")
    assert first.run_id != second.run_id
