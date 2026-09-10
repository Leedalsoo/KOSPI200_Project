"""Runtime Decision Command Adapter — _children variant."""
from __future__ import annotations

from typing import Iterable

from application.composition.runtime_strategy_result_collection_adapter import (
    RuntimeStrategyEvaluation,
)
from core.runtime.reference_execution_pipeline import (
    DecisionCommandContext,
    approved_signal_to_command,
)
from shared.contracts.canonical import CanonicalOrderCommand, CanonicalStrategySignal


class RuntimeDecisionCommandAdapter:
    """Transport approved signals to CanonicalOrderCommand using Runtime-owned IDs."""

    def build_commands(
        self,
        evaluations: Iterable[RuntimeStrategyEvaluation],
        approved_signals: Iterable[CanonicalStrategySignal],
    ) -> tuple[CanonicalOrderCommand, ...]:
        contexts: dict[str, RuntimeStrategyEvaluation] = {}
        for evaluation in evaluations:
            track_id = str(getattr(evaluation.context, "strategy_id", "") or "").strip()
            if not track_id:
                raise ValueError("RUNTIME_TRACK_ID_REQUIRED")
            signal_id = evaluation.runtime_context.signal_id(track_id)
            if signal_id in contexts:
                raise ValueError("RUNTIME_DUPLICATE_SIGNAL_ID")
            contexts[signal_id] = evaluation

        commands: list[CanonicalOrderCommand] = []
        for signal in approved_signals:
            evaluation = contexts.get(signal.signal_id)
            if evaluation is None:
                raise ValueError("RUNTIME_APPROVED_SIGNAL_CONTEXT_REQUIRED")
            track_id = str(getattr(evaluation.context, "strategy_id", "") or "").strip()
            if track_id != signal.track_id:
                raise ValueError("RUNTIME_TRACK_ID_CONTEXT_MISMATCH")

            commands.append(
                approved_signal_to_command(
                    signal,
                    context=DecisionCommandContext(
                        client_order_id=evaluation.runtime_context.client_order_id(track_id),
                    ),
                )
            )

        return tuple(commands)
