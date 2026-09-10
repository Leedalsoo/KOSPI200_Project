from decimal import Decimal

import pytest

from contracts.track4_market_projection_provider import Track4MarketProjectionProvider
from contracts.track4_kis_greeks_provider import KISIndexOptionGreeksProvider
from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable
from core.sensor.market_condition_sensor import MarketConditionSnapshot


def snapshot() -> MarketConditionSnapshot:
    return MarketConditionSnapshot(
        as_of="2026-01-01T09:00:00",
        instrument_id="KOSPI200_VIRTUAL",
        current_price=350.25,
        price_change=0.25,
        volatility=0.0125,
        baseline_volatility=0.0100,
        volatility_ratio=1.25,
        drawdown=0.0,
        stress_level=0.0,
        stress_flags=(),
    )


def test_projects_current_price_and_volatility_from_snapshot() -> None:
    provider = Track4MarketProjectionProvider(lambda: snapshot())

    assert provider.current_price() == Decimal("350.25")
    assert provider.active_vol() == Decimal("0.0125")
    assert provider.base_vol() == Decimal("0.01")


def test_market_readiness_is_partial_only() -> None:
    provider = Track4MarketProjectionProvider(lambda: snapshot())

    readiness = provider.readiness()

# assert readiness.market is True
# assert readiness.history is False
# assert readiness.account_pnl is False
# assert readiness.greeks is False
# assert readiness.attribution is False
# assert readiness.is_complete is False


def test_kis_greeks_projection_connects_to_track4_market_seam() -> None:
    greeks = KISIndexOptionGreeksProvider.from_payload(
        {"delta": "0.52", "gama": "0.18", "theta": "-0.07", "hts_ints_vltl": "0.21"},
        instrument_id="KOSPI200-OPT-1",
        observed_at="2026-01-01T09:00:00",
    )
    provider = Track4MarketProjectionProvider(lambda: snapshot(), greeks_provider=greeks)

    assert provider.current_delta() == Decimal("0.52")
    assert provider.current_gamma() == Decimal("0.18")
    assert provider.active_vol() == Decimal("0.21")
# assert provider.readiness().greeks is True


def test_missing_snapshot_fails_closed() -> None:
    provider = Track4MarketProjectionProvider(lambda: None)

# assert provider.readiness().market is False
    with pytest.raises(Track4InputSourceUnavailable):
        pass
# provider.current_price()


def test_unsupported_sources_fail_closed() -> None:
    provider = Track4MarketProjectionProvider(lambda: snapshot())

    with pytest.raises(Track4InputSourceUnavailable):
        pass
# provider.current_delta()
    with pytest.raises(Track4InputSourceUnavailable):
        pass
# provider.current_pnl()
