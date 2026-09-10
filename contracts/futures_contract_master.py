"""KIS index-futures contract projection from fo_idx_code_mts.mst.

Authoritative meanings follow KIS 종목마스터정보(지수선물옵션).h
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

KIS_FUTURES_INFO_TYPES = frozenset({"1", "3", "7", "9", "B"})

KIS_CURRENT_MONTH_CODE = "1"


class FuturesContractMasterError(ValueError):
    pass


@dataclass(frozen=True)
class KisFuturesContractIdentity:
    shrn_iscd: str
    stnd_iscd: Optional[str]
    info_type: str
    mmsc_cls_code: str
    unas_shrn_iscd: Optional[str]
    unas_kor_name: Optional[str]
    kor_name: Optional[str] = None


def parse_kis_futures_contracts(raw_content: str) -> tuple[KisFuturesContractIdentity, ...]:
    records: list[KisFuturesContractIdentity] = []
    seen: dict[str, KisFuturesContractIdentity] = {}
    for line in raw_content.splitlines():
        if not line or "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 9:
            continue
        info_type, shrn_iscd, stnd_iscd, kor_name = parts[:4]
        if info_type not in KIS_FUTURES_INFO_TYPES or not shrn_iscd:
            continue
        identity = KisFuturesContractIdentity(
            shrn_iscd=shrn_iscd,
            stnd_iscd=stnd_iscd or None,
            info_type=info_type,
            mmsc_cls_code=parts[6],
            unas_shrn_iscd=parts[7] or None,
            unas_kor_name=parts[8] or None,
            kor_name=kor_name or None,
        )
        existing = seen.get(shrn_iscd)
        if existing is not None and existing != identity:
            raise FuturesContractMasterError(f"CONFLICTING_FUTURES_IDENTITY:{shrn_iscd}")
        seen[shrn_iscd] = identity
    return tuple(seen.values())


def select_current_futures_contract(
    records: Iterable[KisFuturesContractIdentity],
# *,
    underlying_short_code: Optional[str] = None,
    underlying_name: Optional[str] = None,
) -> KisFuturesContractIdentity:
    candidates = [r for r in records if r.mmsc_cls_code == KIS_CURRENT_MONTH_CODE]
    if underlying_short_code is not None:
        candidates = [r for r in candidates if r.unas_shrn_iscd == underlying_short_code]
    if underlying_name is not None:
        candidates = [r for r in candidates if r.unas_kor_name == underlying_name]
    if len(candidates) != 1:
        raise FuturesContractMasterError(f"CURRENT_FUTURES_NOT_UNIQUE:{len(candidates)}")
    return candidates[0]


class KisCurrentFuturesContractSource:
    def __init__(self, records, *, underlying_short_code=None, underlying_name=None):
        self._records = tuple(records)
        self._underlying_short_code = underlying_short_code
        self._underlying_name = underlying_name

    def current_contract(self) -> KisFuturesContractIdentity:
        return select_current_futures_contract(
            self._records,
            underlying_short_code=self._underlying_short_code,
            underlying_name=self._underlying_name,
        )

    def with_target(
# self,
# *,
        underlying_short_code: Optional[str] = None,
        underlying_name: Optional[str] = None,
    ) -> "KisCurrentFuturesContractSource":
        return KisCurrentFuturesContractSource(
            self._records,
            underlying_short_code=underlying_short_code,
            underlying_name=underlying_name,
        )
