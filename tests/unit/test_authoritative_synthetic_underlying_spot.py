import json
from datetime import date
from pathlib import Path
import pytest
from scripts.generate_authoritative_option_synthetic_3m import load_initial_underlying_spot

def korean(escaped: str) -> str:
    return bytes(escaped, "ascii").decode("unicode_escape")

def test_initial_spot_comes_from_regular_kospi200_futures_not_mini(tmp_path: Path):
    folder = tmp_path / "data" / "historical" / "krx_raw"
    folder.mkdir(parents=True)
    mini = korean("\\ubbf8\\ub2c8\\ucf54\\uc2a4\\ud53c200 \\uc120\\ubb3c")
    mini_name = korean("\\ubbf8\\ub2c8\\ucf54\\uc2a4\\ud53c F 202612 (\\uc8fc\\uac04)")
    regular = korean("\\ucf54\\uc2a4\\ud53c200 \\uc120\\ubb3c")
    regular_name = korean("\\ucf54\\uc2a4\\ud53c200 F 202612 (\\uc8fc\\uac04)")
    (folder / "20260918_futures_daily.json").write_text(json.dumps({"OutBlock_1": [
        {"BAS_DD": "20260918", "PROD_NM": mini, "ISU_NM": mini_name, "ISU_CD": "A056C000", "SPOT_PRC": "752.50"},
        {"BAS_DD": "20260918", "PROD_NM": regular, "ISU_NM": regular_name, "ISU_CD": "A016C000", "SPOT_PRC": "1090.23"},
    ]}, ensure_ascii=False), encoding="utf-8")
    value, source, code = load_initial_underlying_spot(tmp_path, date(2026, 9, 18))
    assert value == 1090.23
    assert source.endswith("20260918_futures_daily.json")
    assert code == "A016C000"

def test_initial_spot_fails_closed_when_regular_kospi200_source_missing(tmp_path: Path):
    folder = tmp_path / "data" / "historical" / "krx_raw"
    folder.mkdir(parents=True)
    mini = korean("\\ubbf8\\ub2c8\\ucf54\\uc2a4\\ud53c200 \\uc120\\ubb3c")
    mini_name = korean("\\ubbf8\\ub2c8\\ucf54\\uc2a4\\ud53c F 202612 (\\uc8fc\\uac04)")
    (folder / "20260918_futures_daily.json").write_text(json.dumps({"OutBlock_1": [
        {"BAS_DD": "20260918", "PROD_NM": mini, "ISU_NM": mini_name, "ISU_CD": "A056C000", "SPOT_PRC": "752.50"}
    ]}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="KRX_AUTHORITATIVE_KOSPI200_SPOT_NOT_FOUND"):
        load_initial_underlying_spot(tmp_path, date(2026, 9, 18))
