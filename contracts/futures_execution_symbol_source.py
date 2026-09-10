"""Authoritative KIS FUTURES execution/Risk symbol projection."""
from __future__ import annotations

from contracts.futures_contract_master import KisCurrentFuturesContractSource
from application.composition.futures_contract_target_resolver import resolve_current_futures_contract
from application.composition.futures_target_configuration import FuturesTargetConfiguration


class FuturesExecutionSymbolSourceError(ValueError):
    pass


class KisFuturesExecutionSymbolSource:
    """Expose the selected KIS short product code without creating Standard identity."""

    def __init__(
        self,
        source: KisCurrentFuturesContractSource,
        target: FuturesTargetConfiguration,
    ) -> None:
        self._source = source
        self._target = target

    def current_symbol(self) -> str:
        contract = resolve_current_futures_contract(
            source=self._source,
            target=self._target,
        )
        symbol = contract.shrn_iscd.strip()
        if not symbol:
            raise FuturesExecutionSymbolSourceError("FUTURES_EXECUTION_SYMBOL_REQUIRED")
        return symbol
