import json

from contracts.historical_daily_store import HistoricalDailyStore
from infrastructure.krx.krx_daily_ingestion import KRXDailyHistoricalIngestor


def test_daily_ingestor_records_only_price_complete_rows(monkeypatch, tmp_path):
    class Normalizer:
        def normalize_option_row(self, row):
            raise ValueError("not used")

        def normalize_futures_row(self, row):
            raise ValueError("not used")

    raw = tmp_path / "daily.json"
    raw.write_text(json.dumps({"OutBlock_1": [
        {"BAS_DD": "20260918", "TDD_OPNPRC": "1", "TDD_HGPRC": "2", "TDD_LWPRC": "1", "TDD_CLSPRC": "2", "ISU_CD": "X"},
        {"BAS_DD": "20260918", "TDD_OPNPRC": "", "TDD_HGPRC": "2", "TDD_LWPRC": "1", "TDD_CLSPRC": "2", "ISU_CD": "Y"},
    ]}), encoding="utf-8")
    master = tmp_path / "master.xlsx"
    master.write_bytes(b"master")
    store = HistoricalDailyStore(tmp_path / "out.jsonl")
    ingestor = KRXDailyHistoricalIngestor(
        normalizer=Normalizer(), store=store, raw_dir=tmp_path, master_paths=[master]
    )
    try:
        ingestor.ingest_file(raw, kind="option")
    except ValueError as exc:
        assert str(exc) == "not used"
    else:
        raise AssertionError("test normalizer should be invoked for the complete row")


def test_daily_ingestor_blocks_ambiguous_canonical_collision(tmp_path):
    from datetime import date, datetime
    from decimal import Decimal
    from contracts.historical_market_ohlc import HistoricalDailyOHLC

    class Normalizer:
        def normalize_option_row(self, row):
            return HistoricalDailyOHLC(
                symbol="B056A752",
                trading_date=date(2026, 9, 18),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10.5"),
                observed_at=datetime(2026, 9, 18),
                source="KRX_OPEN_API:opt_bydd_trd;KRX_ISU_CD=B056A752",
            )

        def normalize_futures_row(self, row):
            raise AssertionError("not used")

    raw = tmp_path / "daily.json"
    rows = [
        {"BAS_DD": "20260918", "TDD_OPNPRC": "10", "TDD_HGPRC": "11", "TDD_LWPRC": "9", "TDD_CLSPRC": "10.5", "ISU_CD": "B056A752"},
        {"BAS_DD": "20260918", "TDD_OPNPRC": "20", "TDD_HGPRC": "21", "TDD_LWPRC": "19", "TDD_CLSPRC": "20.5", "ISU_CD": "B056A752"},
    ]
    raw.write_text(json.dumps({"OutBlock_1": rows}), encoding="utf-8")
    master = tmp_path / "master.xlsx"
    master.write_bytes(b"master")
    store = HistoricalDailyStore(tmp_path / "out.jsonl")
    ingestor = KRXDailyHistoricalIngestor(
        normalizer=Normalizer(), store=store, raw_dir=tmp_path, master_paths=[master]
    )
    result = ingestor.ingest_file(raw, kind="option")
    assert result[0] == 0
    assert result[1] == 2
    assert result[2]["CANONICAL_DAILY_IDENTITY_COLLISION"] == 2
    assert store.load_records() == []
