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
    # (strategy_id, code_version, config_version, manifest_sha256)
    config_provenance: Tuple[Tuple[str, str, str, str], ...] = ()


class StrategyOrchestrator:
    """Runs the standard Strategy lifecycle without Runtime/Broker/UI dependency."""

    def __init__(
        self,
        registry: StrategyRegistry,
        strategy_keys: Iterable[StrategyKey],
    ) -> None:
        self._registry = registry
        self._strategy_keys = tuple(strategy_keys)
        definition_lookup = getattr(registry, "definition_for", None)
        self._enabled: Dict[StrategyKey, bool] = {
            key: (
                definition.enabled
                if callable(definition_lookup)
                and (definition := definition_lookup(*key)) is not None
                else True
            )
            for key in self._strategy_keys
        }
        self._entry_enabled: Dict[StrategyKey, bool] = {
            key: True for key in self._strategy_keys
        }
        self._exit_enabled: Dict[StrategyKey, bool] = {
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

    def set_entry_enabled(self, strategy_id: str, version: str, enabled: bool) -> None:
        key = (strategy_id, version)
        if key not in self._entry_enabled:
            raise KeyError(f"strategy not managed: {key}")
        self._entry_enabled[key] = enabled

    def is_entry_enabled(self, strategy_id: str, version: str) -> bool:
        return self._entry_enabled[(strategy_id, version)]

    def set_exit_enabled(self, strategy_id: str, version: str, enabled: bool) -> None:
        key = (strategy_id, version)
        if key not in self._exit_enabled:
            raise KeyError(f"strategy not managed: {key}")
        self._exit_enabled[key] = enabled

    def is_exit_enabled(self, strategy_id: str, version: str) -> bool:
        return self._exit_enabled[(strategy_id, version)]

    @staticmethod
    def _signal_lifecycle(signal: Signal) -> str:
        proposal = getattr(signal, "execution_proposal", None)
        tag = str(getattr(proposal, "tag_id", "") or "").upper()
        reason = str(getattr(signal, "reason", "") or "").upper()
        text = f"{tag} {reason}"
        if any(token in text for token in ("ENTRY", "OPEN")):
            return "ENTRY"
        if any(token in text for token in ("EXIT", "CLOSE", "UNWIND", "FLATTEN", "TAKE_PROFIT", "STOP_LOSS", "TIMEOUT")):
            return "EXIT"
        return "UNKNOWN"

    def _apply_lifecycle_controls(self, signals: Sequence[Signal]) -> tuple[Signal, ...]:
        filtered: list[Signal] = []
        for signal in signals:
            key = next((candidate for candidate in self._strategy_keys if candidate[0] == signal.strategy_id), None)
            if key is None:
                filtered.append(signal)
                continue
            lifecycle = self._signal_lifecycle(signal)
            if lifecycle == "ENTRY" and not self._entry_enabled[key]:
                continue
            if lifecycle == "EXIT" and not self._exit_enabled[key]:
                continue
            filtered.append(signal)
        return tuple(filtered)

    def on_execution_result(self, strategy_id: str, purpose: str, result: object) -> None:
        """Deliver an execution result through the registered strategy boundary."""
        key = next((item for item in self._strategy_keys if item[0] == strategy_id), None)
        if key is None:
            return
        strategy = self._registry.get(*key)
        callback = getattr(strategy, "on_execution_result", None)
        if callable(callback):
            callback(purpose, result)

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

        provenance_lookup = getattr(self._registry, "configuration_provenance", None)
        provenance = provenance_lookup(keys) if callable(provenance_lookup) else ()
        return StrategyRunResult(
            signals=self._apply_lifecycle_controls(tuple(signals)),
            failures=tuple(failures),
            config_provenance=provenance,
        )
