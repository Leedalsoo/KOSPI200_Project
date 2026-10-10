"""Strategy-specific execution-plan resolver registry with fail-closed requirements."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from core.strategy.definition import StrategyDefinition

Resolver = Callable[[Any, Any], Any]


class ExecutionMultiLegResolverRegistry:
    """Resolve plans by strategy contract, never by a growing central if-chain."""

    def __init__(
        self,
        definitions: Mapping[str, StrategyDefinition] | None = None,
    ) -> None:
        self._resolvers: dict[str, Resolver] = {}
        self._definitions = dict(definitions or {})

    def register(self, strategy_id: str, resolver: Resolver) -> None:
        key = str(strategy_id).strip()
        if not key:
            raise ValueError("EXECUTION_RESOLVER_STRATEGY_ID_REQUIRED")
        if key in self._resolvers:
            raise ValueError(f"EXECUTION_RESOLVER_ALREADY_REGISTERED:{key}")
        if not callable(resolver):
            raise TypeError("EXECUTION_RESOLVER_CALLABLE_REQUIRED")
        self._resolvers[key] = resolver

    def resolve(self, strategy_id: str, evaluation: Any, canonical: Any) -> Any:
        key = str(strategy_id).strip()
        definition = self._definitions.get(key)
        signal = getattr(evaluation, "result", None)
        required = definition.requires_multi_leg(signal) if definition is not None else False
        resolver = self._resolvers.get(key)
        if resolver is None:
            if required:
                raise ValueError(f"MULTI_LEG_RESOLVER_REQUIRED:{key}")
            return None
        plan = resolver(evaluation, canonical)
        if plan is None:
            if required:
                raise ValueError(f"MULTI_LEG_EXECUTION_PLAN_REQUIRED:{key}")
            return None
        if str(getattr(plan, "strategy_id", "")) != key:
            raise ValueError(f"MULTI_LEG_STRATEGY_ID_MISMATCH:{key}")
        return plan

    def registered_strategy_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._resolvers))
