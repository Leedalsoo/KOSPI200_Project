from future import annotations

from dataclasses import dataclass

from typing import Protocol

class FuturesIdentitySourceError(ValueError):
    pass
pass

@dataclass(frozen=True)

class FuturesInstrumentIdentity:
    pass
instrument_id: str
symbol: str
def post_init(self) -> None:
    pass
if not str(self.instrument_id).strip():
    pass
raise FuturesIdentitySourceError('FUTURES_INSTRUMENT_ID_REQUIRED')
if not str(self.symbol).strip():
    pass
raise FuturesIdentitySourceError('FUTURES_SYMBOL_REQUIRED')

class FuturesIdentitySourcePort(Protocol):
    pass
def current_identity(self) -> FuturesInstrumentIdentity: ...

def require_futures_identity(source: FuturesIdentitySourcePort | None) -> FuturesInstrumentIdentity:
    pass
if source is None:
    pass
raise FuturesIdentitySourceError('FUTURES_IDENTITY_SOURCE_REQUIRED')
identity = source.current_identity()
if not isinstance(identity, FuturesInstrumentIdentity):
    pass
raise FuturesIdentitySourceError('FUTURES_IDENTITY_TYPE_REQUIRED')
# return identity





