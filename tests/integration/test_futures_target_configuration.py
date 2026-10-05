import pytest

from application.composition.futures_target_configuration import FuturesTargetConfiguration, FuturesTargetConfigurationError
from contracts.futures_contract_master import FuturesProductType


def test_target_configuration_requires_product_type_and_one_underlying_selector():
    with pytest.raises(FuturesTargetConfigurationError):
        FuturesTargetConfiguration()
    with pytest.raises(FuturesTargetConfigurationError):
        FuturesTargetConfiguration(underlying_short_code="U200")
    with pytest.raises(FuturesTargetConfigurationError):
        FuturesTargetConfiguration(underlying_short_code="U200", underlying_name="KOSPI200", product_type=FuturesProductType.STANDARD)


def test_short_code_and_product_type_are_explicit_selector_inputs():
    config = FuturesTargetConfiguration(underlying_short_code=" U200 ", product_type=FuturesProductType.STANDARD)
    assert config.selector_kwargs() == {"underlying_short_code": "U200", "product_type": FuturesProductType.STANDARD}


def test_name_and_product_type_are_explicit_selector_inputs():
    config = FuturesTargetConfiguration(underlying_name=" KOSPI200 ", product_type=FuturesProductType.MINI)
    assert config.selector_kwargs() == {"underlying_name": "KOSPI200", "product_type": FuturesProductType.MINI}


def test_whitespace_only_selector_is_not_accepted():
    with pytest.raises(FuturesTargetConfigurationError):
        FuturesTargetConfiguration(underlying_short_code="   ", underlying_name="   ", product_type=FuturesProductType.STANDARD)


def test_mini_contract_for_replay_month_uses_authoritative_master_record():
    from pathlib import Path
    from contracts.futures_contract_master import KisCurrentFuturesContractSource, parse_kis_futures_contracts

    raw = Path("fo_idx_code_mts.mst").read_bytes().decode("cp949", errors="replace")
    source = KisCurrentFuturesContractSource(
        parse_kis_futures_contracts(raw),
        underlying_short_code="2001",
        product_type=FuturesProductType.MINI,
    )

    contract = source.contract_for_month("202610")

    assert contract.shrn_iscd == "A05610"
    assert contract.product_type is FuturesProductType.MINI
