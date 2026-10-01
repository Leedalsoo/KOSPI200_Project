"""Strategy-specific execution/multi-leg resolver registry."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

Resolver = Callable[[Any, Any], Any]


class ExecutionMultiLegResolverRegistry:
    """Resolve strategy execution plans without a central strategy if-chain."""

    def __init__(self) -> None:
        self._resolvers: dict[str, Resolver] = {}

    def register(self, strategy_id: str, resolver: Resolver) -> None:
        key = str(strategy_id).strip()
        if not key:
            raise ValueError("EXECUTION_RESOLVER_STRATEGY_ID_REQUIRED")
        if key in self._resolvers:
            raise ValueError(f"EXECUTION_RESOLVER_ALREADY_REGISTERED:{key}")
        self._resolvers[key] = resolver

    def resolve(self, strategy_id: str, evaluation: Any, canonical: Any) -> Any:
        resolver = self._resolvers.get(str(strategy_id))
        if resolver is None:
            return None
        return resolver(evaluation, canonical)

    def registered_strategy_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._resolvers))
