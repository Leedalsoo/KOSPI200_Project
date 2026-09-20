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


def test_daily_ingestor_selects_regular_futures_row_from_mkt_name(tmp_path):
    from datetime import date, datetime
    from decimal import Decimal
    from contracts.historical_market_ohlc import HistoricalDailyOHLC

    class Normalizer:
        def normalize_option_row(self, row):
            raise AssertionError("not used")

        def normalize_futures_row(self, row):
            assert row["MKT_NM"] == "정규"
            return HistoricalDailyOHLC("A016C000", date(2026, 9, 18), Decimal("1092.8"), Decimal("1095.2"), Decimal("1079"), Decimal("1092.45"), datetime(2026, 9, 18), "KRX_OPEN_API:fut_bydd_trd;KRX_ISU_CD=A016C000")

    raw = tmp_path / "daily.json"
    rows = [
        {"BAS_DD": "20260918", "ISU_CD": "A016C000", "MKT_NM": "야간", "TDD_OPNPRC": "1067.55", "TDD_HGPRC": "1099.5", "TDD_LWPRC": "1065.35", "TDD_CLSPRC": "1094.55"},
        {"BAS_DD": "20260918", "ISU_CD": "A016C000", "MKT_NM": "정규", "TDD_OPNPRC": "1092.8", "TDD_HGPRC": "1095.2", "TDD_LWPRC": "1079", "TDD_CLSPRC": "1092.45"},
    ]
    raw.write_text(json.dumps({"OutBlock_1": rows}, ensure_ascii=False), encoding="utf-8")
    master = tmp_path / "master.xlsx"
    master.write_bytes(b"master")
    store = HistoricalDailyStore(tmp_path / "out.jsonl")
    ingestor = KRXDailyHistoricalIngestor(normalizer=Normalizer(), store=store, raw_dir=tmp_path, master_paths=[master])
    result = ingestor.ingest_file(raw, kind="futures")
    assert result[0] == 1
    assert result[1] == 0
    assert store.load_records()[0][0].close == Decimal("1092.45")


def test_daily_ingestor_selects_regular_option_row_from_isu_name(tmp_path):
    from datetime import date, datetime
    from decimal import Decimal
    from contracts.historical_market_ohlc import HistoricalDailyOHLC

    class Normalizer:
        def normalize_option_row(self, row):
            assert row["ISU_NM"].endswith("(\uC815\uADDC)")
            return HistoricalDailyOHLC("B056A752", date(2026, 9, 18), Decimal("10"), Decimal("11"), Decimal("9"), Decimal("10.5"), datetime(2026, 9, 18), "KRX_OPEN_API:opt_bydd_trd;KRX_ISU_CD=B056A752")

        def normalize_futures_row(self, row):
            raise AssertionError("not used")

    raw = tmp_path / "daily.json"
    rows = [
        {"BAS_DD": "20260918", "ISU_CD": "B056A752", "ISU_NM": "KOSPI200 C 202610 752.5 (\uC57C\uAC04)", "TDD_OPNPRC": "20", "TDD_HGPRC": "21", "TDD_LWPRC": "19", "TDD_CLSPRC": "20.5"},
        {"BAS_DD": "20260918", "ISU_CD": "B056A752", "ISU_NM": "KOSPI200 C 202610 752.5 (\uC815\uADDC)", "TDD_OPNPRC": "10", "TDD_HGPRC": "11", "TDD_LWPRC": "9", "TDD_CLSPRC": "10.5"},
    ]
    raw.write_text(json.dumps({"OutBlock_1": rows}, ensure_ascii=False), encoding="utf-8")
    master = tmp_path / "master.xlsx"; master.write_bytes(b"master")
    store = HistoricalDailyStore(tmp_path / "out.jsonl")
    ingestor = KRXDailyHistoricalIngestor(normalizer=Normalizer(), store=store, raw_dir=tmp_path, master_paths=[master])
    result = ingestor.ingest_file(raw, kind="option")
    assert result[0] == 1
    assert result[1] == 0


def test_daily_ingestor_keeps_collision_when_multiple_regular_option_rows_exist(tmp_path):
    from datetime import date, datetime
    from decimal import Decimal
    from contracts.historical_market_ohlc import HistoricalDailyOHLC

    class Normalizer:
        def normalize_option_row(self, row):
            return HistoricalDailyOHLC("B056A752", date(2026, 9, 18), Decimal(row["TDD_OPNPRC"]), Decimal(row["TDD_HGPRC"]), Decimal(row["TDD_LWPRC"]), Decimal(row["TDD_CLSPRC"]), datetime(2026, 9, 18), "KRX_OPEN_API:opt_bydd_trd;KRX_ISU_CD=B056A752")

        def normalize_futures_row(self, row):
            raise AssertionError("not used")

    raw = tmp_path / "daily.json"
    rows = [
        {"BAS_DD": "20260918", "ISU_CD": "B056A752", "ISU_NM": "KOSPI200 C 202610 752.5 (\uC815\uADDC)", "TDD_OPNPRC": "10", "TDD_HGPRC": "11", "TDD_LWPRC": "9", "TDD_CLSPRC": "10.5"},
        {"BAS_DD": "20260918", "ISU_CD": "B056A752", "ISU_NM": "KOSPI200 C 202610 752.5 (\uC815\uADDC)", "TDD_OPNPRC": "20", "TDD_HGPRC": "21", "TDD_LWPRC": "19", "TDD_CLSPRC": "20.5"},
    ]
    raw.write_text(json.dumps({"OutBlock_1": rows}, ensure_ascii=False), encoding="utf-8")
    master = tmp_path / "master.xlsx"; master.write_bytes(b"master")
    store = HistoricalDailyStore(tmp_path / "out.jsonl")
    ingestor = KRXDailyHistoricalIngestor(normalizer=Normalizer(), store=store, raw_dir=tmp_path, master_paths=[master])
    result = ingestor.ingest_file(raw, kind="option")
    assert result[0] == 0
    assert result[1] == 2
    assert result[2]["CANONICAL_DAILY_IDENTITY_COLLISION"] == 2
