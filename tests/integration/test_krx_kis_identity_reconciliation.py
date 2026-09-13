import pytest

from contracts.krx_kis_identity_reconciliation import IdentityReconciliationError, KisMasterIdentityRecord, KrxInstrumentRecord, reconcile_krx_to_kis


def test_exact_standard_code_match_preserves_kis_execution_code():
    result = reconcile_krx_to_kis(
        [KrxInstrumentRecord("KRX-A", "INDEX FUT", "FUTURES")],
        [KisMasterIdentityRecord("101S12", "KRX-A")],
    )
    assert result[0].kis_shrn_iscd == "101S12"
    assert result[0].matched_by == "KIS_STND_ISCD_EXACT"


def test_no_prefix_or_name_guessing():
    result = reconcile_krx_to_kis(
        [KrxInstrumentRecord("KRX-A", "INDEX FUT", "FUTURES")],
        [KisMasterIdentityRecord("101S12", "OTHER")],
    )
    assert result == ()


def test_ambiguous_standard_code_fails_closed():
    with pytest.raises(IdentityReconciliationError, match="AMBIGUOUS"):
        reconcile_krx_to_kis([], [
            KisMasterIdentityRecord("101S12", "KRX-A"),
            KisMasterIdentityRecord("101S13", "KRX-A"),
        ])
