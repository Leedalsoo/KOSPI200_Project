from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import infrastructure.kis.kis_websocket_option_identity_resolver as resolver_module
from application.composition.vms_market_tick_projection_adapter import (
    VMSMarketTickProjectionAdapter,
)
from contracts.types import OptionInstrumentIdentity
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.replay_engine import HistoricalReplayEngine
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from infrastructure.kis.kis_index_option_master_source import (
    KIS_INDEX_MASTER_URL,
    KISIndexMasterSnapshot,
)
from infrastructure.kis.kis_option_expiry_source import (
    EXPIRY_ENDPOINT,
    EXPIRY_TR_ID,
    KISOptionExpiryRecord,
    KISOptionExpiryResolver,
)
from infrastructure.kis.kis_websocket_market_observation_normalizer import (
    KISWebSocketMarketObservationNormalizer,
)
from infrastructure.kis.kis_websocket_option_identity_resolver import (
    KISWebSocketIdentityResolutionError,
    KISWebSocketOptionIdentityResolver,
)


def _snapshot(master_hash: str, rows: tuple[dict[str, object], ...] = ()) -> KISIndexMasterSnapshot:
    raw_lines = []
    for row in rows:
        strike = Decimal(str(row["strike"]))
        raw_lines.append(
            "|".join(
                (
                    str(row["type_code"]),
                    str(row["short_code"]),
                    str(row["standard_code"]),
                    str(row["master_name"]),
                    "",
                    f"{strike:08.2f}",
                    "",
                    "2001",
                    "",
                )
            )
        )
    raw_content = "\n".join(raw_lines)
    return KISIndexMasterSnapshot(
        raw_content=raw_content,
        archive_sha256=master_hash,
        archive_path=Path("snapshot.zip"),
        fetched_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        source_url=KIS_INDEX_MASTER_URL,
        row_count=len(raw_lines),
    )


def _row(symbol: str, master_hash: str, *, strike: str = "835.00") -> dict[str, object]:
    return {
        "short_code": symbol,
        "standard_code": f"KR4{symbol}",
        "type_code": "5",
        "option_type": "CALL",
        "product_series": "MONTHLY",
        "instrument_family": "STANDARD",
        "month": "202611",
        "expiry_label": "202611",
        "week_label": None,
        "strike": Decimal(strike),
        "master_name": f"C 202611 {Decimal(strike)}",
        "master_sha256": master_hash,
    }


def _expiry_record(symbol: str, master_hash: str, expiry: str = "20261112") -> KISOptionExpiryRecord:
    return KISOptionExpiryRecord(
        symbol=symbol,
        expiry_yyyymmdd=expiry,
        environment="VTS",
        source="KIS_REST:futs_last_tr_date",
        endpoint=EXPIRY_ENDPOINT,
        tr_id=EXPIRY_TR_ID,
        requested_at_utc="2026-10-20T16:00:00+00:00",
        received_at_utc="2026-10-20T16:00:01+00:00",
        http_status=200,
        rt_cd="0",
        msg_cd=None,
        response_field="output1.futs_last_tr_date",
        raw_response_sha256="c" * 64,
        master_sha256=master_hash,
        raw_response={"rt_cd": "0", "output1": {"futs_last_tr_date": expiry}},
    )


def test_exact_expiry_series_join_requires_identical_official_master_rows() -> None:
    target_hash = "a" * 64
    evidence_hash = "b" * 64
    target_rows = (
        _row("B01611835", target_hash),
        _row("B01611837", target_hash, strike="837.50"),
    )
    evidence_rows = (
        _row("B01611835", evidence_hash),
        _row("B01611837", evidence_hash, strike="837.50"),
    )
    resolver = KISWebSocketOptionIdentityResolver(
        target_snapshot=_snapshot(target_hash),
        target_rows=target_rows,
        evidence_snapshots={evidence_hash: _snapshot(evidence_hash, evidence_rows)},
        expiry_records=(_expiry_record("B01611835", evidence_hash),),
    )

    identity = resolver.get_contract_identity("B01611837")
    assert identity is not None
    assert identity.expiry == "20261112"
    assert identity.strike == Decimal("837.50")
    assert identity.contract_multiplier is None
    assert identity.identity_source.endswith("EXACT_ROW_JOIN")
    metadata = dict(resolver.provenance_metadata("B01611837"))
    assert metadata["master_snapshot_sha256"] == target_hash
    assert metadata["expiry_evidence_master_hashes"] == evidence_hash


def test_expiry_series_conflict_fails_closed() -> None:
    target_hash = "a" * 64
    evidence_hash = "b" * 64
    rows = (_row("B01611835", target_hash), _row("B01611837", target_hash, strike="837.50"))
    evidence_rows = (
        _row("B01611835", evidence_hash),
        _row("B01611837", evidence_hash, strike="837.50"),
    )
    with pytest.raises(KISWebSocketIdentityResolutionError, match="KIS_OPTION_SERIES_EXPIRY_CONFLICT"):
        KISWebSocketOptionIdentityResolver(
            target_snapshot=_snapshot(target_hash),
            target_rows=rows,
            evidence_snapshots={evidence_hash: _snapshot(evidence_hash, evidence_rows)},
            expiry_records=(
                _expiry_record("B01611835", evidence_hash, "20261112"),
                _expiry_record("B01611837", evidence_hash, "20261119"),
            ),
        )


def test_expiry_series_join_rejects_changed_master_identity_row() -> None:
    target_hash = "a" * 64
    evidence_hash = "b" * 64
    target_rows = (_row("B01611835", target_hash, strike="835.00"),)
    evidence_rows = (_row("B01611835", evidence_hash, strike="837.50"),)
    resolver = KISWebSocketOptionIdentityResolver(
        target_snapshot=_snapshot(target_hash),
        target_rows=target_rows,
        evidence_snapshots={evidence_hash: _snapshot(evidence_hash, evidence_rows)},
        expiry_records=(_expiry_record("B01611835", evidence_hash),),
    )
    assert resolver.get_contract_identity("B01611835") is None


def test_stale_master_expiry_cache_is_not_reused(tmp_path: Path) -> None:
    current_hash = "a" * 64
    other_hash = "b" * 64
    resolver = KISOptionExpiryResolver(
        master_sha256=current_hash,
        auth_manager=object(),
        transport=object(),
        cache_dir=tmp_path,
    )
    resolver.record_verified_response(
        symbol="B01611835",
        response={"rt_cd": "0", "output1": {"futs_last_tr_date": "20261112"}},
        http_status=200,
        requested_at_utc="2026-10-20T16:00:00+00:00",
        received_at_utc="2026-10-20T16:00:01+00:00",
    )
    stale_reader = KISOptionExpiryResolver(
        master_sha256=other_hash,
        auth_manager=object(),
        transport=object(),
        cache_dir=tmp_path,
    )
    assert stale_reader.cached_records_for_current_master() == ()
    assert stale_reader._cached_records("B01611835") == []


class _IdentityLookup:
    def get_contract_identity(self, symbol: str) -> OptionInstrumentIdentity | None:
        if symbol != "B01611835":
            return None
        return OptionInstrumentIdentity(
            instrument_id=symbol,
            symbol=symbol,
            expiry="20261112",
            option_type="CALL",
            strike=Decimal("835.00"),
            contract_multiplier=None,
            identity_source="KIS_OFFICIAL_INDEX_MASTER_TEST",
        )


def _quote_frame() -> str:
    fields = ["0"] * 38
    fields[0] = "B01611835"
    fields[1] = "093000"
    fields[2] = "43.50"
    fields[3] = "43.60"
    fields[7] = "43.40"
    fields[8] = "43.30"
    fields[22] = "2"
    fields[23] = "3"
    fields[27] = "4"
    fields[28] = "5"
    return "0|H0IOASP0|001|" + "^".join(fields)


def test_h0ioasp0_normalizes_five_price_and_quantity_levels_without_fake_greeks() -> None:
    normalizer = KISWebSocketMarketObservationNormalizer(_IdentityLookup())
    observation = normalizer.normalize_frame(
        _quote_frame(),
        received_at=datetime(2026, 10, 20, 0, 30, tzinfo=timezone.utc),
        run_id="quote-test",
        raw_id="20261020:1",
        raw_content_hash="d" * 64,
    )[0]

    assert observation.contract.expiry == "20261112"
    assert observation.provenance.tr_ids == ("H0IOASP0",)
    assert len(observation.order_book.bids) == 5
    assert len(observation.order_book.asks) == 5
    assert observation.order_book.asks[0].price == Decimal("43.50")
    assert observation.order_book.asks[0].quantity == Decimal("2")
    assert observation.order_book.bids[0].price == Decimal("43.40")
    assert observation.order_book.bids[0].quantity == Decimal("4")
    assert observation.order_book.total_ask_quantity == Decimal("5")
    assert observation.order_book.total_bid_quantity == Decimal("9")
    assert observation.analytics.implied_volatility is None
    assert observation.analytics.delta is None
    metadata = dict(observation.provenance.metadata)
    assert metadata["order_book_depth"] == "5"
    assert metadata["source_timestamp_semantics"] == "KIS_H0IOASP0_HHMMSS_CANDIDATE_UNVERIFIED"
    assert metadata["source_timestamp_field"] == "H0IOASP0.HHMMSS"
    assert metadata["source_timestamp_timezone"] == "UNVERIFIED"
    assert metadata["source_timestamp_date_resolution"] == "UNVERIFIED"
    assert metadata["source_timestamp_absolute"] == "false"
    assert metadata["source_capability_status"] == "UNVERIFIED_FOR_VTS_OFFICIAL_SAMPLE_SAYS_LIVE_ONLY"
    assert metadata["observed_at_semantics"] == "RECEIPT_TIME_FALLBACK_SOURCE_TIME_UNVERIFIED"
    assert metadata["receipt_timezone"] == "UTC"


def test_quote_only_observation_projects_without_inventing_trade_fields() -> None:
    normalizer = KISWebSocketMarketObservationNormalizer(_IdentityLookup())
    observation = normalizer.normalize_frame(
        _quote_frame(),
        received_at=datetime(2026, 10, 20, 0, 30, tzinfo=timezone.utc),
        run_id="quote-only-replay-test",
        raw_id="20261020:quote-only",
        raw_content_hash="e" * 64,
    )[0]

    tick = HistoricalReplayEngine.project_observation(observation, seq_id=17)
    assert tick.bid_price > 0
    assert tick.ask_price >= tick.bid_price
    assert tick.last_price is None
    assert tick.volume is None
    with pytest.raises(ValueError, match="REFERENCE_TICK_TRADE_FIELDS_UNAVAILABLE"):
        VMSMarketTickProjectionAdapter("B01611835").project(tick)


def test_historical_order_book_source_discards_invalid_levels_without_synthesis() -> None:
    from types import SimpleNamespace

    from infrastructure.kis.historical_observation_sources import (
        HistoricalObservationOptionSource,
    )

    levels = (
        SimpleNamespace(price="12.5", quantity="3"),
        SimpleNamespace(price=None, quantity="2"),
        SimpleNamespace(price="not-a-price", quantity="1"),
        SimpleNamespace(price="0", quantity="0"),
    )
    valid = HistoricalObservationOptionSource._valid_order_book_levels(levels)
    assert len(valid) == 1
    assert valid[0].price == Decimal("12.5")
    assert valid[0].quantity == Decimal("3")


def test_quote_only_event_uses_quote_consumer_and_never_legacy_tick_consumer() -> None:
    runtime = VirtualMarketSimulatorRuntime()
    tick_events = []
    quote_events = []
    runtime.subscribe(tick_events.append)
    runtime.subscribe_quote_only(quote_events.append)
    tick = ReferenceCanonicalMarketTick(
        timestamp="2026-10-20T09:30:00+09:00",
        strike_price=835.0,
        option_type="CALL",
        bid_price=43.4,
        ask_price=43.5,
        last_price=None,
        volume=None,
        seq_id=1,
        expiry="20261112",
        symbol="B01611835",
    )

    runtime.publish_replay_tick(tick)

    assert tick_events == []
    assert quote_events == [tick]
    assert runtime.last_tick is tick


def test_h0iocnt0_uses_exchange_event_time_and_unique_record_ids() -> None:
    normalizer = KISWebSocketMarketObservationNormalizer(_IdentityLookup())
    fields_a = ["0"] * 58
    fields_b = ["0"] * 58
    for fields, price in ((fields_a, "12.30"), (fields_b, "12.35")):
        fields[0] = "B01611835"
        fields[1] = "091501"
        fields[2] = price
        fields[10] = "1"
        fields[33] = "10.0"
        fields[41] = "12.40"
        fields[42] = "12.20"
    frame = "0|H0IOCNT0|2|" + "^".join(fields_a + fields_b)
    received_at = datetime(2026, 10, 12, 0, 15, 2, tzinfo=timezone.utc)

    observations = normalizer.normalize_frame(
        frame,
        received_at=received_at,
        run_id="trade-time-id-test",
        raw_id="20261012:7:line-9:frame-hash",
        raw_content_hash="f" * 64,
        session_date=date(2026, 10, 12),
    )

    assert len(observations) == 2
    assert observations[0].observation_id != observations[1].observation_id
    assert observations[0].observed_at.isoformat() == "2026-10-12T09:15:01+09:00"
    assert observations[1].observed_at == observations[0].observed_at
    assert all(item.collected_at == received_at for item in observations)
    assert [dict(item.provenance.metadata)["frame_record_index"] for item in observations] == ["0", "1"]
    assert all(dict(item.provenance.metadata)["received_at"] == received_at.isoformat() for item in observations)
    metadata = dict(observations[0].provenance.metadata)
    assert metadata["source_timestamp_field"] == "BSOP_HOUR"
    assert metadata["source_timestamp_raw"] == "091501"
    assert metadata["source_timestamp_timezone"] == "UNVERIFIED"
    assert metadata["source_timestamp_date_resolution"] == "UNVERIFIED"
    assert metadata["source_timestamp_absolute"] == "false"
    assert metadata["source_timestamp_interpretation"] == "CANDIDATE_ONLY"
    assert metadata["source_capability_status"] == "UNVERIFIED_FOR_VTS_OFFICIAL_SAMPLE_SAYS_LIVE_ONLY"
    assert metadata["source_environment"] == "UNKNOWN"
    assert metadata["source_environment_status"] == "UNVERIFIED_CONFLICT"
    assert metadata["source_time_semantics_verified"] == "false"
    assert metadata["candidate_source_clock_timezone"] == "Asia/Seoul"
    assert metadata["candidate_source_date_basis"] == "TRADING_DATE"
    assert metadata["observed_at_semantics"] == "CANDIDATE_SOURCE_EVENT_TIME_UNVERIFIED"
    assert metadata["candidate_source_to_receipt_lag_ms"] == "1000.000"
    assert metadata["receipt_timezone"] == "UTC"


def test_historical_master_override_is_explicit_and_date_scoped(monkeypatch, tmp_path: Path) -> None:
    from dataclasses import replace

    trading_day = date(2026, 10, 12)
    selected_snapshot_day = date(2026, 10, 14)
    target_hash = "a" * 64
    snapshot = replace(
        _snapshot(target_hash, (_row("B01611835", target_hash),)),
        archive_path=Path("fo_idx_code_mts_20261014_test.json"),
    )
    requested_dates: list[date] = []

    def load_snapshot(day: date, *, cache_dir: Path):
        requested_dates.append(day)
        return snapshot

    monkeypatch.setattr(resolver_module, "load_kis_master_snapshot_for_date", load_snapshot)
    monkeypatch.setattr(resolver_module, "_load_expiry_records_for_all_master_hashes", lambda cache_dir: ({}, ()))

    resolver = KISWebSocketOptionIdentityResolver.for_trading_date(
        trading_day, project_root=tmp_path, target_master_snapshot_date=selected_snapshot_day
    )

    assert requested_dates == [selected_snapshot_day]
    assert resolver.summary(["B01611835"])["target_master_snapshot_date"] == "20261014"
    assert resolver.provenance_metadata("B01611835")[1] == ("master_snapshot_date", "20261014")


def test_t13_ws_future_source_time_preserves_negative_clock_skew_without_clamping():
    normalizer = KISWebSocketMarketObservationNormalizer(_IdentityLookup())
    fields = ['0'] * 58
    fields[0] = 'B01611835'
    fields[1] = '091503'
    fields[2] = '12.30'
    fields[10] = '1'
    fields[33] = '10.0'
    fields[41] = '12.40'
    fields[42] = '12.20'
    received_at = datetime(2026, 10, 12, 0, 15, 2, tzinfo=timezone.utc)
    observation = normalizer.normalize_frame(
        '0|H0IOCNT0|1|' + '^'.join(fields),
        received_at=received_at,
        run_id='t13-negative-clock-skew',
        raw_id='20261012:negative-clock-skew',
        raw_content_hash='9' * 64,
        session_date=date(2026, 10, 12),
    )[0]
    metadata = dict(observation.provenance.metadata)
    assert metadata['candidate_source_to_receipt_lag_ms'] == '-1000.000'
    assert observation.observed_at.isoformat() == '2026-10-12T09:15:03+09:00'
    assert observation.collected_at == received_at


def test_h0iocnt0_replay_identity_is_provenance_deterministic_without_order_filtering() -> None:
    normalizer = KISWebSocketMarketObservationNormalizer(_IdentityLookup())

    def frame_at(hour: str, price: str) -> str:
        fields = ["0"] * 58
        fields[0] = "B01611835"
        fields[1] = hour
        fields[2] = price
        fields[10] = "1"
        fields[33] = "10.0"
        fields[41] = "12.40"
        fields[42] = "12.20"
        return "0|H0IOCNT0|1|" + "^".join(fields)

    received_at = datetime(2026, 10, 12, 0, 15, 3, tzinfo=timezone.utc)
    first_frame = frame_at("091502", "12.30")
    older_frame = frame_at("091501", "12.25")

    def normalize(frame: str, raw_id: str):
        return normalizer.normalize_frame(
            frame,
            received_at=received_at,
            run_id="synthetic-ordering-test",
            raw_id=raw_id,
            raw_content_hash="a" * 64,
            session_date=date(2026, 10, 12),
        )

    first = normalize(first_frame, "synthetic-frame-1")
    exact_replay = normalize(first_frame, "synthetic-frame-1")
    older = normalize(older_frame, "synthetic-frame-2")

    assert first[0].observation_id == exact_replay[0].observation_id
    assert first[0].observation_id != older[0].observation_id
    assert first[0].observed_at > older[0].observed_at
    assert older[0].collected_at == received_at
