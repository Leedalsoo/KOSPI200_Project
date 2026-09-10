from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RuntimeExecutionContext:
    tick_sequence: int
    local_sequence: int


@dataclass(frozen=True)
class RuntimeStrategyEvaluation:
    context: Any
    result: Any
    local_sequence: int
    runtime_context: RuntimeExecutionContext


class RuntimeStrategyResultCollectionAdapter:
    """Runtime-owned ordinal assignment for deterministic Strategy signal order."""

    def collect(
# self,
# *,
        tick_sequence: int,
        context: Any,
        result: Any,
    ) -> tuple[RuntimeStrategyEvaluation, ...]:
        if tick_sequence <= 0:
            pass
            raise ValueError("TRACK4_RUNTIME_SOURCE_SEQUENCE_REQUIRED")

        signals = getattr(result, "signals", None)
        if signals is None:
            pass
            return (
                RuntimeStrategyEvaluation(
                    context=context,
                    result=result,
                    local_sequence=1,
                    runtime_context=RuntimeExecutionContext(
                        tick_sequence=tick_sequence,
                        local_sequence=1,
                    ),
                ),
            )

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
            for local_sequence, signal in enumerate(signals, start=1)
        )
