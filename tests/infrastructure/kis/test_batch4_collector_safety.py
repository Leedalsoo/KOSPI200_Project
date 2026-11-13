from datetime import date
import json
from pathlib import Path

import pytest

from infrastructure.kis.kis_rest_market_observation_collector import (
    KISRestMarketObservationCollector,
)
from infrastructure.kis.kis_websocket_option_identity_resolver import (
    KISWebSocketIdentityResolutionError,
    KISWebSocketOptionIdentityResolver,
)
from scripts.ingest_kis_vts_websocket_canonical import _load_raw_manifest, _sha256_file


class _Clock:
    def monotonic(self):
        return 1.0

    def sleep(self, seconds):
        raise AssertionError("unexpected_sleep")

    def now(self):
        raise AssertionError("unexpected_clock_read")


def test_rest_collector_default_interval_respects_policy_minimum():
    collector = KISRestMarketObservationCollector(
        identity_source={}, transport=object(), store=object(), clock=_Clock()
    )
    assert collector.limiter.interval_seconds == 1.25


def test_ws_raw_manifest_requires_matching_sha256_and_record_count(tmp_path: Path):
    raw_path = tmp_path / "kis_vts_websocket_raw.jsonl"
    raw_path.write_text('{"sequence":1}\n{"sequence":2}\n', encoding="utf-8")
    manifest = {
        "schema": "kis-realtime-raw-manifest-v1",
        "source": "KIS_VTS_WEBSOCKET_RAW",
        "trading_date": "20261021",
        "file": raw_path.name,
        "file_sha256": _sha256_file(raw_path),
        "record_count": 2,
    }
    raw_path.with_name(raw_path.name + ".manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    assert _load_raw_manifest(raw_path, date(2026, 10, 21))["record_count"] == 2

    manifest["record_count"] = 1
    raw_path.with_name(raw_path.name + ".manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="WS_RAW_RECORD_COUNT_MISMATCH"):
        _load_raw_manifest(raw_path, date(2026, 10, 21))


def test_ws_identity_resolver_fails_closed_without_verified_local_master(tmp_path: Path, monkeypatch):
    import urllib.request

    def forbidden_network(*args, **kwargs):
        raise AssertionError("network_access_forbidden")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden_network)
    with pytest.raises(
        KISWebSocketIdentityResolutionError,
        match="KIS_MASTER_SNAPSHOT_FOR_DATE_MISSING:20261021",
    ):
        KISWebSocketOptionIdentityResolver.for_trading_date(
            date(2026, 10, 21), project_root=tmp_path
        )

def test_ws_raw_manifest_rejects_sha256_mismatch(tmp_path: Path):
    raw_path = tmp_path / "kis_vts_websocket_raw.jsonl"
    raw_path.write_text('{"sequence":1}\n', encoding="utf-8")
    manifest = {
        "schema": "kis-realtime-raw-manifest-v1",
        "source": "KIS_VTS_WEBSOCKET_RAW",
        "trading_date": "20261021",
        "file": raw_path.name,
        "file_sha256": _sha256_file(raw_path),
        "record_count": 1,
    }
    raw_path.with_name(raw_path.name + ".manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    raw_path.write_text('{"sequence":2}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="WS_RAW_FILE_HASH_MISMATCH"):
        _load_raw_manifest(raw_path, date(2026, 10, 21))

\n