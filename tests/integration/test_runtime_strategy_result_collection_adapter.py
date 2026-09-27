from dataclasses import dataclass

import pytest

from application.composition.runtime_strategy_result_collection_adapter import (
RuntimeStrategyResultCollectionAdapter,
)


@dataclass(frozen=True)
class Result:
    signals: tuple[object, ...]


@dataclass(frozen=True)
class Signal:
    strategy_id: str


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


def test_runtime_maps_each_signal_to_its_strategy_context():
    first = Signal("track1")
    second = Signal("track5")
    contexts = {"track1": "ctx1", "track5": "ctx5"}
    evaluations = RuntimeStrategyResultCollectionAdapter().collect(
        tick_sequence=17,
        context=contexts,
        result=Result((first, second)),
    )
    assert [item.context for item in evaluations] == ["ctx1", "ctx5"]


def test_missing_signal_strategy_context_fails_closed():
    with pytest.raises(ValueError, match="RUNTIME_SIGNAL_CONTEXT_REQUIRED"):
        RuntimeStrategyResultCollectionAdapter().collect(
            tick_sequence=17,
            context={"track1": "ctx1"},
            result=Result((Signal("track5"),)),
        )


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
