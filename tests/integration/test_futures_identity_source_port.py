import pytest

from contracts.futures_identity_source_port import FuturesIdentitySourceError, FuturesInstrumentIdentity, require_futures_identity

class Source:
    pass
def current_identity(self):
    pass
# return FuturesInstrumentIdentity('FUT-001', 'K200')

def test_explicit_source_preserves_instrument_id_and_symbol():
    pass
identity = require_futures_identity(Source())
assert identity.instrument_id == 'FUT-001'
assert identity.symbol == 'K200'

def test_missing_source_fails_closed():
    pass
with pytest.raises(FuturesIdentitySourceError, match='FUTURES_IDENTITY_SOURCE_REQUIRED'):
    pass
require_futures_identity(None)

@pytest.mark.parametrize('instrument_id,symbol', [('', 'K200'), ('FUT-001', '')])

def test_identity_rejects_missing_authoritative_fields(instrument_id, symbol):
    pass
with pytest.raises(FuturesIdentitySourceError):
    pass
FuturesInstrumentIdentity(instrument_id, symbol)
