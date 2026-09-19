import pytest

from contracts.krx_kis_identity_reconciliation import (
    IdentityReconciliationError,
    KisMasterIdentityRecord,
    KrxInstrumentRecord,
    derive_kis_shrn_iscd,
    reconcile_krx_to_kis_short_code,
)


def test_futures_month_letter_maps_to_kis_short_code():
    assert derive_kis_shrn_iscd("A056A000") == "A05610"
    assert derive_kis_shrn_iscd("A016C000") == "A01612"


def test_option_month_letter_preserves_call_put_code_family_and_strike():
    assert derive_kis_shrn_iscd("B056A752") == "B05610752"
    assert derive_kis_shrn_iscd("C056A752") == "C05610752"


def test_invalid_krx_code_fails_closed():
    with pytest.raises(IdentityReconciliationError, match="UNSUPPORTED_KRX_CODE_FORMAT"):
        derive_kis_shrn_iscd("not-a-code")


def test_short_code_reconciliation_requires_authoritative_kis_record():
    result = reconcile_krx_to_kis_short_code(
        [KrxInstrumentRecord("A056A000", "MINI FUT 202610", "FUTURES")],
        [KisMasterIdentityRecord("A05610", "KR4A056A0007")],
    )
    assert result[0].kis_shrn_iscd == "A05610"
    assert result[0].kis_stnd_iscd == "KR4A056A0007"
    assert result[0].matched_by == "KRX_CODE_MONTH_ENCODING_TO_KIS_SHRN_ISCD"


def test_invalid_krx_code_fails_closed():
    with pytest.raises(IdentityReconciliationError, match="UNSUPPORTED_KRX_CODE_FORMAT"):
        derive_kis_shrn_iscd("not-a-code")
