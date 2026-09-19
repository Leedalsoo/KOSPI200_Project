"""KRX/KIS identity reconciliation.

No implicit code conversion is permitted. A match is accepted only when the
authoritative KRX ISU_CD exactly equals a KIS stnd_iscd. Name similarity and
prefix heuristics are intentionally excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

ProductKind = Literal["FUTURES", "OPTION"]

_KRX_MONTH_TO_KIS_MONTH = {
    **{str(month): f"{month:02d}" for month in range(1, 10)},
    "A": "10",
    "B": "11",
    "C": "12",
}


def derive_kis_shrn_iscd(krx_isu_cd: str) -> str:
    """Convert a supported KRX derivative ISU code to its KIS short-code form.

    The conversion only rewrites the documented month-code position; it never
    invents contract attributes. The result must still be present in the
    authoritative KIS Master before it can be accepted as an identity.
    """
    code = krx_isu_cd.strip()
    if len(code) != 8 or code[4] not in _KRX_MONTH_TO_KIS_MONTH:
        raise IdentityReconciliationError("UNSUPPORTED_KRX_CODE_FORMAT")
    if code[0] == "A":
        if code[5:] != "000":
            raise IdentityReconciliationError("UNSUPPORTED_KRX_CODE_FORMAT")
        return code[:4] + _KRX_MONTH_TO_KIS_MONTH[code[4]]
    if code[0] in {"B", "C"}:
        return code[:4] + _KRX_MONTH_TO_KIS_MONTH[code[4]] + code[5:]
    raise IdentityReconciliationError("UNSUPPORTED_KRX_CODE_FORMAT")


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


def reconcile_krx_to_kis_short_code(
    krx_records: Iterable[KrxInstrumentRecord],
    kis_records: Iterable[KisMasterIdentityRecord],
) -> tuple[ReconciledInstrumentIdentity, ...]:
    """Reconcile KRX ISU codes through the verified KRX→KIS short-code form.

    A derived short code is accepted only when it exists uniquely in the KIS
    Master; absence remains an unresolved identity rather than a synthetic one.
    """
    by_short: dict[str, KisMasterIdentityRecord] = {}
    for record in kis_records:
        key = record.shrn_iscd.strip()
        previous = by_short.get(key)
        if previous is not None and previous.stnd_iscd != record.stnd_iscd:
            raise IdentityReconciliationError(f"AMBIGUOUS_KIS_SHORT_CODE:{key}")
        by_short[key] = record

    reconciled: list[ReconciledInstrumentIdentity] = []
    seen_krx: set[str] = set()
    for record in krx_records:
        key = record.isu_cd.strip()
        if key in seen_krx:
            raise IdentityReconciliationError(f"DUPLICATE_KRX_ISU_CD:{key}")
        seen_krx.add(key)
        kis_code = derive_kis_shrn_iscd(key)
        kis = by_short.get(kis_code)
        if kis is None or not kis.stnd_iscd:
            continue
        reconciled.append(ReconciledInstrumentIdentity(
            product_kind=record.product_kind,
            krx_isu_cd=key,
            kis_shrn_iscd=kis.shrn_iscd,
            kis_stnd_iscd=kis.stnd_iscd,
            matched_by="KRX_CODE_MONTH_ENCODING_TO_KIS_SHRN_ISCD",
        ))
    return tuple(reconciled)
