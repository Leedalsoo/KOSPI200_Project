from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick


class _Scenario:
    @staticmethod
    def active_config():
        return {}


class _GreeksProvider:
    def __init__(self, instrument_id: str, observed_at: datetime) -> None:
        self.snapshot = SimpleNamespace(
            instrument_id=instrument_id,
            observed_at=observed_at.isoformat(),
        )

    @staticmethod
    def current_delta() -> Decimal:
        return Decimal("0.25")

    @staticmethod
    def current_gamma() -> Decimal:
        return Decimal("0.015")


class _GreeksSource:
    def __init__(self, provider: _GreeksProvider) -> None:
        self.provider = provider

    def current_delta(self) -> Decimal:
        return self.provider.current_delta()

    def current_gamma(self) -> Decimal:
        return self.provider.current_gamma()



def _runtime_data(*, tick_instrument: str, greeks_instrument: str, tick_at: datetime, greeks_at: datetime):
    tick = ReferenceCanonicalMarketTick(
        timestamp=tick_at.isoformat(),
        underlying_price=350.0,
        strike_price=350.0,
        last_price=10.0,
        seq_id=1,
        expiry="20261210",
        symbol=tick_instrument,
        instrument_id=tick_instrument,
    )
    market = SimpleNamespace(
        recent_ticks=[tick],
        underlying_history=[],
        scenario=_Scenario(),
    )
    provider = _GreeksSource(_GreeksProvider(greeks_instrument, greeks_at))
    return VirtualRuntimeDataProvider(market, track4_greeks_provider=provider).snapshot(tick)


def test_track4_greeks_from_different_option_instrument_are_not_injected() -> None:
    observed_at = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)
    data = _runtime_data(
        tick_instrument="SYNTHETIC:OPTION-A",
        greeks_instrument="SYNTHETIC:OPTION-B",
        tick_at=observed_at,
        greeks_at=observed_at,
    )

    assert data.option_delta is None
    assert data.option_gamma is None


def test_track4_greeks_from_older_tick_are_not_injected() -> None:
    tick_at = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)
    greeks_at = datetime(2026, 11, 23, 8, 59, tzinfo=timezone.utc)
    data = _runtime_data(
        tick_instrument="SYNTHETIC:OPTION-A",
        greeks_instrument="SYNTHETIC:OPTION-A",
        tick_at=tick_at,
        greeks_at=greeks_at,
    )

    assert data.option_delta is None
    assert data.option_gamma is None


def test_track4_greeks_with_exact_instrument_and_tick_time_are_injected() -> None:
    observed_at = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)
    data = _runtime_data(
        tick_instrument="SYNTHETIC:OPTION-A",
        greeks_instrument="SYNTHETIC:OPTION-A",
        tick_at=observed_at,
        greeks_at=observed_at,
    )

    assert data.option_delta == Decimal("0.25")
    assert data.option_gamma == Decimal("0.015")
