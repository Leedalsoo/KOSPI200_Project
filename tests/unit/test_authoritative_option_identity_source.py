from dataclasses import dataclass
from decimal import Decimal

from contracts.authoritative_option_identity_source import AuthoritativeOptionIdentitySource
from contracts.types import OptionInstrumentIdentity


@dataclass
class FixtureAuthoritativeSource:
    identity: OptionInstrumentIdentity | None

    def get_identity(self, selector: object) -> OptionInstrumentIdentity | None:
        return self.identity


def _identity() -> OptionInstrumentIdentity:
    return OptionInstrumentIdentity(
        instrument_id="AUTH-OPTION-1",
        symbol="101V3000",
        expiry="2026-12-10",
        option_type="CALL",
        strike=Decimal("300"),
    )


def test_source_returns_complete_authoritative_identity() -> None:
    source: AuthoritativeOptionIdentitySource = FixtureAuthoritativeSource(_identity())
    result = source.get_identity("fixture-selector")
    assert result == _identity()
    assert result.instrument_id == "AUTH-OPTION-1"


def test_source_may_return_none_when_unresolved() -> None:
    source: AuthoritativeOptionIdentitySource = FixtureAuthoritativeSource(None)
    assert source.get_identity("missing-selector") is None


def test_source_contract_does_not_synthesize_identity() -> None:
    source: AuthoritativeOptionIdentitySource = FixtureAuthoritativeSource(None)
    result = source.get_identity({"shrn_iscd": "101V3000"})
    assert result is None
