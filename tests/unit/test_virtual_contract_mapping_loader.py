import pytest

from application.composition.virtual_contract_mapping_loader import (
VirtualContractMappingConfigurationError,
VirtualContractMappingLoader,
)


def test_loads_explicit_contract_mappings():
    mappings = VirtualContractMappingLoader().load(
        {
            "contract_mappings": [
                {
                    "scenario_contract_key": "scenario-call",
                    "shrn_iscd": "AUTHORITATIVE_CODE",
                }
            ]
        }
    )

    assert mappings["scenario-call"].scenario_contract_key == "scenario-call"
    assert mappings["scenario-call"].shrn_iscd == "AUTHORITATIVE_CODE"


@pytest.mark.parametrize(
    "source,error",
    [
        ({"contract_mappings": []}, None),
        (
            {"contract_mappings": [{"scenario_contract_key": "", "shrn_iscd": "X"}]},
            "SCENARIO_CONTRACT_KEY_REQUIRED",
        ),
        (
            {"contract_mappings": [{"scenario_contract_key": "k", "shrn_iscd": ""}]},
            "SHRN_ISCD_REQUIRED",
        ),
    ],
)
def test_loader_is_fail_closed(source, error):
    loader = VirtualContractMappingLoader()
    if error is None:
        pass
        assert loader.load(source) == {}
    else:
        pass
        with pytest.raises(VirtualContractMappingConfigurationError, match=error):
            pass
loader.load(source)


def test_duplicate_key_is_rejected():
    source = {
        "contract_mappings": [
            {"scenario_contract_key": "k", "shrn_iscd": "A"},
            {"scenario_contract_key": "k", "shrn_iscd": "B"},
        ]
    }

    with pytest.raises(
VirtualContractMappingConfigurationError,
        match="DUPLICATE_SCENARIO_CONTRACT_KEY",
    ):
        VirtualContractMappingLoader().load(source)
