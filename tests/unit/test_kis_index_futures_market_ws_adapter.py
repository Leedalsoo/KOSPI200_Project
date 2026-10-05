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
    values[34] = "350.30"
    values[35] = "350.20"
    return "0|H0IFCNT0|50|" + "^".join(values)


def test_h0ifcnt0_preserves_kis_short_code_and_market_values():
    result = KISIndexFuturesMarketWebSocketAdapter().adapt(frame())

    assert result.shrn_iscd == "101S12"
    assert result.observed_hour == "103015"
    assert result.price == Decimal("350.25")
    assert result.volume == Decimal("12345")
    assert result.ask_price == Decimal("350.30")
    assert result.bid_price == Decimal("350.20")


def test_h0ifcnt0_accepts_actual_single_record_frame():
    actual = frame().replace("|50|", "|001|")

    result = KISIndexFuturesMarketWebSocketAdapter().adapt(actual)

    assert result.shrn_iscd == "101S12"
    assert result.observed_hour == "103015"


def test_h0ifcnt0_rejects_wrong_tr_id():
    with pytest.raises(KISIndexFuturesWebSocketAdapterInvalid):
        KISIndexFuturesMarketWebSocketAdapter().adapt(frame().replace("H0IFCNT0", "H0IOCNT0"))


def test_h0ifcnt0_rejects_field_count_mismatch():
    with pytest.raises(KISIndexFuturesWebSocketAdapterInvalid):
        KISIndexFuturesMarketWebSocketAdapter().adapt(frame().replace("|50|", "|49|"))


def test_h0ifcnt0_adapt_many_parses_repeated_records():
    repeated = frame().replace("|50|", "|002|") + "^" + frame().split("|", 3)[3]
    repeated = repeated.replace("|002|", "|002|", 1)
    # The second record differs only in its timestamp/value, while preserving 50-field width.
    values = frame().split("|", 3)[3].split("^")
    values2 = list(values)
    values2[1] = "103016"
    values2[5] = "350.35"
    repeated = "0|H0IFCNT0|002|" + "^".join(values + values2)
    result = KISIndexFuturesMarketWebSocketAdapter().adapt_many(repeated)
    assert len(result) == 2
    assert result[0].observed_hour == "103015"
    assert result[1].observed_hour == "103016"
