from __future__ import annotations

from typing import Iterable, Mapping

from core.strategy.contracts import StrategyContext
from core.strategy.orchestrator import StrategyKey, StrategyOrchestrator, StrategyRunResult
from core.strategy.registry import StrategyRegistry
from application.strategy_hub.contracts import StrategyHubPort


class StrategyHub(StrategyHubPort):
    """Own strategy selection/lifecycle while hiding registry implementation."""

    def __init__(self, registry: StrategyRegistry, strategy_keys: Iterable[StrategyKey]) -> None:
        self._orchestrator = StrategyOrchestrator(registry, strategy_keys)
        self._keys = tuple(strategy_keys)

    @property
    def strategy_keys(self) -> tuple[StrategyKey, ...]:
        return self._keys

    def run(self, contexts: Mapping[str, StrategyContext], selected: Iterable[StrategyKey] | None = None) -> StrategyRunResult:
        return self._orchestrator.run(contexts, selected=selected)

    def set_enabled(self, strategy_id: str, version: str, enabled: bool) -> None:
        self._orchestrator.set_enabled(strategy_id, version, enabled)

    def is_enabled(self, strategy_id: str, version: str) -> bool:
        return self._orchestrator.is_enabled(strategy_id, version)

    def reset(self) -> None:
        self._orchestrator.reset()
