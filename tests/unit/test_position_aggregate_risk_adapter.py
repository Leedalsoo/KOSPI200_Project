from core.position.position_aggregate import PositionAggregate
from core.position.position_aggregate_risk_adapter import position_aggregate_to_risk_input


def test_authoritative_side_qty_are_preserved():
    class Source:
        def snapshot(self):
            return {
                "OPTION_X": PositionAggregate(side="BUY", qty=3, avg_price=1.25),
                "OPTION_Y": PositionAggregate(side="SELL", qty=2, avg_price=0.95),
            }

    result = position_aggregate_to_risk_input(Source())

    assert result.positions["OPTION_X"].side == "BUY"
    assert result.positions["OPTION_X"].qty == 3
    assert result.positions["OPTION_Y"].side == "SELL"
    assert result.positions["OPTION_Y"].qty == 2


def test_missing_side_fails_closed():
    class Source:
        def snapshot(self):
            return {"OPTION_X": PositionAggregate(side="", qty=3)}

    try:
        pass
        position_aggregate_to_risk_input(Source())
    except TypeError as exc:
        pass
        assert str(exc) == "RISK_POSITION_SIDE_REQUIRED"
    else:
        pass
        raise AssertionError("missing side must fail closed")


def test_invalid_qty_fails_closed():
    class Source:
        def snapshot(self):
            return {"OPTION_X": PositionAggregate(side="BUY", qty=1.5)}

    try:
        pass
        position_aggregate_to_risk_input(Source())
    except TypeError as exc:
        pass
        assert str(exc) == "RISK_POSITION_QTY_REQUIRED"
    else:
        pass
        raise AssertionError("invalid qty must fail closed")


def test_non_mapping_snapshot_fails_closed():
    class Source:
        def snapshot(self):
            return None

    try:
        pass
        position_aggregate_to_risk_input(Source())
    except TypeError as exc:
        pass
        assert str(exc) == "RISK_POSITION_AGGREGATE_SOURCE_REQUIRED"
    else:
        pass
        raise AssertionError("non-mapping snapshot must fail closed")
