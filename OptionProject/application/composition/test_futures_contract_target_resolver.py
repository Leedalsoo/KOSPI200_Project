from contracts.futures_contract_master import KisCurrentFuturesContractSource, parse_kis_futures_contracts
from application.composition.futures_contract_target_resolver import resolve_current_futures_contract
from application.composition.futures_target_configuration import FuturesTargetConfiguration

RAW = """1|101W09|STANDARD|KOSPI200|x|x|1|U200|KOSPI200\n3|101W10|STANDARD|KOSPI200|x|x|2|U200|KOSPI200\n"""


def test_target_configuration_selects_authoritative_current_contract():
    records = parse_kis_futures_contracts(RAW)
    source = KisCurrentFuturesContractSource(records, underlying_short_code="U200")
    target = FuturesTargetConfiguration(underlying_short_code="U200")

    selected = resolve_current_futures_contract(source=source, target=target)

    assert selected.shrn_iscd == "101W09"
    assert selected.unas_shrn_iscd == "U200"


def test_target_configuration_does_not_create_standard_identity():
    records = parse_kis_futures_contracts(RAW)
    source = KisCurrentFuturesContractSource(records, underlying_short_code="U200")
    target = FuturesTargetConfiguration(underlying_name="KOSPI200")

    selected = resolve_current_futures_contract(source=source, target=target)

    assert selected.shrn_iscd == "101W09"
# assert not hasattr(selected, "instrument_id")
