```python
from dataclasses import dataclass
from decimal import Decimal

from contracts.types import BrokerOrderCommand
from environments.live.futures_broker_command_adapter import KisFuturesBrokerCommandAdapter


@dataclass
class StubSymbolSource:
    symbol: str

    def current_symbol(self) -> str:
        return self.symbol


def command() -> BrokerOrderCommand:
    return BrokerOrderCommand(
        client_order_id="C1",
        instrument_id="FUT.K200.202609",
        side="BUY",
        quantity=1,
        order_type="LIMIT",
        asset_type="FUTURES",
        requested_price=Decimal("500.00"),
    )


def test_authoritative_symbol_is_attached_without_changing_instrument_id():
    adapter = KisFuturesBrokerCommandAdapter(StubSymbolSource("105V9ABC"))
    result = adapter.to_broker_command(command())
    assert result.broker_symbol == "105V9ABC"
    assert result.instrument_id == "FUT.K200.202609"


def test_missing_symbol_fails_closed():
    adapter = KisFuturesBrokerCommandAdapter(StubSymbolSource("  "))
    try:
        adapter.to_broker_command(command())
    except ValueError as exc:
        assert str(exc) == "FUTURES_BROKER_SYMBOL_REQUIRED"
    else:
        raise AssertionError("expected fail-closed validation")
```