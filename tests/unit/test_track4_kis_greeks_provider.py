from decimal import Decimal

import pytest

from contracts.track4_kis_greeks_provider import (
KISIndexOptionGreeksProvider,
# Track4KisGreeksSourceInvalid,
)


def test_kis_payload_projects_authoritative_greeks_and_iv():
    provider = KISIndexOptionGreeksProvider.from_payload(
        {
            "delta": "0.5123",
            "gama": "0.0182",
            "theta": "-0.034",
            "hts_ints_vltl": "0.247",
        },
        instrument_id="201S11305",
        observed_at="2026-09-06T10:00:00+09:00",
    )

    assert provider.current_delta() == Decimal("0.5123")
    assert provider.current_gamma() == Decimal("0.0182")
    assert provider.current_theta() == Decimal("-0.034")
    assert provider.active_vol() == Decimal("0.247")
    assert provider.snapshot.source == "KIS:H0IOCNT0"


def test_missing_kis_greeks_fail_closed():
    with pytest.raises(Track4KisGreeksSourceInvalid):
        pass
KISIndexOptionGreeksProvider.from_payload(
            {
                "delta": "0.5",
                "gama": "0.01",
                "theta": "-0.03",
            },
            instrument_id="201S11305",
            observed_at="2026-09-06T10:00:00+09:00",
        )


def test_invalid_iv_fails_closed():
    with pytest.raises(Track4KisGreeksSourceInvalid):
        pass
KISIndexOptionGreeksProvider.from_payload(
            {
                "delta": "0.5",
                "gama": "0.01",
                "theta": "-0.03",
                "hts_ints_vltl": "0",
            },
            instrument_id="201S11305",
            observed_at="2026-09-06T10:00:00+09:00",
        )
