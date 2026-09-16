from decimal import Decimal

import pytest

from contracts.basis_source import BasisObservation
from infrastructure.kis.basis_source import KISBasisSource


def test_basis_is_futures_minus_spot_from_authoritative_observation():
    source = KISBasisSource()
    source.update(BasisObservation("KOSPI200", Decimal("352.10"), Decimal("350.80"), "101500", "KIS:H0IFCNT0+INDEX"))
    assert source.get_basis("KOSPI200") == Decimal("1.30")


def test_basis_missing_symbol_is_unavailable():
    assert KISBasisSource().get_basis("KOSPI200") is None


def test_basis_rejects_non_positive_prices():
    with pytest.raises(ValueError, match="AUTHORITATIVE_BASIS_PRICES_REQUIRED"):
        KISBasisSource().update(BasisObservation("KOSPI200", Decimal("0"), Decimal("350"), "101500", "KIS"))


def test_basis_rejects_missing_identity():
    with pytest.raises(ValueError, match="AUTHORITATIVE_BASIS_IDENTITY_REQUIRED"):
        KISBasisSource().update(BasisObservation("", Decimal("352"), Decimal("350"), "101500", "KIS"))


def test_provider_exposes_basis_when_source_is_injected():
    from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
    from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
    from environments.virtual.market.canonical import ReferenceCanonicalMarketTick

    market = VirtualMarketSimulatorRuntime()
    tick = ReferenceCanonicalMarketTick(
        timestamp="2026-09-16T10:00:00", underlying_price=350.0,
        strike_price=350.0, option_type="CALL", bid_price=3.0,
        ask_price=3.1, last_price=3.05, volume=100, seq_id=1,
        expiry="202610", symbol="KOSPI200",
    )
    market._recent_ticks.append(tick)
    source = KISBasisSource()
    source.update(BasisObservation("KOSPI200", Decimal("351.2"), Decimal("350.0"), "100000", "KIS:INDEX+FUTURES"))
    data = VirtualRuntimeDataProvider(market, basis_source=source).snapshot(tick)
    assert data.basis == Decimal("1.2")
    assert data.status["basis"].available is True


def test_basis_uses_kis_index_observation_and_rejects_stale_pair():
    from datetime import datetime
    from contracts.kis_index_price_source import KISIndexPriceObservation

    source = KISBasisSource()
    source.update_futures(
        price=Decimal("352.10"), observed_at=datetime(2026, 9, 16, 10, 15, 0),
        source="KIS:H0IFCNT0", contract_symbol="10100"
    )
    source.update_index(KISIndexPriceObservation(
        "KOSPI200", "2001", Decimal("350.80"),
        datetime(2026, 9, 16, 10, 15, 1), "KIS:FHPUP02100000:2001"
    ))
    assert source.get_basis("KOSPI200") == Decimal("1.30")

    stale = KISBasisSource(max_time_delta_seconds=2.0)
    stale.update_futures(
        price=Decimal("352.10"), observed_at=datetime(2026, 9, 16, 10, 15, 0),
        source="KIS:H0IFCNT0", contract_symbol="10100"
    )
    stale.update_index(KISIndexPriceObservation(
        "KOSPI200", "2001", Decimal("350.80"),
        datetime(2026, 9, 16, 10, 15, 5), "KIS:FHPUP02100000:2001"
    ))
    assert stale.get_basis("KOSPI200") is None


def test_basis_rejects_wrong_kospi200_index_identity():
    from datetime import datetime
    from contracts.kis_index_price_source import KISIndexPriceObservation

    source = KISBasisSource()
    with pytest.raises(ValueError, match="KIS_INDEX_PRICE_IDENTITY_MISMATCH"):
        source.update_index(KISIndexPriceObservation(
            "KOSPI200", "0001", Decimal("350"),
            datetime(2026, 9, 16, 10, 15, 0), "KIS:FHPUP02100000:0001"
        ))
