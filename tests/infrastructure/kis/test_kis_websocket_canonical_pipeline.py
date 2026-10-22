from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from contracts.types import OptionInstrumentIdentity
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
from application.composition.vms_market_tick_projection_adapter import VMSMarketTickProjectionAdapter
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.replay_engine import HistoricalReplayEngine
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime


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
    from infrastructure.kis.historical_observation_sources import HistoricalObservationOptionSource

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
