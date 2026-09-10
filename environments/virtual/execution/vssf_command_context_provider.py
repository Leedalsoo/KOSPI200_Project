from dataclasses import dataclass
from decimal import Decimal

from contracts.types import BrokerOrderCommand
from shared.contracts.canonical import (
    CanonicalAssetType, CanonicalOptionType, CanonicalOrderCommand, CanonicalOrderSide,
)


class VSSFCommandContextError(ValueError):
    """Raised when a Standard order cannot be losslessly converted for VSSF."""


@dataclass(frozen=True)
class CanonicalVSSFCommandContextProvider:
    """Concrete Standard BrokerOrderCommand -> Reference CanonicalOrderCommand adapter."""

    def build_command(self, order: BrokerOrderCommand) -> CanonicalOrderCommand:
        identity = order.instrument_identity
        if not order.client_order_id:
            raise VSSFCommandContextError("CLIENT_ORDER_ID_REQUIRED")
        if not order.track_id:
            raise VSSFCommandContextError("TRACK_ID_REQUIRED")
        if order.quantity <= 0:
            raise VSSFCommandContextError("QUANTITY_REQUIRED")
        if order.requested_price is None:
            raise VSSFCommandContextError("REQUESTED_PRICE_REQUIRED")
        if order.asset_type != CanonicalAssetType.OPTION.value:
            raise VSSFCommandContextError("OPTION_ASSET_TYPE_REQUIRED")
        if order.side not in {CanonicalOrderSide.BUY.value, CanonicalOrderSide.SELL.value}:
            raise VSSFCommandContextError("CANONICAL_SIDE_REQUIRED")
        if identity is None:
            raise VSSFCommandContextError("OPTION_IDENTITY_REQUIRED")
        if identity.instrument_id != order.instrument_id:
            raise VSSFCommandContextError("INSTRUMENT_IDENTITY_MISMATCH")
        if not identity.symbol:
            raise VSSFCommandContextError("OPTION_SYMBOL_REQUIRED")
        if not identity.expiry:
            raise VSSFCommandContextError("OPTION_EXPIRY_REQUIRED")
        if identity.option_type not in {
            CanonicalOptionType.CALL.value, CanonicalOptionType.PUT.value,
        }:
            raise VSSFCommandContextError("CANONICAL_OPTION_TYPE_REQUIRED")
        if identity.strike is None or identity.strike <= Decimal("0"):
            raise VSSFCommandContextError("OPTION_STRIKE_REQUIRED")
        if not order.tag_id:
            raise VSSFCommandContextError("TAG_ID_REQUIRED")

        return CanonicalOrderCommand(
            client_order_id=order.client_order_id,
            track_id=order.track_id,
            asset_type=CanonicalAssetType(order.asset_type),
            side=CanonicalOrderSide(order.side),
            qty=order.quantity,
            price=float(order.requested_price),
            option_type=CanonicalOptionType(identity.option_type),
            strike=float(identity.strike),
            symbol=identity.symbol,
            expiry=identity.expiry,
            tag_id=order.tag_id,
        )
