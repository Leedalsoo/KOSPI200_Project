from __future__ import annotations

import re
import urllib.request
import zipfile
from io import BytesIO
from decimal import Decimal
from typing import Mapping

from core.option.option_master import KisOptionContractIdentity
from contracts.types import OptionInstrumentIdentity


KIS_INDEX_OPTION_MASTER_URL = (
    "https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip"
)


def parse_kis_index_option_master(raw_text: str) -> dict[str, KisOptionContractIdentity]:
    """Parse current KIS index-option MTS master (pipe or fixed-width)."""
    result: dict[str, KisOptionContractIdentity] = {}
    for line in raw_text.splitlines():
        if "|" in line:
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 6:
                continue
            info_type, shrn_iscd, stnd_iscd, name, _, strike_raw = parts[:6]
        else:
            if len(line) < 72:
                continue
            info_type = line[0:1]
            shrn_iscd = line[1:10].strip()
            stnd_iscd = line[10:22].strip()
            name = line[22:63].strip()
            strike_raw = line[63:72].strip()
        if info_type not in {"5", "6", "D", "E", "L", "M"}:
            continue
        expiry_match = re.search(r"20\d{4}", name)
        if not shrn_iscd or not stnd_iscd or not expiry_match:
            continue
        try:
            strike = Decimal(strike_raw)
        except Exception:
            continue
        option_type = "CALL" if info_type in {"5", "D", "L"} else "PUT"
        identity = KisOptionContractIdentity(
            shrn_iscd=shrn_iscd, stnd_iscd=stnd_iscd,
            expiry=expiry_match.group(0), option_type=option_type,
            strike=strike, info_type="KIS_INDEX_OPTION_MASTER",
            contract_multiplier=Decimal("250000"),
        )
        existing = result.get(shrn_iscd)
        if existing is not None and existing != identity:
            raise ValueError(f"AMBIGUOUS_KIS_SHORT_CODE:{shrn_iscd}")
        result[shrn_iscd] = identity
    if not result:
        raise ValueError("KIS_INDEX_OPTION_MASTER_EMPTY")
    return result


def load_kis_index_option_master(
    url: str = KIS_INDEX_OPTION_MASTER_URL, timeout: float = 10.0
) -> dict[str, KisOptionContractIdentity]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        archive_bytes = response.read()
    with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
        name = next(
            (item for item in archive.namelist() if "fo_idx_code" in item), None
        )
        if name is None:
            raise ValueError("KIS_INDEX_OPTION_MASTER_FILE_MISSING")
        raw = archive.read(name).decode("cp949", errors="ignore")
    return parse_kis_index_option_master(raw)


class KRXKISOptionIdentityResolver:
    """Combine KRX contract identity with the authoritative KIS broker symbol."""

    def __init__(self, kis_master: Mapping[str, KisOptionContractIdentity]) -> None:
        self._by_short = dict(kis_master)
        self._by_standard = {
            identity.stnd_iscd: identity
            for identity in self._by_short.values()
            if identity.stnd_iscd
        }

    def get_contract_identity(
        self, symbol: str, krx_identity: KisOptionContractIdentity | None = None
    ) -> OptionInstrumentIdentity | None:
        if krx_identity is not None:
            if not krx_identity.stnd_iscd:
                return None
            kis = self._by_standard.get(krx_identity.stnd_iscd)
            if kis is None:
                return None
            if (
                kis.expiry != krx_identity.expiry.replace("-", "")[:6]
                or kis.option_type != krx_identity.option_type
                or kis.strike != krx_identity.strike
            ):
                return None
            return OptionInstrumentIdentity(
                instrument_id=krx_identity.shrn_iscd,
                symbol=kis.shrn_iscd,
                expiry=krx_identity.expiry,
                option_type=krx_identity.option_type,
                strike=krx_identity.strike,
                contract_multiplier=krx_identity.contract_multiplier,
                identity_source="KRX_MARKETPLACE+KIS_INDEX_OPTION_MASTER",
            )
        kis = self._by_short.get(symbol.strip())
        if kis is None:
            return None
        return OptionInstrumentIdentity(
            instrument_id=kis.shrn_iscd,
            symbol=kis.shrn_iscd,
            expiry=kis.expiry,
            option_type=kis.option_type,
            strike=kis.strike,
            contract_multiplier=kis.contract_multiplier,
            identity_source="KIS_INDEX_OPTION_MASTER",
        )
