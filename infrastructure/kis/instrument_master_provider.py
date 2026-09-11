from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from contracts.futures_contract_master import (
    KisCurrentFuturesContractSource,
    KisFuturesContractIdentity,
    parse_kis_futures_contracts,
)


class KisInstrumentMasterProviderError(RuntimeError):
    """Raised when the authoritative KIS instrument master cannot be loaded safely."""


DownloadBytes = Callable[[str], bytes]


def _download_bytes(source_url: str, timeout: float) -> bytes:
    request = Request(
        source_url,
        headers={"User-Agent": "KOSPI200_Project/Project200"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:
        raise KisInstrumentMasterProviderError(
            "KIS_INSTRUMENT_MASTER_DOWNLOAD_FAILED"
        ) from exc


def _decode_master_payload(payload: bytes) -> str:
    if payload.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = [name for name in archive.namelist() if name.lower().endswith(".mst")]
                if len(names) != 1:
                    raise KisInstrumentMasterProviderError(
                        "KIS_INSTRUMENT_MASTER_ZIP_MST_FILE_NOT_UNIQUE"
                    )
                payload = archive.read(names[0])
        except KisInstrumentMasterProviderError:
            raise
        except Exception as exc:
            raise KisInstrumentMasterProviderError(
                "KIS_INSTRUMENT_MASTER_ZIP_READ_FAILED"
            ) from exc

    try:
        return payload.decode("euc-kr")
    except UnicodeDecodeError as exc:
        raise KisInstrumentMasterProviderError(
            "KIS_INSTRUMENT_MASTER_EUCKR_DECODE_FAILED"
        ) from exc


@dataclass(frozen=True)
class KisFuturesInstrumentMasterProvider:
    """Loads the authoritative KIS domestic index-futures master.

    The source URL is deliberately injected. This class never invents a KIS URL,
    instrument code, contract value, timestamp, or fallback instrument.
    """

    source_url: str
    timeout: float = 10.0
    cache_path: Path | None = None
    downloader: DownloadBytes | None = None

    def refresh(self) -> tuple[KisFuturesContractIdentity, ...]:
        if not self.source_url.startswith("https://"):
            raise KisInstrumentMasterProviderError(
                "KIS_INSTRUMENT_MASTER_HTTPS_SOURCE_REQUIRED"
            )

        download = self.downloader
        payload = (
            download(self.source_url)
            if download is not None
            else _download_bytes(self.source_url, self.timeout)
        )
        if not payload:
            raise KisInstrumentMasterProviderError(
                "KIS_INSTRUMENT_MASTER_EMPTY_PAYLOAD"
            )

        if self.cache_path is not None:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_bytes(payload)

        records = parse_kis_futures_contracts(_decode_master_payload(payload))
        if not records:
            raise KisInstrumentMasterProviderError(
                "KIS_INSTRUMENT_MASTER_NO_FUTURES_RECORDS"
            )
        return records

    def current_mini_futures_source(
        self,
        *,
        underlying_short_code: str,
    ) -> KisCurrentFuturesContractSource:
        records = tuple(
            record
            for record in self.refresh()
            if record.info_type == "B"
        )
        if not records:
            raise KisInstrumentMasterProviderError(
                "KIS_MINI_FUTURES_RECORDS_NOT_FOUND"
            )
        return KisCurrentFuturesContractSource(
            records,
            underlying_short_code=underlying_short_code,
        )
