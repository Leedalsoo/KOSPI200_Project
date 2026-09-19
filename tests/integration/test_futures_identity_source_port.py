import pytest
from decimal import Decimal

from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesIdentitySourceError, FuturesInstrumentIdentity, require_futures_identity

class Source:
    def current_identity(self):
        return FuturesInstrumentIdentity("FUT-001", "K200", FuturesProductType.STANDARD, Decimal("250000"), "TEST_SOURCE")

def test_explicit_source_preserves_identity_and_multiplier():
    identity = require_futures_identity(Source())
    assert identity.instrument_id == "FUT-001"
    assert identity.symbol == "K200"
    assert identity.product_type is FuturesProductType.STANDARD
    assert identity.contract_multiplier == Decimal("250000")
    assert identity.identity_source == "TEST_SOURCE"

def test_missing_source_fails_closed():
    with pytest.raises(FuturesIdentitySourceError, match="FUTURES_IDENTITY_SOURCE_REQUIRED"):
        require_futures_identity(None)

@pytest.mark.parametrize("args", [
    ("", "K200", FuturesProductType.STANDARD, Decimal("250000"), "TEST"),
    ("FUT-001", "", FuturesProductType.STANDARD, Decimal("250000"), "TEST"),
    ("FUT-001", "K200", FuturesProductType.STANDARD, Decimal("0"), "TEST"),
    ("FUT-001", "K200", FuturesProductType.STANDARD, Decimal("250000"), ""),
])
def test_identity_rejects_missing_authoritative_fields(args):
    with pytest.raises(FuturesIdentitySourceError):
        FuturesInstrumentIdentity(*args)
