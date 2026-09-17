from datetime import datetime
from decimal import Decimal

import pytest

from application.composition.track7_support_resistance_source import Track7AuthoritativeSupportResistanceSource
from contracts.track7_support_resistance_source import Track7SupportResistanceObservation


class ExplicitSource:
    def get_support_resistance(self, *, symbol, observed_at, current_price):
        return Track7SupportResistanceObservation(
            support=Decimal("340"), resistance=Decimal("360"), observed_at=observed_at,
            source="TEST.EXPLICIT.SR", definition="PROJECT_DEFINED_TEST_LEVELS",
            window="test-window", calculation_version="test-v1",
        )


def test_authoritative_adapter_preserves_source_contract():
    observed = datetime(2026, 9, 17, 9, 0)
    source = Track7AuthoritativeSupportResistanceSource(ExplicitSource())
    result = source.get(symbol="KOSPI200", observed_at=observed, current_price=Decimal("350"))
    assert result.support == Decimal("340")
    assert result.resistance == Decimal("360")
    assert result.source == "TEST.EXPLICIT.SR"
    assert result.definition == "PROJECT_DEFINED_TEST_LEVELS"


def test_adapter_rejects_future_observation():
    observed = datetime(2026, 9, 17, 9, 0)

    class FutureSource(ExplicitSource):
        def get_support_resistance(self, *, symbol, observed_at, current_price):
            return Track7SupportResistanceObservation(
                Decimal("340"), Decimal("360"),
                datetime(2026, 9, 17, 9, 1), "TEST", "DEFINED", "window", "v1"
            )

    source = Track7AuthoritativeSupportResistanceSource(FutureSource())
    with pytest.raises(ValueError, match="FUTURE_OBSERVATION"):
        source.get(symbol="KOSPI200", observed_at=observed, current_price=Decimal("350"))


def test_runtime_data_provider_projects_injected_authoritative_levels():
    from types import SimpleNamespace
    from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider

    observed = datetime(2026, 9, 17, 9, 0)
    tick = SimpleNamespace(timestamp=observed.isoformat(), last_price=350.0, symbol="KOSPI200",
                           strike_price=350.0, option_type="CALL", expiry="202609", seq_id=1)
    market = SimpleNamespace(recent_ticks=(tick,), scenario=SimpleNamespace(active_config=lambda: {}))
    source = Track7AuthoritativeSupportResistanceSource(ExplicitSource())
    data = VirtualRuntimeDataProvider(market, track7_support_resistance_source=source).snapshot(tick)
    assert data.support == Decimal("340")
    assert data.resistance == Decimal("360")
    assert data.status["track7_support_resistance"].available is True
