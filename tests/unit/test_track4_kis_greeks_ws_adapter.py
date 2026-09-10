from decimal import Decimal

import pytest

from contracts.track4_kis_greeks_ws_adapter import (
    KISIndexOptionGreeksWebSocketAdapter,
    Track4KisWebSocketAdapterInvalid,
)


def _frame() -> str:
    values = [""] * 58
    values[0] = "201S11305"
    values[1] = "101530"
    values[28] = "0.5123"  # delta
    values[29] = "0.0182"  # gama
    values[31] = "-0.034"  # theta
    values[33] = "0.247"   # hts_ints_vltl
    return f"0|H0IOCNT0|{len(values)}|{'^'.join(values)}"


def test_h0iocnt0_wire_frame_reaches_provider_without_recalculation() -> None:
    provider = KISIndexOptionGreeksWebSocketAdapter().adapt(
        _frame(), observed_at="2026-09-06T10:15:30+09:00"
    )

    assert provider.current_delta() == Decimal("0.5123")
    assert provider.current_gamma() == Decimal("0.0182")
    assert provider.current_theta() == Decimal("-0.034")
    assert provider.active_vol() == Decimal("0.247")
    assert provider.snapshot.instrument_id == "201S11305"
    assert provider.snapshot.source == "KIS:H0IOCNT0"


def test_unexpected_tr_id_is_rejected() -> None:
    with pytest.raises(Track4KisWebSocketAdapterInvalid):
        KISIndexOptionGreeksWebSocketAdapter().adapt(
            _frame().replace("H0IOCNT0", "H0IFCNT0"),
            observed_at="2026-09-06T10:15:30+09:00",
        )


def test_field_count_mismatch_is_rejected() -> None:
    frame = _frame().replace("|58|", "|57|")
    with pytest.raises(Track4KisWebSocketAdapterInvalid):
        KISIndexOptionGreeksWebSocketAdapter().adapt(
            frame, observed_at="2026-09-06T10:15:30+09:00"
        )
