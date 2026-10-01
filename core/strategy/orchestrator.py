"""Environment-neutral lifecycle orchestrator for registered strategies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from core.strategy.contracts import Signal, StrategyContext, UnavailableStrategyPayload
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
            raise KeyError(f"strategy not managed: {key}")
        self._enabled[key] = enabled

    def is_enabled(self, strategy_id: str, version: str) -> bool:
        return self._enabled[(strategy_id, version)]

    def reset(self) -> None:
        for strategy_id, version in self._strategy_keys:
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
            key = (strategy_id, version)
            if key not in self._enabled:
                raise KeyError(f"strategy not managed: {key}")
            if not self._enabled[key]:
                continue

            context = contexts.get(strategy_id)
            if context is None:
                failures.append(
                    StrategyRunFailure(
                        strategy_id, version, "context",
                        "KeyError", "strategy context not supplied",
                    )
                )
                continue

            payload = getattr(getattr(context, "input", None), "payload", None)
            if isinstance(payload, UnavailableStrategyPayload):
                failures.append(
                    StrategyRunFailure(
                        strategy_id, version, "input", "UnavailableData",
                        payload.reason,
                    )
                )
                continue

            try:
                strategy = self._registry.prepare(strategy_id, version, context)
            except Exception as exc:
                failures.append(
                    StrategyRunFailure(
                        strategy_id, version, "prepare",
                        type(exc).__name__, str(exc),
                    )
                )
                continue

            if key not in self._initialized:
                try:
                    strategy.initialize(context)
                    self._initialized.add(key)
                except Exception as exc:
                    failures.append(
                        StrategyRunFailure(
                            strategy_id, version, "initialize",
                            type(exc).__name__, str(exc),
                        )
                    )
                    continue

            try:
                strategy.on_market_state(context)
            except Exception as exc:
                failures.append(
                    StrategyRunFailure(
                        strategy_id, version, "on_market_state",
                        type(exc).__name__, str(exc),
                    )
                )
                continue

            try:
                produced = strategy.evaluate(context)
                signals.extend(tuple(produced))
            except Exception as exc:
                failures.append(
                    StrategyRunFailure(
                        strategy_id, version, "evaluate",
                        type(exc).__name__, str(exc),
                    )
                )

        return StrategyRunResult(
            signals=tuple(signals),
            failures=tuple(failures),
        )
