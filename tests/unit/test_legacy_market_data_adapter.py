from pathlib import Path

from infrastructure.kis.legacy_market_data_adapter import LegacyMarketDataAdapter


def test_legacy_adapter_is_read_only_and_preserves_source_paths(tmp_path):
    rest = tmp_path / "kis_rest_collection"
    minute = tmp_path / "kis_rest_minute_backfill"
    rest.mkdir()
    minute.mkdir()
    (rest / "20260921_collection_summary.json").write_text("{}", encoding="utf-8")
    (minute / "C01610A29_vts-rest-minute-backfill-20260921.json").write_text("{}", encoding="utf-8")
    adapter = LegacyMarketDataAdapter(tmp_path)
    files = adapter.files_for("2026-09-21")
    assert "kis_rest_collection/20260921_collection_summary.json" in files
    assert "kis_rest_minute_backfill/C01610A29_vts-rest-minute-backfill-20260921.json" in files


def test_legacy_adapter_does_not_copy_or_delete_data(tmp_path):
    legacy = tmp_path / "kis_rest_collection"
    legacy.mkdir()
    source = legacy / "20260921_collection_summary.json"
    source.write_text("original", encoding="utf-8")
    adapter = LegacyMarketDataAdapter(tmp_path)
    adapter.files_for("2026-09-21")
    assert source.exists()
    assert source.read_text(encoding="utf-8") == "original"
