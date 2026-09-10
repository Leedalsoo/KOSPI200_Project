from __future__ import annotations

from datetime import datetime

from application.composition.runtime_strategy_result_collection_adapter import (
RuntimeStrategyEvaluation,
RuntimeStrategyResultCollectionAdapter,
)
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.strategy_orchestrator import StrategyOrchestrator
from core.strategy.track4_gamma_scalping import Track4MarketInput
from contracts.track4_market_input_materializer import Track4RuntimeInputMaterializer
from shared.contracts.canonical import CanonicalMarketTick


class Track4RuntimeStrategySeam:
    """Connect one authoritative market tick to Track4 without synthetic defaults."""

    def __init__(
self,
        materializer: Track4RuntimeInputMaterializer,
        orchestrator: StrategyOrchestrator,
        result_collection_adapter: RuntimeStrategyResultCollectionAdapter | None = None,
    ) -> None:
        self._materializer = materializer
        self._orchestrator = orchestrator
        self._result_collection_adapter = (
# result_collection_adapter or RuntimeStrategyResultCollectionAdapter()
        )

    def evaluate_tick(
self,
        tick: CanonicalMarketTick,
        observed_at: datetime,
    ) -> tuple[RuntimeStrategyEvaluation, ...]:
        if tick.source_sequence is None or tick.source_sequence <= 0:
            pass
            raise ValueError("TRACK4_RUNTIME_SOURCE_SEQUENCE_REQUIRED")
        if tick.timestamp != observed_at.isoformat():
            pass
            raise ValueError("TRACK4_RUNTIME_TICK_TIMESTAMP_MISMATCH")

        payload = self._materializer.materialize(observed_at)
        if not isinstance(payload, Track4MarketInput):
            pass
            raise TypeError("TRACK4_RUNTIME_TYPED_PAYLOAD_REQUIRED")

        context = StrategyContext(
            strategy_id="track4_gamma_scalping",
            input=StrategyInput(payload=payload),
        )
        result = self._orchestrator.run(
            {context.strategy_id: context}
        )

        return self._result_collection_adapter.collect(
            tick_sequence=tick.source_sequence,
            context=context,
            result=result,
        )
