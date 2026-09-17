from dataclasses import dataclass

import pytest

from application.composition.runtime_strategy_result_collection_adapter import (
RuntimeStrategyResultCollectionAdapter,
)


@dataclass(frozen=True)
class Result:
    signals: tuple[object, ...]


def test_runtime_assigns_lossless_local_sequence_in_signal_order():
    first, second, third = object(), object(), object()
    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=17,
        context="ctx",
        result=Result((first, second, third)),
    )

    assert [item.result for item in evaluations] == [first, second, third]
    assert [item.local_sequence for item in evaluations] == [1, 2, 3]
    assert [item.runtime_context.tick_sequence for item in evaluations] == [17, 17, 17]


def test_empty_signal_collection_produces_no_evaluation():
    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=17,
        context="ctx",
        result=Result(()),
    )
    assert evaluations == ()


def test_invalid_tick_sequence_and_non_collection_fail_closed():
    adapter = RuntimeStrategyResultCollectionAdapter()
    with pytest.raises(ValueError, match="RUNTIME_SOURCE_SEQUENCE_REQUIRED"):
        adapter.collect(tick_sequence=0, context="ctx", result=Result(()))
    with pytest.raises(TypeError, match="RUNTIME_STRATEGY_SIGNAL_COLLECTION_REQUIRED"):
        adapter.collect(tick_sequence=1, context="ctx", result=object())
