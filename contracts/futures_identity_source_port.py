from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class FuturesIdentitySourceError(ValueError):
    pass


@dataclass(frozen=True)
class FuturesInstrumentIdentity:
    instrument_id: str
    symbol: str

    def __post_init__(self) -> None:
        if not str(self.instrument_id).strip():
            raise FuturesIdentitySourceError("FUTURES_INSTRUMENT_ID_REQUIRED")
        if not str(self.symbol).strip():
            raise FuturesIdentitySourceError("FUTURES_SYMBOL_REQUIRED")


class FuturesIdentitySourcePort(Protocol):
    def current_identity(self) -> FuturesInstrumentIdentity: ...


def require_futures_identity(source: FuturesIdentitySourcePort | None) -> FuturesInstrumentIdentity:
    if source is None:
        raise FuturesIdentitySourceError("FUTURES_IDENTITY_SOURCE_REQUIRED")
    identity = source.current_identity()
    if not isinstance(identity, FuturesInstrumentIdentity):
        raise FuturesIdentitySourceError("FUTURES_IDENTITY_TYPE_REQUIRED")
    return identity
