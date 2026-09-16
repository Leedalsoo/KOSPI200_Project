from datetime import date, datetime
from decimal import Decimal

import pytest

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from contracts.kis_index_price_source import KISIndexPriceObservation
from infrastructure.kis.basis_source import KISBasisSource
from infrastructure.kis.track2_market_metrics_source import KISTrack2MarketMetricsSource
from infrastructure.kis.track2_market_observation_sink import KISTrack2MarketObservationSink


def obs(i: int, price: str, volume: int) -> KisIndexFuturesMarketObservation:
    return KisIndexFuturesMarketObservation(
        shrn_iscd="101S2609", observed_hour=f"1015{i:02d}", price=Decimal(price),
        volume=Decimal(volume), ask_price=Decimal(price), bid_price=Decimal(price),
        source="KIS:H0IFCNT0",
    )


def test_futures_observation_updates_basis_and_track2_metrics() -> None:
    basis = KISBasisSource(max_time_delta_seconds=2.0)
    metrics = KISTrack2MarketMetricsSource(price_window=20, history_size=40)
    sink = KISTrack2MarketObservationSink(basis_source=basis, metrics_source=metrics)
    for i in range(25):
        sink.update(obs(i, f"{500 + (i % 3) * 0.5:.2f}", 100 + i * 10), session_date=date(2026, 9, 16))
    index = KISIndexPriceObservation(
        underlying_symbol="KOSPI200", index_code="2001", price=Decimal("501.0"),
        observed_at=datetime(2026, 9, 16, 10, 15, 24), source="KIS:FHPUP02100000:2001",
    )
    basis.update_index(index)
    assert basis.get_basis("201S11305") == Decimal("-1.0")
    result = metrics.get_metrics("101S2609")
    assert result is not None
    assert len(result.bbw_window) >= 2
    assert len(result.volume_window) >= 2
    assert result.active_vol >= 0
    assert result.base_vol >= 0
    assert basis.futures_contract_symbol == "101S2609"


def test_basis_rejects_stale_index_against_authoritative_futures_observation() -> None:
    basis = KISBasisSource(max_time_delta_seconds=2.0)
    sink = KISTrack2MarketObservationSink(basis_source=basis, metrics_source=KISTrack2MarketMetricsSource(price_window=2, history_size=4))
    sink.update(obs(0, "510.0", 10), session_date=date(2026, 9, 16))
    basis.update_index(KISIndexPriceObservation(
        underlying_symbol="KOSPI200", index_code="2001", price=Decimal("509.0"),
        observed_at=datetime(2026, 9, 16, 10, 15, 5), source="KIS:FHPUP02100000:2001",
    ))
    assert basis.get_basis("201S11305") is None


def test_track2_metrics_rejects_cumulative_volume_reset() -> None:
    source = KISTrack2MarketMetricsSource(price_window=2, history_size=4)
    source.update(obs(0, "510.0", 20))
    with pytest.raises(ValueError, match="CUMULATIVE_RESET"):
        source.update(obs(1, "511.0", 10))

