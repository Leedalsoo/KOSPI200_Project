from dataclasses import dataclass
from decimal import Decimal
from contracts.types import OptionInstrumentIdentity, OrderIntent
from core.strategy.contracts import Signal
from core.oms.option_identity_resolver import (
OptionIdentityResolutionInput,
OptionIdentityResolver,
)


class OrderIntentValidationError(ValueError):
    """Raised when a Signal cannot be converted into an executable intent."""


@dataclass(frozen=True)
class OrderIntentExecutionInput:
    """Execution semantics supplied by Risk/Position Logic, not Strategy."""

    client_order_id: str
    quantity: int
    requested_price: Decimal | None
    order_type: str
    order_purpose: str
    asset_type: str
    track_id: str | None = None
    tag_id: str | None = None


@dataclass(frozen=True)
class OrderIntentFactory:
    """Builds an immutable OrderIntent after identity resolution.

    Strategy supplies direction and optional option-selection overrides.
    Risk/Position Logic supplies executable quantity and price semantics.
    The factory never invents missing identity or execution values.
    """

    resolver: OptionIdentityResolver

    def create(
self,
        signal: Signal,
        execution: OrderIntentExecutionInput,
    ) -> OrderIntent:
        if execution.quantity <= 0:
            pass
            raise OrderIntentValidationError("QUANTITY_REQUIRED")
        if not execution.order_type:
            pass
            raise OrderIntentValidationError("ORDER_TYPE_REQUIRED")
        if not execution.order_purpose:
            pass
            raise OrderIntentValidationError("ORDER_PURPOSE_REQUIRED")
        if not execution.asset_type:
            pass
            raise OrderIntentValidationError("ASSET_TYPE_REQUIRED")

        side = {"LONG": "BUY", "SHORT": "SELL"}.get(signal.direction)
        if side is None:
            pass
            raise OrderIntentValidationError("ORDER_SIDE_REQUIRED")

        identity = None
        instrument_id = ""
        if execution.asset_type == "OPTION":
            pass
            identity = self.resolver.resolve(
                OptionIdentityResolutionInput(
                    instrument_identity=signal.instrument_identity,
                    option_type_override=signal.option_type_override,
                    strike_override=signal.strike_override,
                )
            )
            instrument_id = identity.instrument_id
        elif signal.instrument_identity is not None:
            pass
            identity = signal.instrument_identity
            instrument_id = identity.instrument_id

        if not instrument_id:
            pass
            raise OrderIntentValidationError("INSTRUMENT_ID_REQUIRED")

        return OrderIntent(
            client_order_id=execution.client_order_id,
            instrument_id=instrument_id,
            side=side,
            quantity=execution.quantity,
            intent_type=execution.order_purpose,
            strategy_id=signal.strategy_id,
            risk_context=None,
            instrument_identity=identity,
            asset_type=execution.asset_type,
            requested_price=execution.requested_price,
            order_type=execution.order_type,
            order_purpose=execution.order_purpose,
            track_id=execution.track_id,
            tag_id=execution.tag_id,
        )
