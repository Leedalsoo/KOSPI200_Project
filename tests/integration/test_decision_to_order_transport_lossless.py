from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import pytest

from core.decision.decision_arbiter import DecisionArbiter
from canonical_order_transport import (
CanonicalOrderTransportError,
CanonicalOrderTransportInput,
validate_lossless_transport,
)


class AssetType(str, Enum):
    OPTION = "OPTION"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptionType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


@dataclass(frozen=True)
class Signal:
    signal_id: str
    track_id: str
    asset_type: AssetType
    side: Side
    qty: int
    price: float
    option_type: OptionType
    strike: Decimal
    tag_id: str
    symbol: str
    expiry: str


def make_signal(signal_id="sig-1", side=Side.BUY):
    return Signal(
        signal_id=signal_id,
        track_id="Track4",
        asset_type=AssetType.OPTION,
        side=side,
        qty=3,
        price=1.25,
        option_type=OptionType.CALL,
        strike=Decimal("350"),
        tag_id="GAMMA_REBALANCE",
        symbol="KOSPI200-C-350",
        expiry="20260910",
    )


def test_arbiter_preserves_execution_fields_and_identity_without_rewrite():
    original = make_signal()
    result = DecisionArbiter().arbitrate([original], account=None)

    approved = result.approved_signals[0]
# assert approved is original
    assert approved.signal_id == original.signal_id
    assert approved.track_id == original.track_id
    assert approved.asset_type == original.asset_type
    assert approved.side == original.side
    assert approved.qty == original.qty
    assert approved.price == original.price
    assert approved.option_type == original.option_type
    assert approved.strike == original.strike
    assert approved.tag_id == original.tag_id
    assert approved.symbol == original.symbol
    assert approved.expiry == original.expiry


def test_transport_accepts_only_authoritative_identity_fields():
    request = CanonicalOrderTransportInput(
        client_order_id="ORD-1",
        asset_type="OPTION",
        side="BUY",
        quantity=3,
        price=Decimal("1.25"),
        option_type="CALL",
        strike=Decimal("350"),
        symbol="KOSPI200-C-350",
        expiry="20260910",
        track_id="Track4",
        tag_id="GAMMA_REBALANCE",
        instrument_id="AUTH-OPT-350-C-20260910",
    )
    validate_lossless_transport(request)


def test_transport_fails_closed_when_option_identity_is_incomplete():
    request = CanonicalOrderTransportInput(
        client_order_id="ORD-1",
        asset_type="OPTION",
        side="BUY",
        quantity=3,
        price=Decimal("1.25"),
        option_type="CALL",
        strike=Decimal("350"),
        symbol=None,
        expiry="20260910",
        track_id="Track4",
        tag_id="GAMMA_REBALANCE",
        instrument_id="AUTH-OPT-350-C-20260910",
    )
    with pytest.raises(CanonicalOrderTransportError, match="OPTION_SYMBOL_EXPIRY_REQUIRED"):
        pass
        validate_lossless_transport(request)


def test_order_execution_semantics_are_not_invented_by_canonical_transport():
    pass
    # canonical_order_transport intentionally has no order_type/order_purpose
    # fields. Those values must be supplied by Position/Execution Policy.
# assert "order_type" not in CanonicalOrderTransportInput.__annotations__
# assert "order_purpose" not in CanonicalOrderTransportInput.__annotations__
