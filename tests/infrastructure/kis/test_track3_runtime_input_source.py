from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from contracts.kis_index_price_source import KISIndexPriceObservation
from infrastructure.kis.track3_runtime_input_source import KISTrack3RuntimeInputSource


def _source(*, regime: str = "NORMAL"):
    source = KISTrack3RuntimeInputSource()
    start = datetime(2026, 11, 20, 10, 0, 0)
    for index in range(12):
        observed_at = start + timedelta(seconds=index)
        index_price = Decimal("1000") + Decimal(index)
        basis = (Decimal("0.40") + Decimal(index) * Decimal("0.01") if index < 11 else Decimal("0.48"))
        source.update_futures(
            KisIndexFuturesMarketObservation(
                shrn_iscd="A05610",
                observed_hour=observed_at.strftime("%H%M%S"),
                price=index_price + basis,
                volume=Decimal("1"),
                ask_price=index_price + basis + Decimal("0.05"),
                bid_price=index_price + basis - Decimal("0.05"),
                source="KIS:H0IFCNT0",
            ),
            session_date=observed_at.date(),
        )
        source.update_index(
            KISIndexPriceObservation(
                underlying_symbol="KOSPI200",
                index_code="2001",
                price=index_price,
                observed_at=observed_at,
                source="KIS:H0UPCNT0",
            )
        )
    observed_at = start + timedelta(seconds=11)
    identity = SimpleNamespace(
        instrument_id="B01611887",
        option_type="CALL",
        strike=Decimal("887.50"),
        expiry="20261126",
        contract_multiplier=Decimal("250000"),
    )
    option = SimpleNamespace(
        observed_at=observed_at,
        collected_at=observed_at,
        contract=identity,
        quote=SimpleNamespace(last=Decimal("10")),
        source="KIS:OPTION_TEST_FIXTURE",
    )
    source.update_option(option)
    source.set_option_quantity(
        instrument_id="B01611887", observed_at=observed_at, quantity=1
    )
    source.set_common_analytics(
        observed_at=observed_at,
        active_vol=20.0,
        base_vol=15.0,
        current_regime=regime,
    )
    source.set_execution_totals(
        observed_at=observed_at - timedelta(seconds=5),
        total_fees=Decimal("2"),
        premium_spent=Decimal("20"),
    )
    source.set_execution_totals(
        observed_at=observed_at,
        total_fees=Decimal("1"),
        premium_spent=Decimal("10"),
    )
    return source, observed_at


def test_track3_basis_history_uses_paired_futures_minus_index_not_underlying_returns():
    source, observed_at = _source()

    result = source.get_input("KOSPI200", observed_at)

    assert result is not None
    assert len(result.spread_history) == 12
    assert result.spread_history[0] == 0.40
    assert result.spread_history[-1] == 0.48
    assert result.market_stable is True
    assert result.spread_normalizing is True


def test_track3_execution_totals_use_latest_timestamp_not_largest_value():
    source, observed_at = _source()

    result = source.get_input("KOSPI200", observed_at)

    assert result is not None
    assert result.total_fees == 1.0
    assert result.premium_spent == 10.0


def test_track3_market_stability_comes_from_common_regime():
    source, observed_at = _source(regime="HIGH_VOLATILITY")

    result = source.get_input("KOSPI200", observed_at)

    assert result is not None
    assert result.market_stable is False


def test_track3_basis_history_does_not_use_index_observation_after_as_of():
    source, observed_at = _source()
    source._index = type(source._index)(
        (item for item in source._index if item.observed_at < observed_at - timedelta(seconds=3)),
        maxlen=source._HISTORY_SIZE,
    )
    future_index_time = observed_at + timedelta(seconds=1)
    source.update_index(
        KISIndexPriceObservation(
            underlying_symbol="KOSPI200",
            index_code="2001",
            price=Decimal("2000"),
            observed_at=future_index_time,
            source="KIS:H0UPCNT0",
        )
    )

    result = source.get_input("KOSPI200", observed_at)

    assert result is None
