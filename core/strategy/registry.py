from __future__ import annotations

from typing import Dict, Iterable, Tuple

from core.strategy.contracts import Strategy, StrategyContext
from core.strategy.definition import StrategyDefinition


class StrategyRegistry:
    """Registry keyed by immutable strategy identity (id, code version)."""

    def __init__(self) -> None:
        self._strategies: Dict[Tuple[str, str], Strategy] = {}
        self._definitions: Dict[Tuple[str, str], StrategyDefinition] = {}

    def register(
        self,
        strategy: Strategy,
        definition: StrategyDefinition | None = None,
    ) -> None:
        key = (strategy.strategy_id, strategy.version)
        if key in self._strategies:
            raise ValueError(f"duplicate strategy: {key}")
        if definition is not None and (
            definition.strategy_id != strategy.strategy_id
            or definition.code_version != strategy.version
        ):
            raise ValueError(f"strategy definition mismatch: {key}")
        self._strategies[key] = strategy
        if definition is not None:
            self._definitions[key] = definition

    def get(self, strategy_id: str, version: str) -> Strategy:
        try:
            return self._strategies[(strategy_id, version)]
        except KeyError as exc:
            raise KeyError(f"strategy not registered: {(strategy_id, version)}") from exc

    def definition_for(
        self, strategy_id: str, version: str
    ) -> StrategyDefinition | None:
        return self._definitions.get((strategy_id, version))

    def definitions_by_strategy_id(
        self,
        keys: Iterable[Tuple[str, str]] | None = None,
    ) -> dict[str, StrategyDefinition]:
        selected = tuple(keys) if keys is not None else tuple(self._definitions)
        definitions: dict[str, StrategyDefinition] = {}
        for strategy_id, version in selected:
            definition = self._definitions.get((strategy_id, version))
            if definition is None:
                continue
            previous = definitions.get(strategy_id)
            if previous is not None and previous.code_version != definition.code_version:
                raise ValueError(f"STRATEGY_VERSION_AMBIGUOUS_FOR_RUNTIME:{strategy_id}")
            definitions[strategy_id] = definition
        return definitions

    def configuration_provenance(
        self, keys: Iterable[Tuple[str, str]] | None = None
    ) -> tuple[tuple[str, str, str, str], ...]:
        selected = tuple(keys) if keys is not None else tuple(self._definitions)
        rows = []
        for strategy_id, version in selected:
            definition = self._definitions.get((strategy_id, version))
            if definition is not None:
                rows.append((
                    definition.strategy_id,
                    definition.code_version,
                    definition.config_version,
                    definition.config_hash,
                ))
        return tuple(rows)

    def validate_context(self, context: StrategyContext) -> None:
        if context.input is None:
            return
        payload_strategy_id = getattr(context.input.payload, "strategy_id", None)
        if payload_strategy_id is not None and payload_strategy_id != context.strategy_id:
            raise ValueError(
                "strategy input payload mismatch: "
                f"context={context.strategy_id!r}, payload={payload_strategy_id!r}"
            )

    def prepare(self, strategy_id: str, version: str, context: StrategyContext) -> Strategy:
        if context.strategy_id != strategy_id:
            raise ValueError(
                "strategy context mismatch: "
                f"context={context.strategy_id!r}, requested={strategy_id!r}"
            )
        self.validate_context(context)
        definition = self._definitions.get((strategy_id, version))
        data_status = getattr(context.input, "data_status", None) if context.input is not None else None
        if definition is not None and data_status is not None:
            for source in definition.required_sources:
                status = str(data_status.get(source, "")).strip().upper()
                if status not in {"AVAILABLE", "PASS", "OK"}:
                    raise ValueError(
                        f"STRATEGY_REQUIRED_SOURCE_UNAVAILABLE:{strategy_id}:{source}:"
                        f"{status or 'STATUS_UNDECLARED'}"
                    )
        return self.get(strategy_id, version)
