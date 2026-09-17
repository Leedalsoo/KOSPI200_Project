from __future__ import annotations

from dataclasses import dataclass, replace

from contracts.futures_execution_symbol_source import KisFuturesExecutionSymbolSource
from contracts.types import BrokerOrderCommand


class FuturesBrokerCommandMappingError(ValueError):
    """Raised when a FUTURES broker command cannot be mapped safely."""


@dataclass(frozen=True)
class KisFuturesBrokerCommandAdapter:
    """Attach the authoritative KIS FUTURES execution symbol to a broker command.

    The adapter does not create instrument identity, infer contract codes, or
    submit an order. It only projects the selected Contract Master short code
    into the environment-specific broker_symbol field.
    """

    symbol_source: KisFuturesExecutionSymbolSource

    def to_broker_command(self, command: BrokerOrderCommand) -> BrokerOrderCommand:
        if command.asset_type != "FUTURES":
            raise FuturesBrokerCommandMappingError("FUTURES_ASSET_TYPE_REQUIRED")
        if not command.client_order_id:
            raise FuturesBrokerCommandMappingError("CLIENT_ORDER_ID_REQUIRED")
        if not command.instrument_id:
            raise FuturesBrokerCommandMappingError("INSTRUMENT_ID_REQUIRED")
        if command.quantity <= 0:
            raise FuturesBrokerCommandMappingError("QUANTITY_REQUIRED")
        if not command.order_type:
            raise FuturesBrokerCommandMappingError("ORDER_TYPE_REQUIRED")

        broker_symbol = self.symbol_source.current_symbol()
        if not broker_symbol:
            raise FuturesBrokerCommandMappingError("FUTURES_BROKER_SYMBOL_REQUIRED")

        return replace(command, broker_symbol=broker_symbol)
