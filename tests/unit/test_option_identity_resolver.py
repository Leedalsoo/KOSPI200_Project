from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity
from core.oms.option_identity_resolver import (
IdentityResolutionError,
OptionIdentityResolutionInput,
OptionIdentityResolver,
)


def identity():
    return OptionInstrumentIdentity(
        instrument_id="KOSPI200-202609-C-350.0",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal("350.0"),
    )


def test_resolve_preserves_authoritative_identity():
    result = OptionIdentityResolver().resolve(OptionIdentityResolutionInput(identity()))
    assert result == identity()


def test_resolve_preserves_same_value_overrides():
    result = OptionIdentityResolver().resolve(
        OptionIdentityResolutionInput(identity(), "CALL", Decimal("350.0"))
    )
    assert result == identity()


def test_changed_option_type_override_fails_closed():
    with pytest.raises(IdentityResolutionError, match="AUTHORITATIVE_IDENTITY_REQUIRED_FOR_OPTION_TYPE_OVERRIDE"):
        OptionIdentityResolver().resolve(OptionIdentityResolutionInput(identity(), "PUT"))


def test_changed_strike_override_fails_closed():
    with pytest.raises(IdentityResolutionError, match="AUTHORITATIVE_IDENTITY_REQUIRED_FOR_STRIKE_OVERRIDE"):
        OptionIdentityResolver().resolve(OptionIdentityResolutionInput(identity(), None, Decimal("345.0")))


def test_missing_identity_fails_closed():
    with pytest.raises(IdentityResolutionError, match="OPTION_IDENTITY_REQUIRED"):
        OptionIdentityResolver().resolve(OptionIdentityResolutionInput(None))


def test_missing_expiry_fails_closed():
    bad = OptionInstrumentIdentity("KOSPI200-X-C-350.0", "KOSPI200", None, "CALL", Decimal("350.0"))
    with pytest.raises(IdentityResolutionError, match="EXPIRY_REQUIRED"):
        OptionIdentityResolver().resolve(OptionIdentityResolutionInput(bad))


def test_zero_strike_fails_closed():
    bad = OptionInstrumentIdentity("KOSPI200-X-C-0.0", "KOSPI200", "202609", "CALL", Decimal("0"))
    with pytest.raises(IdentityResolutionError, match="STRIKE_REQUIRED"):
        OptionIdentityResolver().resolve(OptionIdentityResolutionInput(bad))
