"""Test Standard Strategy Orchestrator Full Integration — 테스트 사양 문서.

from core.strategy.integration_fixtures import contexts
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.standard_registry import (
STANDARD_STRATEGY_KEYS,
build_standard_strategy_registry,
)
def build_orchestrator():
registry = build_standard_strategy_registry()
return StrategyOrchestrator(registry, STANDARD_STRATEGY_KEYS)
def signal_identity(result):
return tuple(
(signal.strategy_id, signal.direction, signal.confidence, signal.reason)
for signal in result.signals
)
def failure_identity(result):
return tuple(
(
failure.strategy_id,
failure.version,
failure.stage,
failure.error_type,
failure.message,
)
for failure in result.failures
)
def test_all_nine_actual_strategies_complete_full_lifecycle():
result = build_orchestrator().run(contexts())
assert result.failures == ()
assert all(
signal.strategy_id in {
strategy_id for strategy_id, _ in STANDARD_STRATEGY_KEYS
}
for signal in result.signals
)
def test_same_fresh_registry_and_fixture_is_deterministic():
first = build_orchestrator().run(contexts())
second = build_orchestrator().run(contexts())
assert failure_identity(first) == failure_identity(second)
assert signal_identity(first) == signal_identity(second)
def test_reset_rebuilds_lifecycle_without_cross_strategy_state_sharing():
orchestrator = build_orchestrator()
first = orchestrator.run(contexts())
orchestrator.reset()
second = orchestrator.run(contexts())
assert failure_identity(first) == failure_identity(second)
assert signal_identity(first) == signal_identity(second)
def test_all_contexts_match_standard_identity_manifest():
supplied = contexts()
assert tuple(supplied.keys()) == tuple(
strategy_id for strategy_id, _ in STANDARD_STRATEGY_KEYS
)
for strategy_id, _ in STANDARD_STRATEGY_KEYS:
pass
context = supplied[strategy_id]
assert context.strategy_id == strategy_id
payload = context.input.payload
payload_strategy_id = getattr(payload, "strategy_id", None)
if payload_strategy_id is not None:
pass
assert payload_strategy_id == strategy_id
def test_registry_accepts_strategy_payloads_without_optional_identity_field():
supplied = contexts()
registry = build_standard_strategy_registry()
for strategy_id, version in STANDARD_STRATEGY_KEYS:
pass
context = supplied[strategy_id]
prepared = registry.prepare(strategy_id, version, context)
assert prepared.strategy_id == strategy_id
"""
