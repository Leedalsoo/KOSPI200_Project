import json
from pathlib import Path

import pytest

from scripts.acquire_krx_daily_snapshot import (
    KRXAcquisitionError,
    load_auth_key,
    parse_response,
)


def test_parse_response_accepts_authoritative_option_daily_rows():
    payload = {
        "OutBlock_1": [{
            "BAS_DD": "20261008",
            "ISU_CD": "B01610A32",
            "ISU_NM": "KOSPI200 C 202610 1090.0",
            "PROD_NM": "KOSPI200",
            "RGHT_TP_NM": "CALL",
        }]
    }
    parsed, rows = parse_response("options", "20261008", json.dumps(payload).encode())

    assert parsed == payload
    assert len(rows) == 1


def test_parse_response_accepts_authoritative_futures_daily_rows():
    payload = {
        "OutBlock_1": [{
            "BAS_DD": "20261008",
            "ISU_CD": "A016C000",
            "ISU_NM": "KOSPI200 Futures 202610",
            "MKT_NM": "??",
            "SPOT_PRC": "1044.52",
        }]
    }
    _, rows = parse_response("futures", "20261008", json.dumps(payload).encode())

    assert rows[0]["SPOT_PRC"] == "1044.52"


@pytest.mark.parametrize("payload, message", [
    ({"OutBlock_1": []}, "KRX_RESPONSE_ROWS_EMPTY"),
    ({"OutBlock_1": [{"BAS_DD": "20261007", "ISU_CD": "X", "ISU_NM": "X",
                       "PROD_NM": "KOSPI200", "RGHT_TP_NM": "CALL"}]},
     "KRX_RESPONSE_DATE_MISMATCH"),
    ({"OutBlock_1": [{"BAS_DD": "20261008", "ISU_CD": "X", "ISU_NM": "X"}]},
     "KRX_RESPONSE_SCHEMA_MISSING"),
])
def test_parse_response_fails_closed_for_empty_mismatched_or_incomplete_payload(payload, message):
    with pytest.raises(KRXAcquisitionError, match=message):
        parse_response("options", "20261008", json.dumps(payload).encode())


def test_load_auth_key_reads_environment_without_logging(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("KRX_AUTH_KEY", "test-key-not-for-production")

    assert load_auth_key(tmp_path) == "test-key-not-for-production"


def test_load_auth_key_reads_local_env_file(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("KRX_AUTH_KEY", raising=False)
    (tmp_path / ".env").write_text("KRX_AUTH_KEY=local-test-key" + chr(10), encoding="utf-8")

    assert load_auth_key(tmp_path) == "local-test-key"


def test_load_auth_key_blocks_when_unset(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("KRX_AUTH_KEY", raising=False)

    with pytest.raises(KRXAcquisitionError, match="KRX_AUTH_KEY_REQUIRED"):
        load_auth_key(tmp_path)
