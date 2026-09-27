from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.runtime.runtime_execution_context import RuntimeExecutionContext


@dataclass(frozen=True)
class RuntimeStrategyEvaluation:
    """One Strategy signal with Runtime-owned deterministic local ordinal."""

    context: Any
    result: Any
    local_sequence: int
    runtime_context: RuntimeExecutionContext


class RuntimeStrategyResultCollectionAdapter:
    """Assign local_sequence from StrategyRunResult.signals order at Runtime boundary."""

    def collect(
        self,
        *,
        tick_sequence: int,
        context: Any,
        result: Any,
    ) -> tuple[RuntimeStrategyEvaluation, ...]:
        if tick_sequence <= 0:
            raise ValueError("RUNTIME_SOURCE_SEQUENCE_REQUIRED")

        signals = getattr(result, "signals", None)
        if signals is None:
            raise TypeError("RUNTIME_STRATEGY_SIGNAL_COLLECTION_REQUIRED")

        evaluations: list[RuntimeStrategyEvaluation] = []
        for local_sequence, signal in enumerate(tuple(signals), start=1):
            signal_strategy_id = str(getattr(signal, "strategy_id", "") or "").strip()
            signal_context = context
            if isinstance(context, dict):
                signal_context = context.get(signal_strategy_id)
                if signal_context is None:
                    raise ValueError("RUNTIME_SIGNAL_CONTEXT_REQUIRED")
            evaluations.append(
                RuntimeStrategyEvaluation(
                    context=signal_context,
                    result=signal,
                    local_sequence=local_sequence,
                    runtime_context=RuntimeExecutionContext(
                        tick_sequence=tick_sequence,
                        local_sequence=local_sequence,
                    ),
                )
            )
        return tuple(evaluations)
