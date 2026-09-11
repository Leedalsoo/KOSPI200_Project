"""Unit tests for KisFuturesInstrumentMasterProvider.

NOTE: All test fixtures herein are synthetic logic-verification fixtures.
Passing these tests proves adapter correctness against synthetic data contracts,
NOT successful external connection to the live KIS system.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
import pytest

from contracts.futures_contract_master import FuturesContractMasterError
from infrastructure.kis.instrument_master_provider import (
    KisFuturesInstrumentMasterProvider,
    KisInstrumentMasterProviderError,
)

# Synthetic test lines for KIS fo_idx_code_mts.mst format (9 pipe-separated fields)
SYNTHETIC_MINI_FUTURES_LINE = (
    "B|105W09|KR4105W09000|미니코스피200선물 2609| |0|1|2001|코스피200"
)
SYNTHETIC_REGULAR_FUTURES_LINE = (
    "1|101W09|KR4101W09000|코스피200선물 2609| |0|1|2001|코스피200"
)
SYNTHETIC_NEXT_MINI_FUTURES_LINE = (
    "B|105W10|KR4105W10000|미니코스피200선물 2610| |0|2|2001|코스피200"
)


def _make_euckr_payload(*lines: str) -> bytes:
    content = "\n".join(lines) + "\n"
    return content.encode("euc-kr")


def _make_zip_payload(filename: str, content_bytes: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, content_bytes)
    return buffer.getvalue()


def test_refresh_with_euckr_payload_creates_contract_identities():
    payload = _make_euckr_payload(
        SYNTHETIC_MINI_FUTURES_LINE,
        SYNTHETIC_REGULAR_FUTURES_LINE,
    )
    provider = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/fo_idx_code_mts.mst",
        downloader=lambda url: payload,
    )

    records = provider.refresh()
    assert len(records) == 2
    shrn_map = {r.shrn_iscd: r for r in records}
    assert "105W09" in shrn_map
    assert shrn_map["105W09"].info_type == "B"
    assert shrn_map["105W09"].mmsc_cls_code == "1"
    assert shrn_map["105W09"].unas_shrn_iscd == "2001"
    assert shrn_map["105W09"].unas_kor_name == "코스피200"


def test_decode_zip_payload_with_single_mst_file():
    raw_euckr = _make_euckr_payload(SYNTHETIC_MINI_FUTURES_LINE)
    zip_bytes = _make_zip_payload("fo_idx_code_mts.mst", raw_euckr)

    provider = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/fo_idx_code_mts.zip",
        downloader=lambda url: zip_bytes,
    )

    records = provider.refresh()
    assert len(records) == 1
    assert records[0].shrn_iscd == "105W09"


def test_decode_zip_payload_fails_if_multiple_or_zero_mst_files():
    # 0 mst files
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("something_else.txt", b"dummy")
    zip_no_mst = buffer.getvalue()

    provider_no_mst = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/no_mst.zip",
        downloader=lambda url: zip_no_mst,
    )
    with pytest.raises(KisInstrumentMasterProviderError) as exc_info:
        provider_no_mst.refresh()
    assert "ZIP_MST_FILE_NOT_UNIQUE" in str(exc_info.value)

    # 2 mst files
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("file1.mst", b"dummy")
        zf.writestr("file2.mst", b"dummy")
    zip_two_mst = buffer.getvalue()

    provider_two_mst = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/two_mst.zip",
        downloader=lambda url: zip_two_mst,
    )
    with pytest.raises(KisInstrumentMasterProviderError) as exc_info:
        provider_two_mst.refresh()
    assert "ZIP_MST_FILE_NOT_UNIQUE" in str(exc_info.value)


def test_non_https_source_url_fails_loud():
    provider = KisFuturesInstrumentMasterProvider(
        source_url="http://example.com/fo_idx_code_mts.mst",
        downloader=lambda url: b"dummy",
    )
    with pytest.raises(KisInstrumentMasterProviderError) as exc_info:
        provider.refresh()
    assert "HTTPS_SOURCE_REQUIRED" in str(exc_info.value)


def test_empty_payload_fails_loud():
    provider = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/fo_idx_code_mts.mst",
        downloader=lambda url: b"",
    )
    with pytest.raises(KisInstrumentMasterProviderError) as exc_info:
        provider.refresh()
    assert "EMPTY_PAYLOAD" in str(exc_info.value)


def test_invalid_euckr_payload_fails_loud():
    provider = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/fo_idx_code_mts.mst",
        downloader=lambda url: b"\xff\xfe\xff",
    )
    with pytest.raises(KisInstrumentMasterProviderError) as exc_info:
        provider.refresh()
    assert "EUCKR_DECODE_FAILED" in str(exc_info.value)


def test_no_futures_records_fails_loud():
    # Only non-futures lines (e.g. option info_type "5")
    non_futures_line = "5|201W09|KR4201W09000|코스피200콜옵션| |0|1|2001|코스피200"
    payload = _make_euckr_payload(non_futures_line)
    provider = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/fo_idx_code_mts.mst",
        downloader=lambda url: payload,
    )
    with pytest.raises(KisInstrumentMasterProviderError) as exc_info:
        provider.refresh()
    assert "NO_FUTURES_RECORDS" in str(exc_info.value)


def test_current_mini_futures_source_filters_info_type_b():
    payload = _make_euckr_payload(
        SYNTHETIC_MINI_FUTURES_LINE,
        SYNTHETIC_REGULAR_FUTURES_LINE,
        SYNTHETIC_NEXT_MINI_FUTURES_LINE,
    )
    provider = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/fo_idx_code_mts.mst",
        downloader=lambda url: payload,
    )

    source = provider.current_mini_futures_source(underlying_short_code="2001")
    contract = source.current_contract()
    assert contract.shrn_iscd == "105W09"
    assert contract.info_type == "B"
    assert contract.mmsc_cls_code == "1"


def test_current_mini_futures_source_fails_if_no_mini_futures_records():
    payload = _make_euckr_payload(SYNTHETIC_REGULAR_FUTURES_LINE)
    provider = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/fo_idx_code_mts.mst",
        downloader=lambda url: payload,
    )
    with pytest.raises(KisInstrumentMasterProviderError) as exc_info:
        provider.current_mini_futures_source(underlying_short_code="2001")
    assert "MINI_FUTURES_RECORDS_NOT_FOUND" in str(exc_info.value)


def test_current_contract_fails_closed_when_underlying_not_matched():
    payload = _make_euckr_payload(SYNTHETIC_MINI_FUTURES_LINE)
    provider = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/fo_idx_code_mts.mst",
        downloader=lambda url: payload,
    )
    source = provider.current_mini_futures_source(underlying_short_code="WRONG_CODE")
    with pytest.raises(FuturesContractMasterError) as exc_info:
        source.current_contract()
    assert "CURRENT_FUTURES_NOT_UNIQUE:0" in str(exc_info.value)


def test_cache_written_but_no_silent_fallback_on_network_failure(tmp_path: Path):
    cache_file = tmp_path / "cache" / "master.mst"
    payload = _make_euckr_payload(SYNTHETIC_MINI_FUTURES_LINE)

    # 1. First refresh succeeds and writes cache
    provider = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/fo_idx_code_mts.mst",
        cache_path=cache_file,
        downloader=lambda url: payload,
    )
    records = provider.refresh()
    assert len(records) == 1
    assert cache_file.exists()
    assert cache_file.read_bytes() == payload

    # 2. Subsequent failure does NOT fall back to cache; it raises immediately
    failing_provider = KisFuturesInstrumentMasterProvider(
        source_url="https://example.com/fo_idx_code_mts.mst",
        cache_path=cache_file,
        downloader=lambda url: (_ for _ in ()).throw(RuntimeError("NETWORK_DOWN")),
    )
    with pytest.raises(RuntimeError) as exc_info:
        failing_provider.refresh()
    assert "NETWORK_DOWN" in str(exc_info.value)
