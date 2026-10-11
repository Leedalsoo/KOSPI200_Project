from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pytest

from core.strategy.contracts import (
    NonExecutionEvent,
    Signal,
    SignalKind,
    StrategyContext,
    StrategyFeatureRequirement,
)
from core.strategy.evaluation_seam import StrategyEvaluationSeam
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.registry import StrategyRegistry


@dataclass
class _SpyPlugin:
    strategy_id: str = "seam_test"
    version: str = "1.0"
    calls: int = 0
    initialize_calls: int = 0
    market_state_calls: int = 0
    failure: Exception | None = None
    emitted: tuple[Signal, ...] = ()

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]:
        return ()

    def initialize(self, context: StrategyContext) -> None:
        self.initialize_calls += 1

    def on_market_state(self, context: StrategyContext) -> None:
        self.market_state_calls += 1

    def evaluate(self, context: StrategyContext) -> Sequence[Signal]:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.emitted

    def reset(self) -> None:
        pass


def _seam(plugin: _SpyPlugin) -> StrategyEvaluationSeam:
    registry = StrategyRegistry()
    registry.register(plugin)
    return StrategyEvaluationSeam(StrategyOrchestrator(registry, ((plugin.strategy_id, plugin.version),)))


def test_evaluate_once_calls_plugin_exactly_once_and_preserves_non_execution() -> None:
    event = NonExecutionEvent(event_type="UPDATE_TRAILING", reason="watermark updated")
    signal = Signal(
        strategy_id="seam_test",
        direction="NONE",
        confidence=1.0,
        reason="UPDATE_TRAILING",
        kind=SignalKind.NON_EXECUTION,
        non_execution_event=event,
    )
    plugin = _SpyPlugin(emitted=(signal,))
    seam = _seam(plugin)

    result = seam.evaluate_once("seam_test", "1.0", StrategyContext(strategy_id="seam_test"))

    assert plugin.calls == 1
    assert result.signals == (signal,)
    assert result.signals[0].kind is SignalKind.NON_EXECUTION
    assert result.signals[0].non_execution_event is event
    assert result.signals[0].execution_proposal is None
    assert result.failures == ()


def test_context_identity_mismatch_fails_before_plugin_invocation() -> None:
    plugin = _SpyPlugin()
    seam = _seam(plugin)

    with pytest.raises(ValueError, match="STRATEGY_EVALUATION_CONTEXT_IDENTITY_MISMATCH"):
        seam.evaluate_once("seam_test", "1.0", StrategyContext(strategy_id="other"))

    assert plugin.calls == 0
    assert plugin.initialize_calls == 0


def test_missing_context_fails_before_plugin_invocation() -> None:
    plugin = _SpyPlugin()
    seam = _seam(plugin)

    with pytest.raises(ValueError, match="STRATEGY_EVALUATION_CONTEXT_REQUIRED"):
        seam.evaluate_once("seam_test", "1.0", None)  # type: ignore[arg-type]

    assert plugin.calls == 0
    assert plugin.initialize_calls == 0


def test_plugin_exception_remains_structured_failure_not_no_signal_success() -> None:
    plugin = _SpyPlugin(failure=RuntimeError("evaluation exploded"))
    seam = _seam(plugin)

    result = seam.evaluate_once("seam_test", "1.0", StrategyContext(strategy_id="seam_test"))

    assert plugin.calls == 1
    assert result.signals == ()
    assert len(result.failures) == 1
    assert result.failures[0].stage == "evaluate"
    assert result.failures[0].error_type == "RuntimeError"
    assert result.failures[0].message == "evaluation exploded"


def test_strategy_identity_arguments_are_required() -> None:
    plugin = _SpyPlugin()
    seam = _seam(plugin)

    with pytest.raises(ValueError, match="STRATEGY_EVALUATION_IDENTITY_REQUIRED"):
        seam.evaluate_once("", "1.0", StrategyContext(strategy_id="seam_test"))
    with pytest.raises(ValueError, match="STRATEGY_EVALUATION_IDENTITY_REQUIRED"):
        seam.evaluate_once("seam_test", "", StrategyContext(strategy_id="seam_test"))
    assert plugin.calls == 0
