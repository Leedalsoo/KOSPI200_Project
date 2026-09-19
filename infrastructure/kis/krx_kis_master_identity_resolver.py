from __future__ import annotations

from typing import Any

from contracts.krx_kis_identity_reconciliation import (
    IdentityReconciliationError,
    derive_kis_shrn_iscd,
)


class KRXKISMasterIdentityResolver:
    """Resolve KRX derivative codes against an authoritative KIS Master.

    The KRX code is only a lookup key. Contract identity is accepted only when
    the derived KIS short code exists in the injected master.
    """

    def __init__(self, kis_master: Any, krx_master: Any | None = None) -> None:
        if kis_master is None or not callable(getattr(kis_master, "get_contract_identity", None)):
            raise IdentityReconciliationError("KIS_MASTER_REQUIRED")
        if krx_master is not None and not callable(getattr(krx_master, "get_contract_identity", None)):
            raise IdentityReconciliationError("KRX_MASTER_INVALID")
        self._kis_master = kis_master
        self._krx_master = krx_master

    def get_contract_identity(self, krx_isu_cd: str) -> Any | None:
        code = krx_isu_cd.strip()
        if self._krx_master is not None:
            direct = self._krx_master.get_contract_identity(code)
            if direct is not None:
                return direct
        kis_shrn_iscd = derive_kis_shrn_iscd(code)
        return self._kis_master.get_contract_identity(kis_shrn_iscd)
