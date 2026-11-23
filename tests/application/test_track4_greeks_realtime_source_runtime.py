from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from infrastructure.kis.track4_kis_greeks_source import KISTrack4GreeksRealtimeSource


class _Scenario:
    @staticmethod
    def active_config():
        return {}


def _synthetic_h0iocnt0_frame(
    instrument_id: str,
    *,
    delta: str = "0.31",
    gamma: str = "0.017",
    theta: str = "-0.42",
    iv: str = "24.5",
) -> str:
    values = [""] * 58
    values[0] = instrument_id
    values[1] = "101500"
    values[28] = delta
    values[29] = gamma
    values[31] = theta
    values[33] = iv
    return "0|H0IOCNT0|1|" + "^".join(values)


def _tick(instrument_id: str, observed_at: datetime) -> ReferenceCanonicalMarketTick:
    return ReferenceCanonicalMarketTick(
        timestamp=observed_at.isoformat(),
        underlying_price=350.0,
        strike_price=350.0,
        last_price=10.0,
        seq_id=1,
        expiry="20261210",
        symbol=instrument_id,
        instrument_id=instrument_id,
    )


def test_synthetic_h0iocnt0_frame_reaches_virtual_runtime_with_exact_identity_and_time() -> None:
    observed_at = datetime(2026, 11, 23, 10, 15, tzinfo=timezone.utc)
    instrument_id = "SYNTHETIC_CONTRACT:TRACK4-CALL-350"
    source = KISTrack4GreeksRealtimeSource()

    provider = source.accept_frame(
        _synthetic_h0iocnt0_frame(instrument_id),
        observed_at=observed_at,
    )

    assert provider is not None
    assert provider.snapshot.instrument_id == instrument_id
    assert provider.snapshot.observed_at == observed_at.isoformat()
    assert provider.current_delta() == Decimal("0.31")
    assert provider.current_gamma() == Decimal("0.017")
    assert provider.current_theta() == Decimal("-0.42")
    assert provider.active_vol() == Decimal("24.5")

    market = type("Market", (), {
        "recent_ticks": [_tick(instrument_id, observed_at)],
        "underlying_history": [],
        "scenario": _Scenario(),
    })()
    runtime = VirtualRuntimeDataProvider(
        market,
        track4_greeks_provider=source,
    ).snapshot(market.recent_ticks[0])

    assert runtime.option_delta == Decimal("0.31")
    assert runtime.option_gamma == Decimal("0.017")


def test_synthetic_source_refresh_is_visible_to_existing_runtime_provider_facade() -> None:
    instrument_id = "SYNTHETIC_CONTRACT:TRACK4-CALL-350"
    first_at = datetime(2026, 11, 23, 10, 15, tzinfo=timezone.utc)
    second_at = datetime(2026, 11, 23, 10, 15, 1, tzinfo=timezone.utc)
    source = KISTrack4GreeksRealtimeSource()
    source.accept_frame(
        _synthetic_h0iocnt0_frame(instrument_id, delta="0.31", gamma="0.017"),
        observed_at=first_at,
    )
    market = type("Market", (), {
        "recent_ticks": [_tick(instrument_id, second_at)],
        "underlying_history": [],
        "scenario": _Scenario(),
    })()
    runtime_provider = VirtualRuntimeDataProvider(
        market,
        track4_greeks_provider=source,
    )

    before = runtime_provider.snapshot(market.recent_ticks[0])
    assert before.option_delta is None
    assert before.option_gamma is None

    source.accept_frame(
        _synthetic_h0iocnt0_frame(instrument_id, delta="0.33", gamma="0.019"),
        observed_at=second_at,
    )
    after = runtime_provider.snapshot(market.recent_ticks[0])

    assert after.option_delta == Decimal("0.33")
    assert after.option_gamma == Decimal("0.019")
