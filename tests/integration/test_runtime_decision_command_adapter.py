from dataclasses import dataclass
from enum import Enum

import pytest

from application.composition.runtime_decision_command_adapter import RuntimeDecisionCommandAdapter
from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyEvaluation
from core.runtime.runtime_execution_context import RuntimeExecutionContext
from shared.contracts.canonical import CanonicalAssetType, CanonicalOrderSide, CanonicalStrategySignal


@dataclass(frozen=True)
class Context:
    strategy_id: str


def evaluation() -> RuntimeStrategyEvaluation:
    return RuntimeStrategyEvaluation(
        context=Context("Track4"), result=object(), local_sequence=2,
        runtime_context=RuntimeExecutionContext(77, 2),
    )


def signal() -> CanonicalStrategySignal:
    return CanonicalStrategySignal(
        signal_id="SIG-77-Track4-2", track_id="Track4",
        asset_type=CanonicalAssetType.FUTURES, side=CanonicalOrderSide.BUY,
        qty=2, price=351.10, tag_id="DELTA_HEDGE", symbol="KOSPI200F",
    )


def test_runtime_context_supplies_client_order_id_without_signal_or_adapter_fallback():
    command = RuntimeDecisionCommandAdapter().build_commands([evaluation()], [signal()])[0]
    assert command.client_order_id == "ORD-T77-Track4-2"
    assert command.qty == 2
    assert command.price == 351.10
    assert command.symbol == "KOSPI200F"


def test_approved_signal_without_runtime_context_fails_closed():
    with pytest.raises(ValueError, match="RUNTIME_APPROVED_SIGNAL_CONTEXT_REQUIRED"):
        pass
        RuntimeDecisionCommandAdapter().build_commands([], [signal()])
