from copy import deepcopy
import pytest

from application.composition.validation_only_contract_inventory_crosswalk_auditor import (
    ValidationOnlyContractInventoryCrosswalkAuditor as Auditor,
)

GOOD = "a" * 64
MASTER = {
    "type_code": "5", "name": "C 202611 1000.0", "strike": "01000.00", "underlying": "2001"
}
KRX = {"B01611A00": [{"side": "CALL", "month": "202611", "strike": "1000.0"}]}


def inputs():
    return {
        "master_snapshots": [
            {"manifest_file": "master.json", "market_date_kst": "20261014", "archive_sha256": GOOD,
             "actual_archive_sha256": GOOD, "fetched_at_utc": "2026-10-14T00:00:00+00:00", "row_count": 10},
            {"manifest_file": "legacy.json", "market_date_kst": None, "archive_sha256": GOOD,
             "actual_archive_sha256": GOOD, "legacy_alias": True, "fetched_at_utc": "2026-10-13T15:00:00+00:00"},
        ],
        "expiry_records": [{
            "symbol": "B01611A00", "expiry": "20261112", "side": "CALL", "strike": "1000.00",
            "master_sha256": GOOD, "master_code_found": True, "master_row": MASTER,
            "requested_at": "2026-10-14T00:01:00+00:00", "received_at": "2026-10-14T00:01:01+00:00",
            "response_hash_valid": True, "file_hash_valid": True, "http_rt_ok": True,
            "response_expiry": "20261112",
        }],
        "krx_crosswalk": KRX,
        "rest_contracts": [{
            "symbol": "B01611A00", "side": "CALL", "month": "202611", "strike": "1000.00",
            "expiry": "20261112", "row_count": 2, "trading_dates": ["20261012"],
            "request_response_mismatch_count": 0, "master_postdate_sha256": GOOD,
            "master_postdate_row": MASTER, "postdate_master_market_date": "20261014",
        }],
        "websocket_days": [{
            "trading_date": "20261012", "raw_frame_count": 2, "tr_counts": {"H0IOCNT0": 2},
            "h0iocnt0_frames": 2, "parsed_58_field_records": 2,
            "symbols": [{"symbol": "B01611A00", "side": "CALL", "month": "202611", "strike": "1000.00",
                         "master_postdate_row": MASTER}],
            "master_postdate_match_count": 1, "event_time_future_vs_received": 0,
            "source_time_metrics": {"count": 2},
        }],
        "websocket_orderbook": {"frames": 1, "symbols": []},
        "time_alignment": {
            "rest": {"rows": 2, "valid_source_time_rows": 2, "missing_or_zero_source_time_rows": 0,
                     "negative_lag_rows": 0, "median_lag_seconds": 1.0},
            "h0iocnt0": {"parsed_records": 2, "valid_source_time_records": 2, "future_vs_received": 0},
        },
        "source_hashes": {"master.zip": GOOD, "rest.jsonl": "b" * 64},
        "krx_inventory": {"supported_kis_codes": 7144, "source_rows": 14288, "unique_isu_codes": 7144},
    }


def audit(data):
    return Auditor(validation_only=True).audit(**data)


def test_crosswalks_master_expiry_rest_and_websocket_identity():
    report = audit(inputs())
    assert report["expiry_cache_crosswalk"]["exact_master_identity_matches"] == 1
    assert report["rest_contract_crosswalk"]["krx_identity_matches"] == 1
    assert report["rest_contract_crosswalk"]["postdate_master_identity_matches"] == 1
    assert report["websocket_contract_crosswalk"]["krx_identity_matches"] == 1
    assert report["websocket_contract_crosswalk"]["postdate_master_identity_matches"] == 1
    assert report["issues"] == []
    assert report["gate_release_permitted"] is False
    assert report["authority_claimed"] is False


def test_weekly_expiry_uses_master_week_label_and_exact_weekday():
    row = {"type_code": "L", "name": "Weekly C 2610W3 885.0", "strike": "885.00", "underlying": "2001"}
    assert Auditor._master_expiry_label_matches(row, "20261015") is True
    assert Auditor._master_expiry_label_matches(row, "20261022") is False


def test_wrong_weekly_expiry_and_master_identity_are_not_accepted():
    data = inputs()
    data["expiry_records"][0]["master_row"] = {
        "type_code": "L", "name": "Weekly C 2610W3 1000.0", "strike": "1000", "underlying": "2001"
    }
    report = audit(data)
    assert any(x.startswith("EXPIRY_EVIDENCE_MISMATCH") for x in report["issues"])


def test_expired_contract_missing_from_later_master_is_classified_not_blocked():
    data = inputs()
    row = data["rest_contracts"][0]
    row.update({"symbol": "B01610A00", "month": "202610", "expiry": "20261008",
                "master_postdate_row": {}, "master_postdate_sha256": "", "postdate_master_market_date": "20261014"})
    data["krx_crosswalk"]["B01610A00"] = [{"side": "CALL", "month": "202610", "strike": "1000"}]
    report = audit(data)
    result = report["rest_contract_crosswalk"]["contracts"][0]
    assert result["krx_crosswalk_match"] is True
    assert result["postdate_master_absence_expected_after_expiry"] is True
    assert not any(x.startswith("REST_CONTRACT_IDENTITY_MISMATCH") for x in report["issues"])


def test_rest_identity_mismatch_is_reported():
    data = inputs()
    data["rest_contracts"][0]["request_response_mismatch_count"] = 1
    report = audit(data)
    assert any(x.startswith("REST_CONTRACT_IDENTITY_MISMATCH") for x in report["issues"])


def test_websocket_krx_gap_is_reported_without_authority_promotion():
    data = inputs()
    data["websocket_days"][0]["symbols"][0]["strike"] = "1005"
    report = audit(data)
    assert any(x.startswith("WEBSOCKET_KRX_CROSSWALK_GAP") for x in report["issues"])
    assert report["authority_claimed"] is False


def test_source_time_coverage_and_future_event_are_checked_without_threshold():
    data = inputs()
    data["time_alignment"]["rest"]["valid_source_time_rows"] = 1
    data["time_alignment"]["h0iocnt0"]["future_vs_received"] = 1
    report = audit(data)
    assert "REST_SOURCE_TIME_COVERAGE_COUNT_MISMATCH" in report["issues"]
    assert "SOURCE_EVENT_TIME_AFTER_RECEIVE" in report["issues"]


def test_expiry_and_rest_nonoverlap_is_separate_evidence_subset_not_conflict():
    data = inputs()
    data["expiry_records"][0]["symbol"] = "B01611750"
    data["expiry_records"][0]["expiry"] = "20261112"
    data["expiry_records"][0]["strike"] = "750.00"
    data["expiry_records"][0]["master_row"] = {"type_code": "5", "name": "C 202611 750.0", "strike": "750.00", "underlying": "2001"}
    report = audit(data)
    assert report["cross_universe_comparison"]["classification"] == "SEPARATE_EVIDENCE_SUBSETS_NOT_IDENTITY_CONFLICT"


def test_report_is_deterministic_and_does_not_mutate_inputs():
    data = inputs()
    before = deepcopy(data)
    a, b = audit(data), audit(data)
    assert a["report_sha256"] == b["report_sha256"]
    assert data == before
    assert a["synthetic_data_used"] is False
    assert a["mutation_applied"] is False


def test_validation_only_opt_in_is_required():
    with pytest.raises(ValueError, match="CONTRACT_INVENTORY_VALIDATION_ONLY_OPT_IN_REQUIRED"):
        Auditor()


def test_synthetic_expiry_requires_rest_series_anchor_krx_hash_and_validation_namespace():
    data = inputs()
    data["rest_contracts"][0]["symbol"] = "B01610A00"
    data["rest_contracts"][0]["month"] = "202610"
    data["rest_contracts"][0]["expiry"] = "20261008"
    data["rest_contracts"][0]["master_postdate_row"] = {}
    data["rest_contracts"][0]["master_postdate_sha256"] = ""
    data["rest_contracts"][0]["postdate_master_market_date"] = "20261014"
    data["krx_crosswalk"]["B01610A00"] = [{"side": "CALL", "month": "202610", "strike": "1000"}]
    data["source_hashes"].update({"rest_raw/20261001": "c" * 64, "rest_day_manifest/20261001": "f" * 64, "krx_options_daily": "d" * 64})
    synthetic = {
        "record_id": "SYNTHETIC_CONTRACT:B01610A01:20261008",
        "symbol": "B01610A01", "side": "CALL", "month": "202610", "strike": "1002.5",
        "expiry": "20261008", "source_namespace": "SYNTHETIC:DERIVED_SCENARIO",
        "source_anchor_type": "KIS_REST:futs_last_tr_date",
        "source_anchor_series_key": "KOSPI200_STANDARD_MONTHLY:202610",
        "target_series_key": "KOSPI200_STANDARD_MONTHLY:202610",
        "source_anchor_expiry": "20261008", "source_anchor_symbols": ["B01610A00"],
        "source_anchor_contract_count": 1,
        "source_anchor_sha256": "c" * 64, "source_anchor_manifest_sha256": "f" * 64,
        "krx_reference_sha256": "d" * 64, "krx_isu_codes": ["B016A001"],
        "krx_product_name": "KOSPI200 options",
        "source_anchor_received_at": "2026-10-01T06:00:00+00:00",
        "generated_at": "2026-11-18T00:00:00+09:00",
        "deterministic_rule": "SAME_KOSPI200_STANDARD_MONTHLY_SERIES_AND_MONTH_USE_REST_EXPIRY_ANCHOR",
        "validation_only": True, "authoritative": False, "master_postdate_row": {},
        "source_event_time": None, "quote_generated_at": None,
    }
    synthetic["record_sha256"] = Auditor._hash(synthetic)
    data["krx_crosswalk"]["B01610A01"] = [{"side": "CALL", "month": "202610", "strike": "1002.5"}]
    data["synthetic_expiry_assignments"] = [synthetic]
    report = audit(data)
    assert report["synthetic_validation_expiry_assignments"]["count"] == 1
    assert report["synthetic_data_used"] is True
    assert report["synthetic_validation_expiry_assignments"]["records"][0]["validation_only"] is True
    assert report["synthetic_validation_expiry_assignments"]["records"][0]["authoritative"] is False
    assert not any(x.startswith("SYNTHETIC_EXPIRY_PROVENANCE_INVALID") for x in report["issues"])


def test_synthetic_expiry_cannot_use_future_anchor_or_unverified_namespace():
    data = inputs()
    data["source_hashes"].update({"rest_raw/20261001": "c" * 64, "rest_day_manifest/20261001": "f" * 64, "krx_options_daily": "d" * 64})
    data["synthetic_expiry_assignments"] = [{
        "symbol": "B01611A01", "side": "CALL", "month": "202611", "strike": "1002.5",
        "expiry": "20261112", "source_namespace": "UNVERIFIED", "source_anchor_expiry": "20261112",
        "source_anchor_symbols": ["B01611A00"], "source_anchor_sha256": "c" * 64,
        "krx_reference_sha256": "d" * 64, "source_anchor_received_at": "2026-11-19T00:00:00+09:00",
        "generated_at": "2026-11-18T00:00:00+09:00", "deterministic_rule": "rule",
        "validation_only": True, "authoritative": False,
    }]
    report = audit(data)
    assert any(x.startswith("SYNTHETIC_EXPIRY_PROVENANCE_INVALID") for x in report["issues"])
