"""Test Standard Strategy Registry — 테스트 사양 문서.

from core.strategy.standard_registry import (
STANDARD_STRATEGY_IDS,
STANDARD_STRATEGY_KEYS,
build_standard_strategy_registry,
)
def test_standard_registry_contains_exactly_nine_baseline_strategies():
registry = build_standard_strategy_registry()
assert len(STANDARD_STRATEGY_KEYS) == 9
assert len(STANDARD_STRATEGY_IDS) == 9
assert len(set(STANDARD_STRATEGY_KEYS)) == 9
assert len(set(STANDARD_STRATEGY_IDS)) == 9
for strategy_id, version in STANDARD_STRATEGY_KEYS:
pass
strategy = registry.get(strategy_id, version)
assert strategy.strategy_id == strategy_id
assert strategy.version == version
def test_standard_registry_ids_are_projection_of_identity_manifest():
assert STANDARD_STRATEGY_IDS == tuple(
strategy_id for strategy_id, _ in STANDARD_STRATEGY_KEYS
)
def test_standard_registry_rebuild_is_isolated():
first = build_standard_strategy_registry()
second = build_standard_strategy_registry()
assert first is not second
for strategy_id, version in STANDARD_STRATEGY_KEYS:
pass
assert first.get(strategy_id, version) is not second.get(
strategy_id, version
)
def test_registry_manifest_has_no_runtime_or_execution_dependency():
import inspect
from core.strategy import standard_registry
source = inspect.getsource(standard_registry)
for forbidden in (
"option_program.runtime",
"Broker",
"OrderRequest",
"ExecutionReport",
"VMS",
"VSSF",
"UI",
):
assert forbidden not in source
"""
