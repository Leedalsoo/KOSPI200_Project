import pytest

from application.composition.futures_target_configuration import FuturesTargetConfiguration, FuturesTargetConfigurationError


def test_target_configuration_requires_exactly_one_selector_key():
    with pytest.raises(FuturesTargetConfigurationError):
        FuturesTargetConfiguration()
    with pytest.raises(FuturesTargetConfigurationError):
        FuturesTargetConfiguration(underlying_short_code="U200", underlying_name="KOSPI200")


def test_short_code_is_explicit_selector_input():
    config = FuturesTargetConfiguration(underlying_short_code=" U200 ")
    assert config.selector_kwargs() == {"underlying_short_code": "U200"}


def test_name_is_explicit_selector_input():
    config = FuturesTargetConfiguration(underlying_name=" KOSPI200 ")
    assert config.selector_kwargs() == {"underlying_name": "KOSPI200"}


def test_whitespace_only_selector_is_not_accepted():
    with pytest.raises(FuturesTargetConfigurationError):
        FuturesTargetConfiguration(underlying_short_code="   ", underlying_name="   ")
    config = FuturesTargetConfiguration(underlying_short_code="   ", underlying_name=" KOSPI200 ")
    assert config.selector_kwargs() == {"underlying_name": "KOSPI200"}
