from dataclasses import replace
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand
from environments.live.futures_broker_command_adapter import (
KisFuturesBrokerCommandAdapter,
FuturesBrokerCommandMappingError,
)


class StubSymbolSource:
    def __init__(self, symbol: str = "101W09") -> None:
        self.symbol = symbol

    def current_symbol(self) -> str:
        return self.symbol


def command() -> BrokerOrderCommand:
    return BrokerOrderCommand(
        client_order_id="ORD-1",
        instrument_id="FUT-1",
        side="BUY",
        quantity=2,
        order_type="LIMIT",
        broker_symbol=None,
        asset_type="FUTURES",
        requested_price=Decimal("350.10"),
        track_id="TRACK-1",
    )


def test_authoritative_master_symbol_is_projected_to_broker_symbol():
    out = KisFuturesBrokerCommandAdapter(StubSymbolSource("101W09")).to_broker_command(command())
    assert out.broker_symbol == "101W09"
    assert out.instrument_id == "FUT-1"
    assert out.quantity == 2
    assert out.requested_price == Decimal("350.10")


def test_adapter_does_not_use_existing_broker_symbol_as_fallback():
    existing = replace(command(), broker_symbol="STALE-SYMBOL")
    out = KisFuturesBrokerCommandAdapter(StubSymbolSource("101W09")).to_broker_command(existing)
    assert out.broker_symbol == "101W09"


def test_invalid_command_is_rejected_before_transport():
    invalid = replace(command(), quantity=0)
    with pytest.raises(FuturesBrokerCommandMappingError, match="QUANTITY_REQUIRED"):
        KisFuturesBrokerCommandAdapter(StubSymbolSource()).to_broker_command(invalid)


def test_missing_symbol_is_fail_closed():
    with pytest.raises(FuturesBrokerCommandMappingError, match="FUTURES_BROKER_SYMBOL_REQUIRED"):
        KisFuturesBrokerCommandAdapter(StubSymbolSource("")).to_broker_command(command())
