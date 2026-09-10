from decimal import Decimal

import pytest

from contracts.external_authoritative_option_identity_record import (
AuthoritativeOptionIdentityRecordError,
ExternalAuthoritativeOptionIdentityRecord,
)


def _record() -> ExternalAuthoritativeOptionIdentityRecord:
    return ExternalAuthoritativeOptionIdentityRecord(
        instrument_id="AUTH-OPTION-1",
        symbol="101V3000",
        expiry="2026-12-10",
        option_type="CALL",
        strike=Decimal("300"),
        shrn_iscd="101V3000",
        stnd_iscd="KR4101V300000000000",
    )


def test_complete_external_record_builds_standard_identity() -> None:
    identity = _record().to_identity()
    assert identity.instrument_id == "AUTH-OPTION-1"
    assert identity.symbol == "101V3000"
    assert identity.expiry == "2026-12-10"
    assert identity.option_type == "CALL"
    assert identity.strike == Decimal("300")


def test_kis_identifiers_are_not_promoted_to_instrument_id() -> None:
    record = _record()
    assert record.shrn_iscd != record.instrument_id
    assert record.stnd_iscd != record.instrument_id
    assert record.to_identity().instrument_id == "AUTH-OPTION-1"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("instrument_id", "", "INSTRUMENT_ID_REQUIRED"),
        ("symbol", "", "SYMBOL_REQUIRED"),
        ("expiry", "", "EXPIRY_REQUIRED"),
        ("option_type", "", "OPTION_TYPE_REQUIRED"),
        ("strike", Decimal("0"), "STRIKE_REQUIRED"),
    ],
)
def test_incomplete_record_fails_closed(field: str, value: object, error: str) -> None:
    values = _record().__dict__.copy()
    values[field] = value
    record = ExternalAuthoritativeOptionIdentityRecord(**values)
    with pytest.raises(AuthoritativeOptionIdentityRecordError, match=error):
        pass
record.to_identity()
