from decimal import Decimal

import pytest

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from infrastructure.kis.underlying_market_state import (
    KISUnderlyingMarketState,
    UnderlyingMarketStateError,
)


def _observation(price: Decimal | None = Decimal("512.50")):
    return KisIndexFuturesMarketObservation(
        shrn_iscd="101V6000",
        observed_hour="101530",
        price=price,
        volume=Decimal("100"),
        ask_price=Decimal("512.55"),
        bid_price=Decimal("512.45"),
        source="KIS:H0IFCNT0",
    )


def test_updates_authoritative_underlying_price() -> None:
    state = KISUnderlyingMarketState()
    state.update(_observation())
    assert state.price_for() == Decimal("512.50")
    assert state.state is not None
    assert state.state.symbol == "101V6000"


def test_price_only_updates_when_trade_price_exists() -> None:
    state = KISUnderlyingMarketState()
    state.update(_observation())
    state.update(_observation(None))
    assert state.price_for() == Decimal("512.50")


def test_missing_underlying_fails_closed() -> None:
    state = KISUnderlyingMarketState()
    with pytest.raises(UnderlyingMarketStateError, match="PRICE_REQUIRED"):
        state.price_for()
