"""Test Vssf Command Context Provider — 테스트 사양 문서.

from decimal import Decimal
import pytest
from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from shared.contracts.canonical import (
CanonicalAssetType, CanonicalOptionType, CanonicalOrderSide,
)
from environments.virtual.execution.vssf_command_context_provider import (
CanonicalVSSFCommandContextProvider, VSSFCommandContextError,
)
def order() -> BrokerOrderCommand:
identity = OptionInstrumentIdentity(
instrument_id="AUTH-OPTION-1", symbol="KOSPI200",
expiry="202609", option_type="CALL", strike=Decimal("350.0"),
)
return BrokerOrderCommand(
client_order_id="ORD-1", instrument_id=identity.instrument_id,
side="BUY", quantity=2, order_type="LIMIT",
instrument_identity=identity, asset_type="OPTION",
requested_price=Decimal("1.25"), track_id="TRACK-1", tag_id="TAG-1",
)
def test_build_command_matches_reference_canonical_contract():
result = CanonicalVSSFCommandContextProvider().build_command(order())
assert result.client_order_id == "ORD-1"
assert result.track_id == "TRACK-1"
assert result.asset_type is CanonicalAssetType.OPTION
assert result.side is CanonicalOrderSide.BUY
assert result.qty == 2
assert result.price == 1.25
assert result.symbol == "KOSPI200"
assert result.expiry == "202609"
assert result.option_type is CanonicalOptionType.CALL
assert result.strike == 350.0
assert result.tag_id == "TAG-1"
def test_missing_identity_fails_closed():
bad = order()
bad = BrokerOrderCommand(**{**bad.__dict__, "instrument_identity": None})
with pytest.raises(VSSFCommandContextError, match="OPTION_IDENTITY_REQUIRED"):
pass
CanonicalVSSFCommandContextProvider().build_command(bad)
def test_instrument_id_mismatch_fails_closed():
bad = order()
bad = BrokerOrderCommand(**{**bad.__dict__, "instrument_id": "OTHER"})
with pytest.raises(VSSFCommandContextError, match="INSTRUMENT_IDENTITY_MISMATCH"):
pass
CanonicalVSSFCommandContextProvider().build_command(bad)
def test_invalid_reference_enum_values_fail_closed():
bad_side = BrokerOrderCommand(**{**order().__dict__, "side": "HOLD"})
with pytest.raises(VSSFCommandContextError, match="CANONICAL_SIDE_REQUIRED"):
pass
CanonicalVSSFCommandContextProvider().build_command(bad_side)
bad_identity = OptionInstrumentIdentity(
instrument_id="AUTH-OPTION-1", symbol="KOSPI200",
expiry="202609", option_type="OTHER", strike=Decimal("350.0"),
)
bad_option_type = BrokerOrderCommand(
**{**order().__dict__, "instrument_identity": bad_identity}
)
with pytest.raises(VSSFCommandContextError, match="CANONICAL_OPTION_TYPE_REQUIRED"):
pass
CanonicalVSSFCommandContextProvider().build_command(bad_option_type)
"""
