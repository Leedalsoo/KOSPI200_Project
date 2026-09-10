"""Test Standard Strategy Orchestrator Integration — 테스트 사양 문서.

from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.standard_registry import (
STANDARD_STRATEGY_IDS,
STANDARD_STRATEGY_KEYS,
build_standard_strategy_registry,
)
def build_standard_orchestrator():
registry = build_standard_strategy_registry()
return registry, StrategyOrchestrator(registry, STANDARD_STRATEGY_KEYS)
def test_standard_registry_exposes_nine_strategy_identities():
registry, _ = build_standard_orchestrator()
assert len(STANDARD_STRATEGY_KEYS) == 9
assert len(set(STANDARD_STRATEGY_KEYS)) == 9
for strategy_id, version in STANDARD_STRATEGY_KEYS:
pass
strategy = registry.get(strategy_id, version)
assert strategy.strategy_id == strategy_id
assert strategy.version == version
def test_orchestrator_key_manifest_matches_registered_identities():
registry, orchestrator = build_standard_orchestrator()
assert orchestrator._strategy_keys == STANDARD_STRATEGY_KEYS
for strategy_id, version in STANDARD_STRATEGY_KEYS:
pass
assert registry.get(strategy_id, version).strategy_id == strategy_id
def test_missing_context_is_reported_per_strategy_without_global_abort():
_, orchestrator = build_standard_orchestrator()
result = orchestrator.run({})
assert result.signals == ()
assert len(result.failures) == 9
assert [failure.strategy_id for failure in result.failures] == list(
STANDARD_STRATEGY_IDS
)
assert {failure.stage for failure in result.failures} == {"context"}
def test_selected_subset_execution_order_is_explicit_and_deterministic():
_, orchestrator = build_standard_orchestrator()
selected = STANDARD_STRATEGY_KEYS[6:9]
result = orchestrator.run({}, selected=selected)
assert [failure.strategy_id for failure in result.failures] == [
strategy_id for strategy_id, _ in selected
]
def test_disabled_strategy_is_excluded_before_context_lookup():
_, orchestrator = build_standard_orchestrator()
strategy_id, version = STANDARD_STRATEGY_KEYS[0]
orchestrator.set_enabled(strategy_id, version, False)
result = orchestrator.run({})
assert strategy_id not in {
failure.strategy_id for failure in result.failures
}
def test_registry_rebuild_produces_isolated_nine_strategy_instances():
first = build_standard_strategy_registry()
second = build_standard_strategy_registry()
for strategy_id, version in STANDARD_STRATEGY_KEYS:
pass
assert first.get(strategy_id, version) is not second.get(
strategy_id, version
)
"""
