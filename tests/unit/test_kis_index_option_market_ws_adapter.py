from decimal import Decimal

import pytest

from contracts.kis_index_option_market_ws_adapter import (
    KISIndexOptionMarketWebSocketAdapter,
    KISIndexOptionMarketWebSocketAdapterInvalid,
)


def _frame(tr_id: str, values: list[str]) -> str:
    return f"0|{tr_id}|{len(values)}|{'^'.join(values)}"


def test_trade_frame_adapts_option_last_bid_ask_and_volume() -> None:
    values = [""] * 43
    values[0] = "201S11305"
    values[1] = "101530"
    values[2] = "3.25"
    values[10] = "120"
    values[41] = "3.30"
    values[42] = "3.20"

    observation = KISIndexOptionMarketWebSocketAdapter().adapt(
        _frame("H0IOCNT0", values)
    )

    assert observation.shrn_iscd == "201S11305"
    assert observation.last_price == Decimal("3.25")
    assert observation.ask_price == Decimal("3.30")
    assert observation.bid_price == Decimal("3.20")
    assert observation.volume == Decimal("120")


def test_quote_frame_adapts_option_bid_ask() -> None:
    values = ["201S11305", "101531"] + [str(3.35 + i * 0.05) for i in range(5)] + [str(3.25 - i * 0.05) for i in range(5)] + ["1"] * 20

    observation = KISIndexOptionMarketWebSocketAdapter().adapt(
        _frame("H0IOASP0", values)
    )

    assert observation.last_price is None
    assert observation.ask_price == Decimal("3.35")
    assert observation.bid_price == Decimal("3.25")
    assert observation.order_book is not None
    assert observation.order_book.ask_quantities == (Decimal("1"),) * 5
    assert observation.order_book.bid_quantities == (Decimal("1"),) * 5


def test_rejects_wrong_tr_id() -> None:
    with pytest.raises(KISIndexOptionMarketWebSocketAdapterInvalid, match="unsupported"):
        KISIndexOptionMarketWebSocketAdapter().adapt("0|H0IFCNT0|1|X")


def test_rejects_field_count_mismatch() -> None:
    with pytest.raises(KISIndexOptionMarketWebSocketAdapterInvalid, match="field count"):
        KISIndexOptionMarketWebSocketAdapter().adapt("0|H0IOASP0|8|X^Y")
