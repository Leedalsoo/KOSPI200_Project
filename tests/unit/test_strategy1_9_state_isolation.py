from application.strategy_hub.hub import StrategyHub
from core.strategy.contracts import StrategyContext
from core.strategy.standard_registry import STANDARD_STRATEGY_KEYS, build_standard_strategy_registry


def test_standard_strategy_registry_keeps_nine_strategy_instances_and_state_containers_independent():
    registry = build_standard_strategy_registry()
    strategies = [registry.get(strategy_id, version) for strategy_id, version in STANDARD_STRATEGY_KEYS]
    assert len(strategies) == 9
    assert len({id(strategy) for strategy in strategies}) == 9
    assert len({strategy.strategy_id for strategy in strategies}) == 9
    assert len({id(vars(strategy)) for strategy in strategies}) == 9
    assert all(registry.get(strategy.strategy_id, strategy.version) is strategy for strategy in strategies)

    # Verify mutable state containers used by the strategies are not shared across instances.
    mutable_state_objects = []
    for strategy in strategies:
        for key, value in vars(strategy).items():
            if key == "state" or key.startswith("_") and key not in {"_initialized"}:
                if isinstance(value, (dict, list, set)) or hasattr(value, "__dataclass_fields__"):
                    mutable_state_objects.append((strategy.strategy_id, key, id(value)))
    ids = [item[2] for item in mutable_state_objects]
    assert len(ids) == len(set(ids)), mutable_state_objects


def test_strategy_hub_evaluates_all_nine_with_unavailable_analytics_without_cross_strategy_signals():
    registry = build_standard_strategy_registry()
    hub = StrategyHub(registry, STANDARD_STRATEGY_KEYS)
    contexts = {strategy_id: StrategyContext(strategy_id=strategy_id, analytics=None)
        for strategy_id, _version in STANDARD_STRATEGY_KEYS}
    result = hub.run(contexts)
    assert result.failures == ()
    assert result.signals == ()
    assert all(hub.is_enabled(strategy_id, version) for strategy_id, version in STANDARD_STRATEGY_KEYS)
    assert len({id(registry.get(strategy_id, version)) for strategy_id, version in STANDARD_STRATEGY_KEYS}) == 9
