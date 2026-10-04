from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from infrastructure.kis.track2_market_observation_sink import KISTrack2MarketObservationSink
from infrastructure.kis.volume_profile_source import KISVolumeProfileSource


def _provider(loop):
    for cell in loop.context_builder.__closure__ or ():
        value = cell.cell_contents
        if value.__class__.__name__ == "StandardRuntimeInputProvider":
            return value
    raise AssertionError("STANDARD_RUNTIME_INPUT_PROVIDER_NOT_FOUND")


def _obs(i: int, price: str, volume: int) -> KisIndexFuturesMarketObservation:
    return KisIndexFuturesMarketObservation(
        shrn_iscd="101S2609",
        observed_hour=f"1015{i:02d}",
        price=Decimal(price),
        volume=Decimal(volume),
        ask_price=Decimal(price),
        bid_price=Decimal(price),
        source="KIS:H0IFCNT0",
    )


def test_production_virtual_runtime_injects_authoritative_track2_sources_and_sink() -> None:
    bootstrap = create_virtual_runtime_bootstrap()
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=("track2_asymmetric_trap",),
        run_id="TRACK2-WIRING-TEST",
    )
    provider = _provider(loop)

    assert isinstance(provider.data.volume_profile_source, KISVolumeProfileSource)
    assert isinstance(provider.track2_market_observation_sink, KISTrack2MarketObservationSink)
    assert provider.data.volume_profile_source is provider.track2_market_observation_sink.volume_profile_source
    assert provider.data.track2_metrics_source is provider.track2_market_observation_sink.metrics_source
    assert provider.data.basis_source is provider.track2_market_observation_sink.basis_source

    for i in range(25):
        provider.track2_market_observation_sink.update(
            _obs(i, f"{500 + (i % 3) * 0.5:.2f}", 100 + i * 10),
            session_date=datetime(2026, 10, 2).date(),
        )

    tick = SimpleNamespace(
        timestamp="2026-10-02T10:15:24",
        last_price=Decimal("501"),
        bid_price=Decimal("500.9"),
        ask_price=Decimal("501.1"),
        strike_price=Decimal("500"),
        expiry="202610",
        seq_id=1,
        symbol="KOSPI200",
    )
    runtime_data = provider.data.snapshot(tick)
    assert runtime_data.poc_price is not None
    assert runtime_data.status["volume_profile_poc"].available is True
    assert runtime_data.status["track2_bbw_volume"].available is True

def test_virtual_futures_identity_uses_authoritative_mini_target_not_option_tick_symbol() -> None:
    bootstrap = create_virtual_runtime_bootstrap()
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=("track4_gamma_scalping",),
        run_id="TRACK4-FUTURES-IDENTITY-TEST",
    )
    identity_provider = loop.identity_provider
    evaluation = SimpleNamespace(
        result=SimpleNamespace(
            execution_proposal=SimpleNamespace(asset_type="FUTURES")
        )
    )
    option_tick = SimpleNamespace(instrument_id="C01610A32", symbol="C01610A32")

    option_tick.timestamp = "2026-10-02T10:15:24"
    identity = identity_provider(evaluation, option_tick)

    assert identity.symbol == "A05610"
    assert identity.instrument_id == "A05610"
