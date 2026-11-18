from __future__ import annotations

from application.composition.validation_only_option_lineage_auditor import (
    ValidationOnlyOptionLineageAuditor,
)


MASTER_HASH_A = "a" * 64
MASTER_HASH_B = "b" * 64
QUOTE_HASH = "c" * 64
ORDERBOOK_HASH = "d" * 64
ANCHOR_HASH = "e" * 64


def _master():
    return [
        {"symbol": "B01611887", "expiry": "20261112", "option_type": "CALL", "strike": "887.50", "master_sha256": MASTER_HASH_A, "source": "KIS_OFFICIAL_INDEX_MASTER"},
        {"symbol": "B01611887", "expiry": "20261112", "option_type": "CALL", "strike": "887.50", "master_sha256": MASTER_HASH_B, "source": "KIS_OFFICIAL_INDEX_MASTER"},
    ]


def _quote():
    return {
        "record_id": "SYNTHETIC:B01611887:fresh_two_sided",
        "symbol": "B01611887", "expiry": "20261112", "option_type": "CALL", "strike": "887.50",
        "master_sha256": MASTER_HASH_B, "source_timestamp": "2026-11-06T10:00:00+09:00",
        "received_at": "2026-11-06T10:00:00.100000+09:00",
        "provenance": "SYNTHETIC:DERIVED_SCENARIO", "synthetic": True,
        "source_anchor_sha256": ANCHOR_HASH, "dataset_sha256": QUOTE_HASH,
    }


def _orderbook():
    return {
        "record_id": "SYNTHETIC:B01611887:fresh_two_sided",
        "quote_record_id": "SYNTHETIC:B01611887:fresh_two_sided",
        "quote_dataset_sha256": QUOTE_HASH,
        "symbol": "B01611887", "expiry": "20261112", "option_type": "CALL", "strike": "887.50",
        "master_sha256": MASTER_HASH_B, "source_timestamp": "2026-11-06T10:00:00+09:00",
        "received_at": "2026-11-06T10:00:00.100000+09:00",
        "provenance": "SYNTHETIC:DERIVED_SCENARIO", "synthetic": True,
        "source_anchor_sha256": ANCHOR_HASH, "dataset_sha256": ORDERBOOK_HASH,
        "levels": {"bids": [{"price": "42.93", "quantity": "3"}], "asks": [{"price": "43.37", "quantity": "3"}]},
    }


def _execution():
    return {
        "execution_id": "EXEC-000001", "client_order_id": "ORDER-1",
        "instrument_id": "B01611887", "broker_symbol": "B01611887",
        "instrument_identity": {
            "expiry": "20261112", "option_type": "CALL", "strike": "887.50",
            "contract_multiplier": "250000",
            "multiplier_source": "KRX_STANDARD_MULTIPLIER_VALIDATION_ONLY",
        },
        "execution_timestamp": "2026-10-21T00:01:16.106074+00:00",
        "adapter": "S15B_VALIDATION_ONLY_VIRTUAL_BROKER",
        "execution_kind": "VALIDATION_ONLY_VIRTUAL_FILL",
        "validation_only": True,
    }


def _audit(**overrides):
    values = {
        "master_records": _master(),
        "quote_records": [_quote()],
        "orderbook_records": [_orderbook()],
        "execution_records": [_execution()],
        "source_manifest_hashes": {"master": MASTER_HASH_B, "quote": QUOTE_HASH, "orderbook": ORDERBOOK_HASH},
    }
    values.update(overrides)
    return ValidationOnlyOptionLineageAuditor(validation_only=True).audit(**values)


def test_requires_validation_only_opt_in():
    try:
        ValidationOnlyOptionLineageAuditor()
    except ValueError as exc:
        assert str(exc) == "OPTION_LINEAGE_VALIDATION_ONLY_OPT_IN_REQUIRED"
    else:
        raise AssertionError("validation-only opt-in was not required")


def test_exact_identity_crosswalk_links_all_four_stages_without_authority():
    report = _audit()
    assert report["counts"]["quote_identity_matches"] == 1
    assert report["counts"]["orderbook_identity_matches"] == 1
    assert report["counts"]["execution_identity_matches"] == 1
    assert report["chain_judgement"]["contract_identity_linked"] is True
    assert report["chain_judgement"]["quote_to_orderbook_lineage_linked"] is True
    assert report["chain_judgement"]["execution_to_orderbook_direct_linked"] is False
    assert report["chain_judgement"]["real_execution_evidence"] is False
    assert report["chain_judgement"]["authoritative_multiplier_proven"] is False
    assert report["gate_release_permitted"] is False


def test_master_snapshot_hash_variants_preserve_identity_without_collapsing_snapshots():
    report = _audit()
    assert report["master_snapshot_crosswalk"][0]["identity_variants"] == 1
    assert report["master_snapshot_crosswalk"][0]["master_hashes"] == [MASTER_HASH_A, MASTER_HASH_B]


def test_missing_quote_source_time_is_not_replaced_by_received_time():
    quote = _quote()
    quote["source_timestamp"] = None
    report = _audit(quote_records=[quote])
    assert report["quotes"][0]["source_time_status"] == "SOURCE_TIME_MISSING_RECEIVE_ONLY"
    assert report["quotes"][0]["received_at"] is not None


def test_future_quote_source_time_is_reported():
    quote = _quote()
    quote["source_timestamp"] = "2026-11-06T10:00:01+09:00"
    report = _audit(quote_records=[quote])
    assert "QUOTE_SOURCE_AFTER_RECEIVE:SYNTHETIC:B01611887:fresh_two_sided" in report["issues"]


def test_identity_mismatch_does_not_get_hidden_by_matching_symbol():
    quote = _quote()
    quote["strike"] = "890.00"
    report = _audit(quote_records=[quote])
    assert report["quotes"][0]["identity_match"] is False
    assert report["quotes"][0]["master_link"] == "MASTER_CONTRACT_IDENTITY_MISMATCH"


def test_orderbook_requires_explicit_quote_dataset_lineage():
    book = _orderbook()
    book["quote_dataset_sha256"] = "f" * 64
    report = _audit(orderbook_records=[book])
    assert report["orderbooks"][0]["quote_lineage_linked"] is False
    assert any(x.startswith("ORDERBOOK_QUOTE_LINEAGE_MISMATCH:") for x in report["issues"])


def test_one_sided_orderbook_is_not_complete_even_with_master_identity():
    book = _orderbook()
    book["levels"]["asks"] = [{"price": "0.00", "quantity": "0"}]
    report = _audit(orderbook_records=[book])
    assert report["orderbooks"][0]["depth_status"] == "ONE_SIDED_OR_EMPTY"
    assert report["chain_judgement"]["complete_observed_orderbook_available"] is False


def test_validation_only_multiplier_is_not_authoritative():
    report = _audit()
    assert report["executions"][0]["multiplier_status"] == "VALIDATION_ONLY_ASSUMPTION"
    assert report["chain_judgement"]["authoritative_multiplier_proven"] is False


def test_execution_symbol_mismatch_is_reported():
    execution = _execution()
    execution["broker_symbol"] = "C01611887"
    report = _audit(execution_records=[execution])
    assert report["executions"][0]["symbol_match"] is False
    assert "EXECUTION_SYMBOL_MISMATCH:EXEC-000001" in report["issues"]


def test_report_hash_is_deterministic_and_non_mutating():
    kwargs = {
        "master_records": _master(), "quote_records": [_quote()],
        "orderbook_records": [_orderbook()], "execution_records": [_execution()],
        "source_manifest_hashes": {"master": MASTER_HASH_B, "quote": QUOTE_HASH, "orderbook": ORDERBOOK_HASH},
    }
    auditor = ValidationOnlyOptionLineageAuditor(validation_only=True)
    first = auditor.audit(**kwargs)
    second = auditor.audit(**kwargs)
    assert first["report_sha256"] == second["report_sha256"]
    assert first["mutation_applied"] is False
    assert first["authority_claimed"] is False
    assert first["gate_release_permitted"] is False



def test_orderbook_quote_link_requires_matching_anchor_and_generated_time():
    book = _orderbook()
    book["source_anchor_sha256"] = "f" * 64
    report = _audit(orderbook_records=[book])
    assert report["orderbooks"][0]["quote_lineage_linked"] is False


def test_orderbook_execution_reference_without_order_or_execution_link_is_not_direct():
    execution = _execution()
    execution["orderbook_record_id"] = "SYNTHETIC:B01611887:fresh_two_sided"
    report = _audit(execution_records=[execution])
    assert report["executions"][0]["orderbook_lineage_linked"] is False


def test_execution_payload_hash_and_exact_receive_time_link_raw_websocket_orderbook():
    execution = _execution()
    execution["orderbook_evidence_sha256"] = "9" * 64
    execution["execution_timestamp"] = "2026-10-21T00:01:16.106074+00:00"
    raw_book = {
        "record_id": "OBSERVED_WS_ORDERBOOK:B01611887:20261021:3628",
        "symbol": "B01611887", "expiry": "20261112", "option_type": "CALL", "strike": "887.50",
        "master_sha256": MASTER_HASH_B,
        "evidence_sha256": "9" * 64,
        "source_timestamp": None, "source_timestamp_raw": "090115",
        "source_timestamp_candidate": "2026-10-21T09:01:15+09:00",
        "source_timestamp_semantics": "RAW_HHMMSS_CANDIDATE_NOT_PROMOTED_TO_EVENT_TIME",
        "received_at": "2026-10-21T00:01:16.106074+00:00",
        "provenance": "OBSERVED_KIS_VTS:H0IOASP0", "synthetic": False,
        "levels": {"bids": [{"price": "35.00", "quantity": "1"}], "asks": [{"price": "37.65", "quantity": "1"}]},
    }
    report = _audit(orderbook_records=[raw_book], execution_records=[execution])
    result = report["executions"][0]
    assert result["orderbook_lineage_linked"] is True
    assert result["orderbook_link_method"] == "PAYLOAD_SHA256_IDENTITY_AND_EXACT_RECEIVE_TIME"
    assert result["orderbook_linked_record_id"] == raw_book["record_id"]
    assert result["execution_to_orderbook_receive_lag_seconds"] == 0.0
    assert report["chain_judgement"]["real_execution_evidence"] is False
    assert report["gate_release_permitted"] is False


def test_execution_payload_hash_match_with_receive_time_mismatch_is_not_linked():
    execution = _execution()
    execution["orderbook_evidence_sha256"] = "9" * 64
    raw_book = {
        "record_id": "OBSERVED_WS_ORDERBOOK:B01611887:20261021:3628",
        "symbol": "B01611887", "expiry": "20261112", "option_type": "CALL", "strike": "887.50",
        "master_sha256": MASTER_HASH_B, "evidence_sha256": "9" * 64,
        "received_at": "2026-10-21T00:01:17.000000+00:00",
        "provenance": "OBSERVED_KIS_VTS:H0IOASP0", "synthetic": False,
    }
    report = _audit(orderbook_records=[raw_book], execution_records=[execution])
    assert report["executions"][0]["orderbook_lineage_linked"] is False
    assert "EXECUTION_ORDERBOOK_EVIDENCE_TIME_MISMATCH:EXEC-000001" in report["issues"]


def test_18_contract_observed_orderbook_to_synthetic_execution_chain_stays_validation_only():
    contracts = [
        ("B01610A31", "CALL", "1085.0"), ("B01610A32", "CALL", "1090.0"),
        ("B01610A34", "CALL", "1100.0"), ("B01610A39", "CALL", "1087.5"),
        ("B01610A42", "CALL", "1102.5"), ("B01610A43", "CALL", "1105.0"),
        ("C01610A29", "PUT", "1075.0"), ("C01610A30", "PUT", "1080.0"),
        ("C01610A31", "PUT", "1085.0"), ("C01610A32", "PUT", "1090.0"),
        ("C01610A33", "PUT", "1095.0"), ("C01610A34", "PUT", "1100.0"),
        ("C01610A37", "PUT", "1077.5"), ("C01610A38", "PUT", "1082.5"),
        ("C01610A39", "PUT", "1087.5"), ("C01610A40", "PUT", "1092.5"),
        ("C01610A41", "PUT", "1097.5"), ("C01610A43", "PUT", "1105.0"),
    ]
    received_at = "2026-10-01T04:36:46.777810+00:00"
    master_hash = "f" * 64
    dataset_hash = "1" * 64
    masters, quotes, books, executions = [], [], [], []
    import hashlib
    for symbol, right, strike in contracts:
        anchor = hashlib.sha256(f"H0IOASP0|{symbol}".encode()).hexdigest()
        identity = {"symbol": symbol, "expiry": "20261008", "option_type": right, "strike": strike, "master_sha256": master_hash}
        masters.append({**identity, "source": "KRX_OPEN_API_VALIDATION_IDENTITY"})
        quote_id = f"DERIVED_QUOTE:{symbol}"
        quotes.append({
            **identity, "record_id": quote_id, "source_timestamp": None,
            "source_timestamp_raw": "133646", "generated_at": received_at,
            "received_at": received_at, "provenance": "DERIVED:OBSERVED_KIS_H0IOASP0_TOP_OF_BOOK",
            "synthetic": False, "source_anchor_sha256": anchor, "dataset_sha256": dataset_hash,
        })
        books.append({
            **identity, "record_id": f"OBSERVED_ORDERBOOK:{symbol}", "quote_record_id": quote_id,
            "quote_dataset_sha256": dataset_hash, "source_timestamp": None,
            "source_timestamp_raw": "133646", "generated_at": received_at,
            "received_at": received_at, "provenance": "OBSERVED_KIS_VTS:H0IOASP0",
            "synthetic": False, "source_anchor_sha256": anchor, "dataset_sha256": dataset_hash,
            "evidence_sha256": anchor,
            "levels": {"bids": [{"price": "10.00", "quantity": "1"}], "asks": [{"price": "10.05", "quantity": "1"}]},
        })
        executions.append({
            "execution_id": f"VALIDATION_ONLY:SYNTHETIC:{symbol}",
            "client_order_id": f"VALIDATION_ONLY:ORDER:{symbol}",
            "instrument_id": symbol, "broker_symbol": symbol,
            "instrument_identity": {
                "expiry": "20261008", "option_type": right, "strike": strike,
                "contract_multiplier": "250000",
                "multiplier_source": "KRX_STANDARD_MULTIPLIER_VALIDATION_ONLY",
            },
            "master_sha256": master_hash, "execution_timestamp": received_at,
            "adapter": "SYNTHETIC:DERIVED_SCENARIO",
            "execution_kind": "VALIDATION_ONLY_SYNTHETIC_FILL",
            "orderbook_evidence_sha256": anchor, "validation_only": True,
        })
    report = ValidationOnlyOptionLineageAuditor(validation_only=True).audit(
        master_records=masters, quote_records=quotes, orderbook_records=books,
        execution_records=executions,
        source_manifest_hashes={"krx": master_hash, "quote": dataset_hash, "orderbook": dataset_hash},
    )
    assert report["counts"]["quote_identity_matches"] == 18
    assert report["counts"]["orderbook_identity_matches"] == 18
    assert report["counts"]["orderbook_quote_lineage_matches"] == 18
    assert report["counts"]["execution_identity_matches"] == 18
    assert report["counts"]["execution_orderbook_evidence_matches"] == 18
    assert report["chain_judgement"]["real_execution_evidence"] is False
    assert report["chain_judgement"]["authoritative_multiplier_proven"] is False
    assert report["gate_release_permitted"] is False
    assert report["issues"] == []
