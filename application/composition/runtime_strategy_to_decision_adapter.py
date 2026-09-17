"""Runtime Strategy to Decision Adapter."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Iterable
from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyEvaluation
from contracts.types import OptionInstrumentIdentity
from core.decision.decision_arbiter import ArbitrationResult, DecisionArbiter
from core.strategy.canonical_signal_adapter import RuntimeSignalContext, signal_to_canonical
from shared.contracts.canonical import CanonicalStrategySignal

InstrumentIdentityProvider = Callable[[RuntimeStrategyEvaluation, Any], OptionInstrumentIdentity | None]

@dataclass(frozen=True)
class RuntimeDecisionResult:
    canonical_signals: tuple[CanonicalStrategySignal, ...]
    arbitration: ArbitrationResult

class RuntimeStrategyToDecisionAdapter:
    def __init__(self, arbiter: DecisionArbiter) -> None:
        self._arbiter = arbiter

    def arbitrate(self, evaluations: Iterable[RuntimeStrategyEvaluation], *, price: float, timestamp: str, account: Any, instrument_identity_provider: InstrumentIdentityProvider | None = None, market_tick: Any | None = None) -> RuntimeDecisionResult:
        canonical_signals: list[CanonicalStrategySignal] = []
        seen_signal_ids: set[str] = set()
        for evaluation in evaluations:
            signal = evaluation.result
            if getattr(signal, "execution_proposal", None) is None:
                continue
            track_id = str(getattr(evaluation.context, "strategy_id", "") or "").strip()
            if not track_id:
                raise ValueError("RUNTIME_TRACK_ID_REQUIRED")
            signal_id = evaluation.runtime_context.signal_id(track_id)
            if signal_id in seen_signal_ids:
                raise ValueError("RUNTIME_DUPLICATE_SIGNAL_ID")
            seen_signal_ids.add(signal_id)
            identity = instrument_identity_provider(evaluation, market_tick) if instrument_identity_provider is not None else None
            canonical_signals.append(signal_to_canonical(signal, RuntimeSignalContext(signal_id=signal_id, track_id=track_id, price=price, timestamp=timestamp), instrument_identity=identity))
        arbitration = self._arbiter.arbitrate(canonical_signals, account)
        return RuntimeDecisionResult(canonical_signals=tuple(canonical_signals), arbitration=arbitration)

