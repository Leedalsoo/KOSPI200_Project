from dataclasses import dataclass
from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
from decimal import Decimal


class CanonicalOrderTransportError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalOrderTransportInput:
    client_order_id: str
    asset_type: str
    side: str
    quantity: int
    price: Decimal
    option_type: str | None
    strike: Decimal | None
    symbol: str | None
    expiry: str | None
    track_id: str | None
    tag_id: str | None
    instrument_id: str | None


def validate_lossless_transport(request: CanonicalOrderTransportInput) -> None:
    if not request.client_order_id:
        raise CanonicalOrderTransportError("CLIENT_ORDER_ID_REQUIRED")
    if request.quantity <= 0:
        raise CanonicalOrderTransportError("QUANTITY_REQUIRED")
    if request.asset_type not in {"OPTION", "FUTURES"}:
        raise CanonicalOrderTransportError("ASSET_TYPE_REQUIRED")
    if not request.instrument_id:
        raise CanonicalOrderTransportError("AUTHORITATIVE_INSTRUMENT_ID_REQUIRED")

    if request.asset_type == "OPTION":
        if not request.symbol or not request.expiry:
            raise CanonicalOrderTransportError("OPTION_SYMBOL_EXPIRY_REQUIRED")
        try:
            require_exact_option_expiry(request.expiry)
        except CanonicalOptionExpiryError as exc:
            raise CanonicalOrderTransportError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc
        if request.option_type not in {"CALL", "PUT"}:
            raise CanonicalOrderTransportError("OPTION_TYPE_REQUIRED")
        if request.strike is None:
            raise CanonicalOrderTransportError("STRIKE_REQUIRED")
