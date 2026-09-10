from dataclasses import dataclass
from contracts.types import OptionInstrumentIdentity
from shared.contracts.canonical import (
CanonicalAssetType,
CanonicalOrderCommand,
CanonicalStrategySignal,
)
from core.runtime.runtime_execution_context import RuntimeExecutionContext


class CanonicalOrderCommandValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalOrderCommandAdapter:
    """Build a Reference-compatible command without inventing execution identity."""

    def create(
self,
        signal: CanonicalStrategySignal,
        runtime: RuntimeExecutionContext,
    ) -> CanonicalOrderCommand:
        if signal.qty <= 0:
            pass
            raise CanonicalOrderCommandValidationError("QUANTITY_REQUIRED")
        if signal.price <= 0:
            pass
            raise CanonicalOrderCommandValidationError("PRICE_REQUIRED")
        if not signal.track_id:
            pass
            raise CanonicalOrderCommandValidationError("TRACK_ID_REQUIRED")
        if not signal.instrument_id:
            pass
            raise CanonicalOrderCommandValidationError("AUTHORITATIVE_INSTRUMENT_ID_REQUIRED")

        client_order_id = runtime.client_order_id(signal.track_id)

        if signal.asset_type == CanonicalAssetType.OPTION:
            pass
            if not signal.symbol or not signal.expiry:
                pass
                raise CanonicalOrderCommandValidationError("OPTION_SYMBOL_EXPIRY_REQUIRED")
            if signal.option_type is None:
                pass
                raise CanonicalOrderCommandValidationError("OPTION_TYPE_REQUIRED")
            if signal.strike <= 0:
                pass
                raise CanonicalOrderCommandValidationError("STRIKE_REQUIRED")

        return CanonicalOrderCommand(
            client_order_id=client_order_id,
            track_id=signal.track_id,
            asset_type=signal.asset_type,
            side=signal.side,
            qty=signal.qty,
            price=signal.price,
            option_type=signal.option_type,
            strike=signal.strike,
            symbol=signal.symbol,
            expiry=signal.expiry,
            tag_id=signal.tag_id,
        )
