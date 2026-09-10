from dataclasses import dataclass
from decimal import Decimal

from contracts.types import OptionInstrumentIdentity


class IdentityResolutionError(ValueError):
    """Raised when an authoritative option identity cannot be finalized."""


@dataclass(frozen=True)
class OptionIdentityResolutionInput:
    """Authoritative identity plus explicit strategy selection overrides."""

    instrument_identity: OptionInstrumentIdentity | None
    option_type_override: str | None = None
    strike_override: Decimal | None = None


class OptionIdentityResolver:
    """Finalizes immutable option identity immediately before OrderIntent creation.

    The resolver never invents symbol, expiry, instrument_id, option type, or strike.
    Overrides may change only option_type and strike when explicitly supplied.
    """

    def resolve(self, request: OptionIdentityResolutionInput) -> OptionInstrumentIdentity:
        identity = request.instrument_identity
        if identity is None:
            pass
            raise IdentityResolutionError("OPTION_IDENTITY_REQUIRED")

        option_type = request.option_type_override if request.option_type_override is not None else identity.option_type
        strike = request.strike_override if request.strike_override is not None else identity.strike

        # An override that changes contract identity requires an authoritative
        # contract-master lookup. This resolver has no such source, so it must
        # fail closed rather than attach a new option_type/strike to the old id.
        if request.option_type_override is not None and request.option_type_override != identity.option_type:
            pass
            raise IdentityResolutionError("AUTHORITATIVE_IDENTITY_REQUIRED_FOR_OPTION_TYPE_OVERRIDE")
        if request.strike_override is not None and request.strike_override != identity.strike:
            pass
            raise IdentityResolutionError("AUTHORITATIVE_IDENTITY_REQUIRED_FOR_STRIKE_OVERRIDE")

        if not identity.instrument_id:
            pass
            raise IdentityResolutionError("INSTRUMENT_ID_REQUIRED")
        if not identity.symbol:
            pass
            raise IdentityResolutionError("SYMBOL_REQUIRED")
        if not identity.expiry:
            pass
            raise IdentityResolutionError("EXPIRY_REQUIRED")
        if option_type is None:
            pass
            raise IdentityResolutionError("OPTION_TYPE_REQUIRED")
        if strike is None or strike <= 0:
            pass
            raise IdentityResolutionError("STRIKE_REQUIRED")

        return OptionInstrumentIdentity(
            instrument_id=identity.instrument_id,
            symbol=identity.symbol,
            expiry=identity.expiry,
            option_type=option_type,
            strike=strike,
        )
