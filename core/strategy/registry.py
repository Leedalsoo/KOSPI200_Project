from typing import Dict, Tuple

from core.strategy.contracts import Strategy, StrategyContext


class StrategyRegistry:
    """Registry keyed by immutable strategy identity (id, version)."""

    def __init__(self) -> None:
        self._strategies: Dict[Tuple[str, str], Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        key = (strategy.strategy_id, strategy.version)
        if key in self._strategies:
            raise ValueError(f"duplicate strategy: {key}")
        self._strategies[key] = strategy

    def get(self, strategy_id: str, version: str) -> Strategy:
        try:
            return self._strategies[(strategy_id, version)]
        except KeyError as exc:
            raise KeyError(f"strategy not registered: {(strategy_id, version)}") from exc

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
        return self.get(strategy_id, version)
