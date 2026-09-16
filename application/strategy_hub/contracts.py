from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from core.strategy.contracts import StrategyContext
from core.strategy.orchestrator import StrategyKey, StrategyRunResult


@dataclass(frozen=True)
class StrategySelection:
    keys: tuple[StrategyKey, ...]


class StrategyHubPort:
    """Stable application boundary between Runtime and individual strategies."""

    def run(self, contexts: Mapping[str, StrategyContext], selected: Iterable[StrategyKey] | None = None) -> StrategyRunResult:
        raise NotImplementedError

    def set_enabled(self, strategy_id: str, version: str, enabled: bool) -> None:
        raise NotImplementedError

    def is_enabled(self, strategy_id: str, version: str) -> bool:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError
