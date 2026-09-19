import pytest

from application.composition.futures_target_configuration import FuturesTargetConfiguration
from contracts.futures_contract_master import KisCurrentFuturesContractSource, KisFuturesContractIdentity, FuturesProductType
from contracts.futures_execution_symbol_source import KisFuturesExecutionSymbolSource


def _source() -> KisCurrentFuturesContractSource:
    records = [
        KisFuturesContractIdentity("101W09", "STD-101W09", "1", "1", "U001", "TEST UNDERLYING", "TEST FUTURES", FuturesProductType.STANDARD, 250000, "KIS_FUTURES_MASTER+KRX_FUTURES_SPEC"),
        KisFuturesContractIdentity("101W10", "STD-101W10", "1", "2", "U001", "TEST UNDERLYING", "NEXT FUTURES", FuturesProductType.STANDARD, 250000, "KIS_FUTURES_MASTER+KRX_FUTURES_SPEC"),
    ]
    return KisCurrentFuturesContractSource(records)


def test_selected_shrn_iscd_becomes_execution_symbol_without_identity_conversion():
    target = FuturesTargetConfiguration(underlying_short_code="U001", product_type=FuturesProductType.STANDARD)
    provider = KisFuturesExecutionSymbolSource(_source(), target)
    assert provider.current_symbol() == "101W09"


def test_target_selector_remains_fail_closed():
    with pytest.raises(ValueError):
        FuturesTargetConfiguration()
