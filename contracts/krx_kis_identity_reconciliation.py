"""KRX/KIS identity reconciliation.

No implicit code conversion is permitted. A match is accepted only when the
authoritative KRX ISU_CD exactly equals a KIS stnd_iscd. Name similarity and
prefix heuristics are intentionally excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

ProductKind = Literal["FUTURES", "OPTION"]


class IdentityReconciliationError(ValueError):
    pass


@dataclass(frozen=True)
class KrxInstrumentRecord:
    isu_cd: str
    isu_nm: str
    product_kind: ProductKind

    def __post_init__(self) -> None:
        if not self.isu_cd.strip():
            raise IdentityReconciliationError("KRX_ISU_CD_REQUIRED")
        if not self.isu_nm.strip():
            raise IdentityReconciliationError("KRX_ISU_NM_REQUIRED")


@dataclass(frozen=True)
class KisMasterIdentityRecord:
    shrn_iscd: str
    stnd_iscd: str | None

    def __post_init__(self) -> None:
        if not self.shrn_iscd.strip():
            raise IdentityReconciliationError("KIS_SHRN_ISCD_REQUIRED")


@dataclass(frozen=True)
class ReconciledInstrumentIdentity:
    product_kind: ProductKind
    krx_isu_cd: str
    kis_shrn_iscd: str
    kis_stnd_iscd: str
    matched_by: str = "KIS_STND_ISCD_EXACT"


def reconcile_krx_to_kis(
    krx_records: Iterable[KrxInstrumentRecord],
    kis_records: Iterable[KisMasterIdentityRecord],
) -> tuple[ReconciledInstrumentIdentity, ...]:
    by_standard: dict[str, KisMasterIdentityRecord] = {}
    for record in kis_records:
        if not record.stnd_iscd:
            continue
        key = record.stnd_iscd.strip()
        previous = by_standard.get(key)
        if previous is not None and previous.shrn_iscd != record.shrn_iscd:
            raise IdentityReconciliationError(f"AMBIGUOUS_KIS_STANDARD_CODE:{key}")
        by_standard[key] = record

    reconciled: list[ReconciledInstrumentIdentity] = []
    seen_krx: set[str] = set()
    for record in krx_records:
        key = record.isu_cd.strip()
        if key in seen_krx:
            raise IdentityReconciliationError(f"DUPLICATE_KRX_ISU_CD:{key}")
        seen_krx.add(key)
        kis = by_standard.get(key)
        if kis is None:
            continue
        reconciled.append(ReconciledInstrumentIdentity(
            product_kind=record.product_kind,
            krx_isu_cd=key,
            kis_shrn_iscd=kis.shrn_iscd.strip(),
            kis_stnd_iscd=key,
        ))
    return tuple(reconciled)
