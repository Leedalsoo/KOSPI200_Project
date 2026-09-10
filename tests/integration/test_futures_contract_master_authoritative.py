import pytest

from contracts.futures_contract_master import (
FuturesContractMasterError,
KisCurrentFuturesContractSource,
parse_kis_futures_contracts,
select_current_futures_contract,

)

RAW = """1|101S12|STD-NEAR|KOSPI FUT|0|0|1|U200|KOSPI200

1|101S13|STD-NEXT|KOSPI FUT|0|0|2|U200|KOSPI200

5|201ABC|OPT|CALL|0|350|1|U200|KOSPI200

3|301S12|STAR FUT|STAR FUT|0|0|1|USTAR|STAR"""

def test_official_futures_info_types_are_projected():
    pass
assert [r.shrn_iscd for r in parse_kis_futures_contracts(RAW)] == ["101S12", "101S13", "301S12"]

def test_month_code_one_is_authoritative_recent_month():
    pass
current = select_current_futures_contract(parse_kis_futures_contracts(RAW), underlying_short_code="U200")
assert current.shrn_iscd == "101S12"

def test_selector_requires_unique_target_product():
    pass
with pytest.raises(FuturesContractMasterError, match="CURRENT_FUTURES_NOT_UNIQUE"):
    pass
select_current_futures_contract(parse_kis_futures_contracts(RAW))

def test_source_returns_selected_identity():
    pass
source = KisCurrentFuturesContractSource(parse_kis_futures_contracts(RAW), underlying_name="KOSPI200")
assert source.current_contract().stnd_iscd == "STD-NEAR"

def test_no_yyyy_mm_assumption_is_used():
    pass
with pytest.raises(FuturesContractMasterError):
    pass
select_current_futures_contract(parse_kis_futures_contracts("1|101S12|STD|FUT|0|0|X|U200|KOSPI200"), underlying_short_code="U200")
