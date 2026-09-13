import pytest

from contracts.futures_identity_source_port import (
    FuturesIdentitySourceError,
    FuturesInstrumentIdentity,
    require_futures_identity,
)


class Source:
    def current_identity(self):
        return FuturesInstrumentIdentity("FUT-001", "K200")


def test_explicit_source_preserves_instrument_id_and_symbol():
    identity = require_futures_identity(Source())
    assert identity.instrument_id == "FUT-001"
    assert identity.symbol == "K200"


def test_missing_source_fails_closed():
    with pytest.raises(FuturesIdentitySourceError, match="FUTURES_IDENTITY_SOURCE_REQUIRED"):
        require_futures_identity(None)


@pytest.mark.parametrize("instrument_id,symbol", [("", "K200"), ("FUT-001", "")])
def test_identity_rejects_missing_authoritative_fields(instrument_id, symbol):
    with pytest.raises(FuturesIdentitySourceError):
        FuturesInstrumentIdentity(instrument_id, symbol)
