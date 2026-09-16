from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from infrastructure.kis.volume_profile_source import KISVolumeProfileSource
from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider


def _obs(symbol: str, price: str, volume: str, hour: str = "101500"):
    return KisIndexFuturesMarketObservation(
        shrn_iscd=symbol, observed_hour=hour, price=Decimal(price),
        volume=Decimal(volume), ask_price=Decimal("510"),
        bid_price=Decimal("509.95"), source="KIS:H0IFCNT0"
    )


def test_poc_uses_cumulative_volume_deltas() -> None:
    source = KISVolumeProfileSource()
    source.update(_obs("101V6000", "510", "10"))
    source.update(_obs("101V6000", "511", "25"))
    source.update(_obs("101V6000", "510", "45"))
    assert source.get_poc("101V6000") == Decimal("510")


def test_poc_is_unavailable_without_trade_volume() -> None:
    source = KISVolumeProfileSource()
    assert source.get_poc("101V6000") is None


def test_cumulative_volume_reset_is_rejected() -> None:
    source = KISVolumeProfileSource()
    source.update(_obs("101V6000", "510", "20"))
    with pytest.raises(ValueError, match="CUMULATIVE_VOLUME_RESET"):
        source.update(_obs("101V6000", "511", "10"))


def test_runtime_exposes_poc_only_from_injected_source() -> None:
    source = KISVolumeProfileSource()
    source.update(_obs("201S11305", "510", "10"))
    source.update(_obs("201S11305", "511", "30"))
    market = SimpleNamespace(
        recent_ticks=(SimpleNamespace(last_price=Decimal("511"),),),
        option_quotes={},
        scenario=SimpleNamespace(active_config=lambda: {"base_volatility": 1.0, "shock_interval_days": 999999}),
    )
    tick = SimpleNamespace(
        timestamp=datetime(2026, 9, 16, 10, 15).isoformat(), last_price=Decimal("511"),
        bid_price=Decimal("510.9"), ask_price=Decimal("511.1"), strike_price=Decimal("510"),
        expiry="202610", seq_id=1, symbol="201S11305",
    )
    data = VirtualRuntimeDataProvider(market, volume_profile_source=source).snapshot(tick)
    assert data.poc_price == Decimal("511")
    assert data.status["volume_profile_poc"].available is True
