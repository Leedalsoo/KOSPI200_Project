from core.position.position_aggregate import PositionAggregate
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate


def test_buy_fill_preserves_authoritative_side_and_qty():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=3, price=1.25)

    snapshot = position.snapshot()
    assert snapshot["OPTION_X"] == PositionAggregate(side="BUY", qty=3, avg_price=1.25)


def test_same_side_fill_accumulates_quantity():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=2, price=1.0)
    position.apply_fill(side="BUY", quantity=2, price=2.0)

    aggregate = position.snapshot()["OPTION_X"]
    assert aggregate.side == "BUY"
    assert aggregate.qty == 4
    assert aggregate.avg_price == 1.5


def test_opposite_fill_reduces_existing_position_without_side_inference():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=5, price=1.0)
    position.apply_fill(side="SELL", quantity=2, price=1.2)

    aggregate = position.snapshot()["OPTION_X"]
    assert aggregate.side == "BUY"
    assert aggregate.qty == 3


def test_opposite_fill_beyond_existing_quantity_creates_residual_new_side():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=2, price=1.0)
    position.apply_fill(side="SELL", quantity=5, price=1.2)

    aggregate = position.snapshot()["OPTION_X"]
    assert aggregate.side == "SELL"
    assert aggregate.qty == 3
    assert aggregate.avg_price == 1.2


def test_flat_position_has_no_authoritative_position_entry():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=2, price=1.0)
    position.apply_fill(side="SELL", quantity=2, price=1.1)

    assert position.snapshot() == {}


def test_invalid_side_fails_closed():
    position = VirtualPositionAggregate("OPTION_X")
    try:
        pass
        position.apply_fill(side="UNKNOWN", quantity=1, price=1.0)
    except ValueError as exc:
        pass
        assert str(exc) == "POSITION_AGGREGATE_SIDE_INVALID"
    else:
        pass
        raise AssertionError("invalid side must fail closed")
