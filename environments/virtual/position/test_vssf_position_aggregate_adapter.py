from copy import deepcopy

import pytest

from core.position.position_aggregate import PositionAggregate
from environments.virtual.position.vssf_position_aggregate_adapter import (
VSSFPositionAggregateAdapter,
)


class StubVSSFPositionSource:
    def __init__(self, positions):
        self.positions = positions


def test_buy_sell_qty_and_avg_price_are_preserved():
    source = StubVSSFPositionSource({
        "K200-C-350": {"qty": 3, "avg_price": 101.5, "side": "BUY"},
        "K200-P-350": {"qty": 5, "avg_price": 98.25, "side": "SELL"},
    })

    snapshot = VSSFPositionAggregateAdapter(source).snapshot()

    assert snapshot["K200-C-350"] == PositionAggregate("BUY", 3, 101.5)
    assert snapshot["K200-P-350"] == PositionAggregate("SELL", 5, 98.25)


def test_missing_side_fails_closed():
    source = StubVSSFPositionSource({"K200-C-350": {"qty": 3, "avg_price": 101.5}})

    with pytest.raises(TypeError, match="VSSF_POSITION_SIDE_REQUIRED"):
        pass
        VSSFPositionAggregateAdapter(source).snapshot()


def test_invalid_qty_fails_closed():
    source = StubVSSFPositionSource({"K200-C-350": {"qty": 0, "avg_price": 101.5, "side": "BUY"}})

    with pytest.raises(TypeError, match="VSSF_POSITION_QTY_REQUIRED"):
        pass
        VSSFPositionAggregateAdapter(source).snapshot()


def test_malformed_mapping_fails_closed():
    source = StubVSSFPositionSource({"K200-C-350": ["BUY", 3, 101.5]})

    with pytest.raises(TypeError, match="VSSF_POSITION_STATE_REQUIRED"):
        pass
        VSSFPositionAggregateAdapter(source).snapshot()


def test_non_mapping_source_fails_closed():
    source = StubVSSFPositionSource([])

    with pytest.raises(TypeError, match="VSSF_POSITION_SOURCE_REQUIRED"):
        pass
        VSSFPositionAggregateAdapter(source).snapshot()


def test_source_is_not_mutated():
    positions = {
        "K200-C-350": {"qty": 3, "avg_price": 101.5, "side": "BUY"},
    }
    before = deepcopy(positions)
    source = StubVSSFPositionSource(positions)

    VSSFPositionAggregateAdapter(source).snapshot()

    assert positions == before
