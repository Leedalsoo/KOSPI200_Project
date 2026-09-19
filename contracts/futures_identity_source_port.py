from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from contracts.futures_contract_spec import FuturesProductType


class FuturesIdentitySourceError(ValueError):
    pass


@dataclass(frozen=True)
class FuturesInstrumentIdentity:
    instrument_id: str
    symbol: str
    product_type: FuturesProductType
    contract_multiplier: Decimal
    identity_source: str

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise FuturesIdentitySourceError("FUTURES_INSTRUMENT_ID_REQUIRED")
        if not self.symbol.strip():
            raise FuturesIdentitySourceError("FUTURES_SYMBOL_REQUIRED")
        if self.contract_multiplier <= 0:
            raise FuturesIdentitySourceError("FUTURES_CONTRACT_MULTIPLIER_REQUIRED")
        if not self.identity_source.strip():
            raise FuturesIdentitySourceError("FUTURES_IDENTITY_SOURCE_REQUIRED")


class FuturesIdentitySourcePort(Protocol):
    def current_identity(self) -> FuturesInstrumentIdentity: ...


def require_futures_identity(source: FuturesIdentitySourcePort | None) -> FuturesInstrumentIdentity:
    if source is None:
        raise FuturesIdentitySourceError("FUTURES_IDENTITY_SOURCE_REQUIRED")
    identity = source.current_identity()
    if not isinstance(identity, FuturesInstrumentIdentity):
        raise FuturesIdentitySourceError("FUTURES_IDENTITY_TYPE_REQUIRED")
    return identity
