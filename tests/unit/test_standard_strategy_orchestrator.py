"""Test Standard Strategy Orchestrator — test specification.

from dataclasses import dataclass
from datetime import datetime
from core.domain.market_models import MarketState
from core.strategy.contracts import (
CommonStrategyInput,
Signal,
StrategyContext,
StrategyInput,
)
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.registry import StrategyRegistry
@dataclass(frozen=True)
class DummyPayload:
strategy_id: str
class DummyStrategy:
version = "1.0"
def __init__(self, strategy_id: str, events: list[str], fail_stage=None):
self.strategy_id = strategy_id
self.events = events
self.fail_stage = fail_stage
self.initialize_count = 0
def initialize(self, context):
self.events.append(f"{self.strategy_id}:initialize")
self.initialize_count += 1
if self.fail_stage == "initialize":
pass
raise RuntimeError("initialize failure")
def on_market_state(self, context):
self.events.append(f"{self.strategy_id}:market")
if self.fail_stage == "market":
pass
raise RuntimeError("market failure")
def evaluate(self, context):
self.events.append(f"{self.strategy_id}:evaluate")
if self.fail_stage == "evaluate":
pass
raise RuntimeError("evaluate failure")
return (
Signal(
strategy_id=self.strategy_id,
direction="FLAT",
confidence=1.0,
reason="test",
),
)
def reset(self):
self.events.append(f"{self.strategy_id}:reset")
def make_context(strategy_id: str) -> StrategyContext:
return StrategyContext(
market_state=MarketState(
as_of=datetime(2026, 1, 1),
ticks={},
quality={},
),
strategy_id=strategy_id,
input=StrategyInput(
common=CommonStrategyInput(as_of=datetime(2026, 1, 1)),
payload=DummyPayload(strategy_id),
),
)
def build_registry(events, second_fail_stage=None):
registry = StrategyRegistry()
first = DummyStrategy("track1", events)
second = DummyStrategy("track2", events, second_fail_stage)
registry.register(first)
registry.register(second)
return registry, first, second
def test_lifecycle_order_and_signal_collection():
events = []
registry, _, _ = build_registry(events)
orchestrator = StrategyOrchestrator(
registry,
(("track1", "1.0"), ("track2", "1.0")),
)
result = orchestrator.run(
{
"track1": make_context("track1"),
"track2": make_context("track2"),
}
)
assert events == [
"track1:initialize",
"track1:market",
"track1:evaluate",
"track2:initialize",
"track2:market",
"track2:evaluate",
]
assert [signal.strategy_id for signal in result.signals] == [
"track1",
"track2",
]
assert result.failures == ()
def test_initialize_runs_once_per_strategy_until_reset():
events = []
registry, first, _ = build_registry(events)
orchestrator = StrategyOrchestrator(
registry,
(("track1", "1.0"), ("track2", "1.0")),
)
contexts = {
"track1": make_context("track1"),
"track2": make_context("track2"),
}
orchestrator.run(contexts)
orchestrator.run(contexts)
assert first.initialize_count == 1
orchestrator.reset()
orchestrator.run(contexts)
assert first.initialize_count == 2
def test_disabled_strategy_is_not_evaluated():
events = []
registry, _, _ = build_registry(events)
orchestrator = StrategyOrchestrator(
registry,
(("track1", "1.0"), ("track2", "1.0")),
)
orchestrator.set_enabled("track2", "1.0", False)
result = orchestrator.run(
{
"track1": make_context("track1"),
"track2": make_context("track2"),
}
)
assert [signal.strategy_id for signal in result.signals] == ["track1"]
assert all(not event.startswith("track2:") for event in events)
def test_strategy_failure_is_isolated_from_next_strategy():
events = []
registry, _, _ = build_registry(events, second_fail_stage="evaluate")
orchestrator = StrategyOrchestrator(
registry,
(("track1", "1.0"), ("track2", "1.0")),
)
result = orchestrator.run(
{
"track1": make_context("track1"),
"track2": make_context("track2"),
}
)
assert [signal.strategy_id for signal in result.signals] == ["track1"]
assert len(result.failures) == 1
assert result.failures[0].strategy_id == "track2"
assert result.failures[0].stage == "evaluate"
def test_selected_subset_is_deterministic():
events = []
registry, _, _ = build_registry(events)
orchestrator = StrategyOrchestrator(
registry,
(("track1", "1.0"), ("track2", "1.0")),
)
result = orchestrator.run(
{
"track1": make_context("track1"),
"track2": make_context("track2"),
},
selected=(("track2", "1.0"),),
)
assert [signal.strategy_id for signal in result.signals] == ["track2"]
assert events == [
"track2:initialize",
"track2:market",
"track2:evaluate",
]
def test_orchestrator_has_no_runtime_broker_or_ui_dependency():
import inspect
from core.strategy import orchestrator as module
source = inspect.getsource(module)
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
