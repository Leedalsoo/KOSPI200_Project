from application.composition.validation_only_trade_orderbook_cross_auditor import ValidationOnlyTradeOrderBookCrossAuditor


def audit(trades, books):
    return ValidationOnlyTradeOrderBookCrossAuditor(validation_only=True).audit(trade_records=trades,orderbook_records=books,source_manifest_hashes={"fixture":"a"*64})


def test_nearest_prior_trade_and_top_of_book_comparison():
    r=audit([{"symbol":"O1","record_id":"T1","source_timestamp_candidate":"2026-10-01T09:00:00+09:00","received_at":"2026-10-01T09:00:00.1+09:00","bid_price":"1.00","ask_price":"1.05","last_price":"1.02","volume":"2"}], [{"symbol":"O1","record_id":"B1","source_timestamp_candidate":"2026-10-01T09:00:01+09:00","received_at":"2026-10-01T09:00:01.1+09:00","bid_price":"1.00","ask_price":"1.10","payload_sha256":"b"*64}])
    assert r["counts"]["nearest_prior_trade"]==1 and r["alignments"][0]["anchor_age_seconds"]==1
    assert r["counts"]["bid_equal"]==1 and r["counts"]["ask_equal"]==0
    assert r["market_trade_is_broker_execution"] is False and r["gate_release_permitted"] is False


def test_future_trade_and_missing_trade_are_distinct():
    r=audit([{"symbol":"O1","record_id":"T1","source_timestamp_candidate":"2026-10-01T09:01:00+09:00","received_at":"2026-10-01T09:01:01+09:00"}], [{"symbol":"O1","record_id":"B1","source_timestamp_candidate":"2026-10-01T09:00:00+09:00","received_at":"2026-10-01T09:00:01+09:00"},{"symbol":"O2","record_id":"B2","source_timestamp_candidate":"2026-10-01T09:00:00+09:00","received_at":"2026-10-01T09:00:01+09:00"}])
    assert r["counts"]["future_trade_only"]==1 and r["counts"]["no_trade_source"]==1


def test_timezones_and_future_receive_order_are_checked():
    r=audit([{"symbol":"O1","record_id":"T1","source_timestamp_candidate":"2026-10-01T09:00:01+09:00","received_at":"2026-10-01T09:00:00+09:00"}], [])
    assert "TRADE_SOURCE_AFTER_RECEIVED:T1" in r["issues"]
    try:
        audit([{"symbol":"O1","source_timestamp_candidate":"2026-10-01T09:00:00"}], [])
    except ValueError as e: assert "TIMEZONE_REQUIRED" in str(e)
    else: raise AssertionError("timezone required")


def test_report_hash_is_deterministic():
    a=([{"symbol":"O1","record_id":"T1","source_timestamp_candidate":"2026-10-01T09:00:00+09:00","received_at":"2026-10-01T09:00:01+09:00","bid_price":"1","ask_price":"2"}],[{"symbol":"O1","record_id":"B1","source_timestamp_candidate":"2026-10-01T09:00:01+09:00","received_at":"2026-10-01T09:00:02+09:00","bid_price":"1","ask_price":"2"}])
    assert audit(*a)["report_sha256"]==audit(*a)["report_sha256"]
