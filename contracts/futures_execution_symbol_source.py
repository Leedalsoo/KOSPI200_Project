"""Authoritative KIS FUTURES execution/Risk symbol projection."""
from __future__ import annotations

from typing import Any

from contracts.futures_contract_master import KisCurrentFuturesContractSource


class FuturesExecutionSymbolSourceError(ValueError):
    pass


class KisFuturesExecutionSymbolSource:
    """Expose the selected KIS short product code without creating Standard identity."""

    def __init__(
        self,
        source: KisCurrentFuturesContractSource,
        target: Any,
    ) -> None:
        self._source = source
        self._target = target

    def current_symbol(self) -> str:
        if self._source is None:
            raise FuturesExecutionSymbolSourceError("FUTURES_CONTRACT_SOURCE_REQUIRED")
        if self._target is None or not hasattr(self._target, "selector_kwargs"):
            raise FuturesExecutionSymbolSourceError("FUTURES_TARGET_CONFIGURATION_REQUIRED")
        contract = self._source.with_target(**self._target.selector_kwargs()).current_contract()
        symbol = contract.shrn_iscd.strip()
        if not symbol:
            raise FuturesExecutionSymbolSourceError("FUTURES_EXECUTION_SYMBOL_REQUIRED")
        return symbol
