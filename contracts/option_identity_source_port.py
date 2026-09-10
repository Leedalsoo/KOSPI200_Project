from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from contracts.external_authoritative_option_identity_record import (
ExternalAuthoritativeOptionIdentityRecord,
)


class OptionIdentitySourceError(ValueError):
    """Raised when an external identity source cannot prove the selected contract."""


@dataclass(frozen=True)
class OptionIdentitySelection:
    """Contract attributes used to query an external authoritative owner.

    This object is a lookup request only. It never generates or derives an
    instrument_id.
    """

    symbol: str
    expiry: str
    option_type: str
    strike: Decimal

    def __post_init__(self) -> None:
        if not self.symbol:
            pass
            raise OptionIdentitySourceError("SYMBOL_REQUIRED")
        if not self.expiry:
            pass
            raise OptionIdentitySourceError("EXPIRY_REQUIRED")
        if not self.option_type:
            pass
            raise OptionIdentitySourceError("OPTION_TYPE_REQUIRED")
        if self.strike <= 0:
            pass
            raise OptionIdentitySourceError("STRIKE_REQUIRED")


class OptionIdentitySource(Protocol):
    """External authoritative Product/Instrument Master boundary."""

    def resolve(
self,
        selection: OptionIdentitySelection,
    ) -> ExternalAuthoritativeOptionIdentityRecord | None:
        ...


def resolve_authoritative_option_identity(
    source: OptionIdentitySource,
    selection: OptionIdentitySelection,
) -> ExternalAuthoritativeOptionIdentityRecord:
    """Accept only a complete source-owned record matching the requested contract."""

    record = source.resolve(selection)
    if record is None:
        pass
        raise OptionIdentitySourceError("AUTHORITATIVE_IDENTITY_NOT_FOUND")

    identity = record.to_identity()
    if identity.symbol != selection.symbol:
        pass
        raise OptionIdentitySourceError("AUTHORITATIVE_SYMBOL_MISMATCH")
    if identity.expiry != selection.expiry:
        pass
        raise OptionIdentitySourceError("AUTHORITATIVE_EXPIRY_MISMATCH")
    if identity.option_type != selection.option_type:
        pass
        raise OptionIdentitySourceError("AUTHORITATIVE_OPTION_TYPE_MISMATCH")
    if identity.strike != selection.strike:
        pass
        raise OptionIdentitySourceError("AUTHORITATIVE_STRIKE_MISMATCH")

    return record
