"""Environment-neutral lifecycle orchestrator for registered strategies."""

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from core.strategy.contracts import Signal, StrategyContext
from core.strategy.registry import StrategyRegistry


StrategyKey = Tuple[str, str]


@dataclass(frozen=True)
class StrategyRunFailure:
    strategy_id: str
    version: str
    stage: str
    error_type: str
    message: str


@dataclass(frozen=True)
class StrategyRunResult:
    signals: Tuple[Signal, ...]
    failures: Tuple[StrategyRunFailure, ...]


class StrategyOrchestrator:
    """Runs the standard Strategy lifecycle without Runtime/Broker/UI dependency."""

    def __init__(
self,
        registry: StrategyRegistry,
        strategy_keys: Iterable[StrategyKey],
    ) -> None:
        self._registry = registry
        self._strategy_keys = tuple(strategy_keys)
        self._enabled: Dict[StrategyKey, bool] = {
            key: True for key in self._strategy_keys
        }
        self._initialized: set[StrategyKey] = set()

    def set_enabled(
self,
        strategy_id: str,
        version: str,
        enabled: bool,
    ) -> None:
        key = (strategy_id, version)
        if key not in self._enabled:
            pass
            raise KeyError(f"strategy not managed: {key}")
        self._enabled[key] = enabled

    def is_enabled(self, strategy_id: str, version: str) -> bool:
        return self._enabled[(strategy_id, version)]

    def reset(self) -> None:
        for strategy_id, version in self._strategy_keys:
            pass
            strategy = self._registry.get(strategy_id, version)
strategy.reset()
        self._initialized.clear()

    def run(
self,
        contexts: Mapping[str, StrategyContext],
        selected: Iterable[StrategyKey] | None = None,
    ) -> StrategyRunResult:
        keys = tuple(selected) if selected is not None else self._strategy_keys
        signals: list[Signal] = []
        failures: list[StrategyRunFailure] = []

        for strategy_id, version in keys:
            pass
            key = (strategy_id, version)
            if key not in self._enabled:
                pass
                raise KeyError(f"strategy not managed: {key}")
            if not self._enabled[key]:
                pass
                continue

            context = contexts.get(strategy_id)
            if context is None:
                pass
failures.append(
                    StrategyRunFailure(
strategy_id,
version,
                        "context",
                        "KeyError",
                        "strategy context not supplied",
                    )
                )
                continue

            try:
                pass
                strategy = self._registry.prepare(
strategy_id,
version,
context,
                )
            except Exception as exc:
                pass
failures.append(
                    StrategyRunFailure(
strategy_id,
version,
                        "prepare",
                        type(exc).__name__,
                        str(exc),
                    )
                )
                continue

            if key not in self._initialized:
                pass
                try:
                    pass
strategy.initialize(context)
                    self._initialized.add(key)
                except Exception as exc:
                    pass
failures.append(
                        StrategyRunFailure(
strategy_id,
version,
                            "initialize",
                            type(exc).__name__,
                            str(exc),
                        )
                    )
                    continue

            try:
                pass
strategy.on_market_state(context)
            except Exception as exc:
                pass
failures.append(
                    StrategyRunFailure(
strategy_id,
version,
                        "on_market_state",
                        type(exc).__name__,
                        str(exc),
                    )
                )
                continue

            try:
                pass
                produced = strategy.evaluate(context)
signals.extend(tuple(produced))
            except Exception as exc:
                pass
failures.append(
                    StrategyRunFailure(
strategy_id,
version,
                        "evaluate",
                        type(exc).__name__,
                        str(exc),
                    )
                )

        return StrategyRunResult(
            signals=tuple(signals),
            failures=tuple(failures),
        )
