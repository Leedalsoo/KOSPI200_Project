from __future__ import annotations

from datetime import datetime

from contracts.futures_contract_master import KisCurrentFuturesContractSource
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from application.composition.futures_contract_target_resolver import resolve_current_futures_contract
from application.composition.futures_target_configuration import FuturesTargetConfiguration


class KisFuturesIdentitySource:
    """Compose KIS contract identity with the authoritative KRX product specification."""

    def __init__(self, source: KisCurrentFuturesContractSource, target: FuturesTargetConfiguration) -> None:
        self._source = source
        self._target = target

    def current_identity(self) -> FuturesInstrumentIdentity:
        contract = resolve_current_futures_contract(source=self._source, target=self._target)
        return self._to_identity(contract)

    def identity_for_as_of(self, as_of: datetime) -> FuturesInstrumentIdentity:
        if as_of is None:
            raise ValueError("FUTURES_AS_OF_REQUIRED")
        contract = self._source.with_target(**self._target.selector_kwargs()).contract_for_month(
            as_of.strftime("%Y%m")
        )
        return self._to_identity(contract)

    def identity_for_observed_symbol(self, shrn_iscd: str) -> FuturesInstrumentIdentity:
        return self._to_identity(self._source.contract_for_symbol(shrn_iscd))

    @staticmethod
    def _to_identity(contract) -> FuturesInstrumentIdentity:
        if contract.product_type is None or contract.contract_multiplier is None:
            raise ValueError("FUTURES_PRODUCT_SPEC_UNAVAILABLE")
        return FuturesInstrumentIdentity(
            instrument_id=contract.shrn_iscd,
            symbol=contract.shrn_iscd,
            product_type=contract.product_type,
            contract_multiplier=contract.contract_multiplier,
            identity_source=contract.identity_source or "KIS_FUTURES_MASTER+KRX_FUTURES_SPEC",
        )
