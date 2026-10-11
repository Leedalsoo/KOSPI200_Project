from __future__ import annotations

from core.strategy.contracts import StrategyContext
from core.strategy.orchestrator import StrategyOrchestrator, StrategyRunResult


class StrategyEvaluationSeam:
    """Opt-in single-strategy evaluation boundary for contract tests.

    This adapter deliberately delegates lifecycle, failure capture, controls and
    provenance to the existing StrategyOrchestrator. It has no market-data,
    analytics, broker, execution or UI responsibilities and is not wired into
    the production composition root.
    """

    def __init__(self, orchestrator: StrategyOrchestrator) -> None:
        self._orchestrator = orchestrator

    def evaluate_once(
        self,
        strategy_id: str,
        version: str,
        context: StrategyContext | None,
    ) -> StrategyRunResult:
        if not strategy_id or not version:
            raise ValueError("STRATEGY_EVALUATION_IDENTITY_REQUIRED")
        if context is None:
            raise ValueError("STRATEGY_EVALUATION_CONTEXT_REQUIRED")
        if context.strategy_id != strategy_id:
            raise ValueError(
                "STRATEGY_EVALUATION_CONTEXT_IDENTITY_MISMATCH:"
                f"requested={strategy_id!r}, context={context.strategy_id!r}"
            )
        return self._orchestrator.run(
            {strategy_id: context},
            selected=((strategy_id, version),),
        )
