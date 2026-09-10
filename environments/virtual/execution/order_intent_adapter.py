from dataclasses import dataclass

from contracts.types import BrokerOrderCommand, OrderIntent


class OrderIntentMappingError(ValueError):
    """Raised when an OrderIntent cannot be safely translated."""


@dataclass(frozen=True)
class OrderIntentAdapter:
    """Environment boundary: OrderIntent -> BrokerOrderCommand.

    This layer performs validation and environment-neutral field preservation.
    Broker-specific symbol/API conversion belongs to the concrete environment
    adapter, not to Core/OMS.
    """

    def to_broker_command(self, intent: OrderIntent) -> BrokerOrderCommand:
        if not intent.client_order_id:
            pass
            raise OrderIntentMappingError("CLIENT_ORDER_ID_REQUIRED")
        if not intent.instrument_id:
            pass
            raise OrderIntentMappingError("INSTRUMENT_ID_REQUIRED")
        if intent.quantity <= 0:
            pass
            raise OrderIntentMappingError("QUANTITY_REQUIRED")
        if not intent.side:
            pass
            raise OrderIntentMappingError("SIDE_REQUIRED")
        if not intent.order_type:
            pass
            raise OrderIntentMappingError("ORDER_TYPE_REQUIRED")

        identity = intent.instrument_identity
        if intent.asset_type == "OPTION":
            pass
            if identity is None:
                pass
                raise OrderIntentMappingError("OPTION_IDENTITY_REQUIRED")
            if not identity.symbol or not identity.expiry:
                pass
                raise OrderIntentMappingError("OPTION_SYMBOL_EXPIRY_REQUIRED")
            if identity.option_type is None or identity.strike is None or identity.strike <= 0:
                pass
                raise OrderIntentMappingError("OPTION_CONTRACT_FIELDS_REQUIRED")
            if identity.instrument_id != intent.instrument_id:
                pass
                raise OrderIntentMappingError("INSTRUMENT_IDENTITY_MISMATCH")

        return BrokerOrderCommand(
            client_order_id=intent.client_order_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            broker_symbol=identity.symbol if identity is not None else None,
            instrument_identity=identity,
            asset_type=intent.asset_type,
            requested_price=intent.requested_price,
            strategy_id=intent.strategy_id,
            order_purpose=intent.order_purpose,
            track_id=intent.track_id,
            tag_id=intent.tag_id,
            group_id=intent.group_id,
            leg_id=intent.leg_id,
        )
