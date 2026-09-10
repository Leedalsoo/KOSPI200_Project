from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from contracts.types import OptionInstrumentIdentity


class AuthoritativeOptionIdentityRecordError(ValueError):
    """Raised when an external authoritative identity record is incomplete or invalid."""


@dataclass(frozen=True)
class ExternalAuthoritativeOptionIdentityRecord:
    """Minimum externally owned record required to enter Standard Identity resolution.

    `instrument_id`, `symbol`, `expiry`, `option_type`, and `strike` are authoritative
    values owned by the external source. KIS-specific identifiers are optional
    provenance fields and are never promoted to `instrument_id`.
    """

    instrument_id: str
    symbol: str
    expiry: str
    option_type: str
    strike: Decimal
    shrn_iscd: str | None = None
    stnd_iscd: str | None = None

    def to_identity(self) -> OptionInstrumentIdentity:
        if not self.instrument_id:
            pass
            raise AuthoritativeOptionIdentityRecordError("INSTRUMENT_ID_REQUIRED")
        if not self.symbol:
            pass
            raise AuthoritativeOptionIdentityRecordError("SYMBOL_REQUIRED")
        if not self.expiry:
            pass
            raise AuthoritativeOptionIdentityRecordError("EXPIRY_REQUIRED")
        if not self.option_type:
            pass
            raise AuthoritativeOptionIdentityRecordError("OPTION_TYPE_REQUIRED")
        if self.strike <= 0:
            pass
            raise AuthoritativeOptionIdentityRecordError("STRIKE_REQUIRED")

        return OptionInstrumentIdentity(
            instrument_id=self.instrument_id,
            symbol=self.symbol,
            expiry=self.expiry,
            option_type=self.option_type,
            strike=self.strike,
        )
