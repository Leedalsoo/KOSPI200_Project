from application.composition.validation_only_rest_ws_orderbook_alignment_auditor import ValidationOnlyRestWsOrderBookAlignmentAuditor


def _audit(rest, books):
    return ValidationOnlyRestWsOrderBookAlignmentAuditor(validation_only=True).audit(
        rest_records=rest, orderbook_records=books, source_manifest_hashes={"fixture": "a" * 64}
    )


def test_exact_and_nearest_prior_are_distinguished_without_freshness_cutoff():
    report = _audit(
        [
            {"symbol": "OPT1", "record_id": "R1", "source_timestamp": "2026-10-01T09:00:00+09:00", "collected_at": "2026-10-01T09:00:01+09:00"},
            {"symbol": "OPT1", "record_id": "R2", "source_timestamp": "2026-10-01T09:01:00+09:00", "collected_at": "2026-10-01T09:01:02+09:00"},
        ],
        [
            {"symbol": "OPT1", "record_id": "W1", "source_timestamp_candidate": "2026-10-01T09:00:00+09:00", "received_at": "2026-10-01T09:00:00.1+09:00"},
            {"symbol": "OPT1", "record_id": "W2", "source_timestamp_candidate": "2026-10-01T09:00:30+09:00", "received_at": "2026-10-01T09:00:30.1+09:00"},
        ],
    )
    assert report["counts"]["exact_same_time"] == 1
    assert report["counts"]["nearest_prior"] == 1
    assert report["alignments"][1]["anchor_record_id"] == "R1"
    assert report["alignments"][1]["anchor_age_seconds"] == 30
    assert report["freshness_threshold_applied"] is False
    assert report["gate_release_permitted"] is False


def test_future_only_and_no_rest_are_classified_separately():
    report = _audit(
        [{"symbol": "OPT1", "record_id": "R1", "source_timestamp": "2026-10-01T09:01:00+09:00", "collected_at": "2026-10-01T09:01:01+09:00"}],
        [
            {"symbol": "OPT1", "record_id": "W1", "source_timestamp_candidate": "2026-10-01T09:00:00+09:00", "received_at": "2026-10-01T09:00:01+09:00"},
            {"symbol": "OPT2", "record_id": "W2", "source_timestamp_candidate": "2026-10-01T09:00:00+09:00", "received_at": "2026-10-01T09:00:01+09:00"},
        ],
    )
    assert report["counts"]["future_only"] == 1
    assert report["counts"]["no_rest_source_time"] == 1


def test_future_source_and_timezone_naive_inputs_are_not_silently_accepted():
    report = _audit(
        [{"symbol": "OPT1", "record_id": "R1", "source_timestamp": "2026-10-01T09:00:00+09:00", "collected_at": "2026-10-01T08:59:59+09:00"}],
        [{"symbol": "OPT1", "record_id": "W1", "source_timestamp_candidate": "2026-10-01T09:00:00+09:00", "received_at": "2026-10-01T09:00:01+09:00"}],
    )
    assert "REST_SOURCE_AFTER_COLLECTED:R1" in report["issues"]
    try:
        _audit([{"symbol": "OPT1", "source_timestamp": "2026-10-01T09:00:00", "collected_at": None}], [])
    except ValueError as exc:
        assert "TIMEZONE_REQUIRED" in str(exc)
    else:
        raise AssertionError("timezone-naive REST source time must be rejected")


def test_identical_inputs_produce_identical_report_hash():
    args = (
        [{"symbol": "OPT1", "record_id": "R1", "source_timestamp": "2026-10-01T09:00:00+09:00", "collected_at": "2026-10-01T09:00:01+09:00"}],
        [{"symbol": "OPT1", "record_id": "W1", "source_timestamp_candidate": "2026-10-01T09:00:00+09:00", "received_at": "2026-10-01T09:00:01+09:00"}],
    )
    assert _audit(*args)["report_sha256"] == _audit(*args)["report_sha256"]
