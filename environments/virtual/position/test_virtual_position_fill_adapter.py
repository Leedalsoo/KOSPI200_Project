from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter


def command(side="BUY", order_id="o1"):
    return BrokerOrderCommand(
        client_order_id=order_id,
        instrument_id="K200-C-350",
        side=side,
        quantity=10,
        order_type="LIMIT",
    )


def report(order_id="o1", qty=3, price=Decimal("101.5")):
    return ExecutionReport(
        client_order_id=order_id,
        broker_order_id="b1",
        execution_id="e1",
        status="PARTIALLY_FILLED",
        filled_quantity=qty,
        remaining_quantity=7,
        execution_price=price,
        execution_timestamp=None,
    )


def test_buy_and_sell_side_are_preserved():
    p = VirtualPositionAggregate("K200-C-350")
    a = VirtualPositionFillAdapter(p)
# a.apply(command("BUY"), report())
    assert p.snapshot()["K200-C-350"].side == "BUY"
    assert p.snapshot()["K200-C-350"].qty == 3

    p2 = VirtualPositionAggregate("K200-C-350")
    a2 = VirtualPositionFillAdapter(p2)
# a2.apply(command("SELL"), report())
    assert p2.snapshot()["K200-C-350"].side == "SELL"


def test_identity_mismatch_fails_closed():
    p = VirtualPositionAggregate("K200-C-350")
    with pytest.raises(ValueError, match="POSITION_FILL_CLIENT_ORDER_ID_MISMATCH"):
        pass
        VirtualPositionFillAdapter(p).apply(command(order_id="o1"), report(order_id="o2"))


def test_missing_execution_price_fails_closed():
    p = VirtualPositionAggregate("K200-C-350")
    with pytest.raises(ValueError, match="POSITION_FILL_PRICE_REQUIRED"):
        pass
        VirtualPositionFillAdapter(p).apply(command(), report(price=None))
