from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.runtime.runtime_execution_context import RuntimeExecutionContext


@dataclass(frozen=True)
class RuntimeStrategyEvaluation:
    """One Strategy signal with deterministic ordinal and pinned config provenance."""

    context: Any
    result: Any
    local_sequence: int
    runtime_context: RuntimeExecutionContext
    strategy_code_version: str | None = None
    strategy_config_version: str | None = None
    strategy_config_hash: str | None = None


class RuntimeStrategyResultCollectionAdapter:
    """Assign local_sequence and attach the configuration snapshot to each signal."""

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

        provenance_by_id: dict[str, tuple[str, str, str]] = {}
        for row in getattr(result, "config_provenance", ()) or ():
            if len(row) != 4:
                raise ValueError("STRATEGY_CONFIG_PROVENANCE_ROW_INVALID")
            strategy_id, code_version, config_version, config_hash = row
            provenance_by_id[str(strategy_id)] = (
                str(code_version), str(config_version), str(config_hash)
            )

        evaluations: list[RuntimeStrategyEvaluation] = []
        for local_sequence, signal in enumerate(tuple(signals), start=1):
            signal_strategy_id = str(getattr(signal, "strategy_id", "") or "").strip()
            signal_context = context
            if isinstance(context, dict):
                signal_context = context.get(signal_strategy_id)
                if signal_context is None:
                    raise ValueError("RUNTIME_SIGNAL_CONTEXT_REQUIRED")
            code_version, config_version, config_hash = provenance_by_id.get(
                signal_strategy_id, (None, None, None)
            )
            evaluations.append(
                RuntimeStrategyEvaluation(
                    context=signal_context,
                    result=signal,
                    local_sequence=local_sequence,
                    runtime_context=RuntimeExecutionContext(
                        tick_sequence=tick_sequence,
                        local_sequence=local_sequence,
                    ),
                    strategy_code_version=code_version,
                    strategy_config_version=config_version,
                    strategy_config_hash=config_hash,
                )
            )
        return tuple(evaluations)
