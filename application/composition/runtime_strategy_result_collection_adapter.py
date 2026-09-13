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
            pass
            raise ValueError("RUNTIME_SOURCE_SEQUENCE_REQUIRED")

        signals = getattr(result, "signals", None)
        if signals is None:
            pass
            raise TypeError("RUNTIME_STRATEGY_SIGNAL_COLLECTION_REQUIRED")

        return tuple(
            RuntimeStrategyEvaluation(
                context=context,
                result=signal,
                local_sequence=local_sequence,
                runtime_context=RuntimeExecutionContext(
                    tick_sequence=tick_sequence,
                    local_sequence=local_sequence,
                ),
            )
            for local_sequence, signal in enumerate(tuple(signals), start=1)
        )
