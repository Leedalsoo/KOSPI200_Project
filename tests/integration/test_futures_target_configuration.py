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
