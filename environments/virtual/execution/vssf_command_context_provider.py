from dataclasses import dataclass
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
        if order.side not in {CanonicalOrderSide.BUY.value, CanonicalOrderSide.SELL.value}:
            raise VSSFCommandContextError("CANONICAL_SIDE_REQUIRED")
        if not order.tag_id:
            raise VSSFCommandContextError("TAG_ID_REQUIRED")
        asset_type = order.asset_type
        if asset_type == CanonicalAssetType.OPTION.value:
            if identity is None:
                raise VSSFCommandContextError("OPTION_IDENTITY_REQUIRED")
            if identity.instrument_id != order.instrument_id:
                raise VSSFCommandContextError("INSTRUMENT_IDENTITY_MISMATCH")
            if not identity.symbol:
                raise VSSFCommandContextError("OPTION_SYMBOL_REQUIRED")
            if not identity.expiry:
                raise VSSFCommandContextError("OPTION_EXPIRY_REQUIRED")
            if identity.option_type not in {CanonicalOptionType.CALL.value, CanonicalOptionType.PUT.value}:
                raise VSSFCommandContextError("CANONICAL_OPTION_TYPE_REQUIRED")
            if identity.strike is None or identity.strike <= Decimal("0"):
                raise VSSFCommandContextError("OPTION_STRIKE_REQUIRED")
            option_type = CanonicalOptionType(identity.option_type)
            strike = float(identity.strike)
            symbol = identity.symbol
            expiry = identity.expiry
        elif asset_type == CanonicalAssetType.FUTURES.value:
            option_type = None
            strike = 0.0
            symbol = order.broker_symbol or order.instrument_id
            expiry = None
        else:
            raise VSSFCommandContextError("UNSUPPORTED_ASSET_TYPE")

        return CanonicalOrderCommand(
            client_order_id=order.client_order_id,
            track_id=order.track_id,
            asset_type=CanonicalAssetType(order.asset_type),
            side=CanonicalOrderSide(order.side),
            qty=order.quantity,
            price=float(order.requested_price),
            option_type=option_type,
            strike=strike,
            symbol=symbol,
            expiry=expiry,
            tag_id=order.tag_id,
            strategy_id=order.strategy_id or "",
            group_id=order.group_id or "",
            leg_id=order.leg_id or "",
        )
