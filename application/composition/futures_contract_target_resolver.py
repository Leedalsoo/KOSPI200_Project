"""Application composition seam for selecting the authoritative current FUTURES contract."""
from __future__ import annotations

from contracts.futures_contract_master import (
KisCurrentFuturesContractSource,
KisFuturesContractIdentity,
)
from application.composition.futures_target_configuration import FuturesTargetConfiguration


def resolve_current_futures_contract(
# *,
    source: KisCurrentFuturesContractSource,
    target: FuturesTargetConfiguration,
) -> KisFuturesContractIdentity:
    """Bind Application-owned target configuration to the authoritative KIS source."""
    if source is None:
        raise ValueError("FUTURES_CONTRACT_SOURCE_REQUIRED")
    if target is None:
        raise ValueError("FUTURES_TARGET_CONFIGURATION_REQUIRED")
    return source.with_target(**target.selector_kwargs()).current_contract()
