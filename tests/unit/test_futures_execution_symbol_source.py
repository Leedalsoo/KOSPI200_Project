import pytest

from application.composition.futures_target_configuration import FuturesTargetConfiguration
from contracts.futures_contract_master import KisCurrentFuturesContractSource, KisFuturesContractIdentity
from contracts.futures_execution_symbol_source import KisFuturesExecutionSymbolSource


def _source() -> KisCurrentFuturesContractSource:
    records = [
        KisFuturesContractIdentity(
            shrn_iscd="101W09",
            stnd_iscd="STD-101W09",
            info_type="1",
            mmsc_cls_code="1",
            unas_shrn_iscd="U001",
            unas_kor_name="TEST UNDERLYING",
            kor_name="TEST FUTURES",
        ),
        KisFuturesContractIdentity(
            shrn_iscd="101W10",
            stnd_iscd="STD-101W10",
            info_type="1",
            mmsc_cls_code="2",
            unas_shrn_iscd="U001",
            unas_kor_name="TEST UNDERLYING",
            kor_name="NEXT FUTURES",
        ),
    ]
    return KisCurrentFuturesContractSource(records)


def test_selected_shrn_iscd_becomes_execution_symbol_without_identity_conversion():
    target = FuturesTargetConfiguration(underlying_short_code="U001")
    provider = KisFuturesExecutionSymbolSource(_source(), target)

    assert provider.current_symbol() == "101W09"


def test_target_selector_remains_fail_closed():
    with pytest.raises(ValueError):
        FuturesTargetConfiguration()
