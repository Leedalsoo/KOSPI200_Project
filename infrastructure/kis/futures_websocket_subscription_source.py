"""Authoritative current KOSPI200 futures symbols for WebSocket subscriptions.

The KIS futures master is the sole symbol source; callers must not hard-code
front-contract broker symbols.
"""
from __future__ import annotations

from pathlib import Path

from contracts.futures_contract_master import (
    FuturesProductType,
    KisCurrentFuturesContractSource,
    parse_kis_futures_contracts,
)


def current_kospi200_futures_symbols(
    root: Path,
) -> tuple[tuple[FuturesProductType, str], ...]:
    master_path = root / "fo_idx_code_mts.mst"
    if not master_path.is_file():
        raise RuntimeError("KIS_FUTURES_MASTER_REQUIRED")
    raw = master_path.read_bytes().decode("cp949", errors="replace")
    source = KisCurrentFuturesContractSource(parse_kis_futures_contracts(raw))
    result = []
    for product_type in (FuturesProductType.STANDARD, FuturesProductType.MINI):
        contract = source.with_target(
            underlying_short_code="2001",
            product_type=product_type,
        ).current_contract()
        result.append((product_type, contract.shrn_iscd))
    return tuple(result)
