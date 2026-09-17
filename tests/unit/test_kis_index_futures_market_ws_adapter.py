from decimal import Decimal
import pytest

from contracts.kis_index_futures_market_ws_adapter import (
KISIndexFuturesMarketWebSocketAdapter,
KISIndexFuturesWebSocketAdapterInvalid,
)


def frame() -> str:
    values = [""] * 50
    values[0] = "101S12"
    values[1] = "103015"
    values[5] = "350.25"
    values[10] = "12345"
    values[35] = "350.30"
    values[36] = "350.20"
    return "0|H0IFCNT0|50|" + "^".join(values)


def test_h0ifcnt0_preserves_kis_short_code_and_market_values():
    result = KISIndexFuturesMarketWebSocketAdapter().adapt(frame())

    assert result.shrn_iscd == "101S12"
    assert result.observed_hour == "103015"
    assert result.price == Decimal("350.25")
    assert result.volume == Decimal("12345")
    assert result.ask_price == Decimal("350.30")
    assert result.bid_price == Decimal("350.20")


def test_h0ifcnt0_rejects_wrong_tr_id():
    with pytest.raises(KISIndexFuturesWebSocketAdapterInvalid):
        KISIndexFuturesMarketWebSocketAdapter().adapt(frame().replace("H0IFCNT0", "H0IOCNT0"))


def test_h0ifcnt0_rejects_field_count_mismatch():
    with pytest.raises(KISIndexFuturesWebSocketAdapterInvalid):
        KISIndexFuturesMarketWebSocketAdapter().adapt(frame().replace("|50|", "|49|"))
