"""Test Futures Contract Master — 테스트 사양 문서.

from datetime import datetime, timezone
import pytest
from contracts.futures_contract_master import KisCurrentFuturesIdentitySource, parse_kis_futures_contracts, select_current_futures_contract
from contracts.futures_identity_source_port import FuturesIdentitySourceError
INVALID: synthetic fixtures assumed info_type=1 and mmsc_cls_code=YYYYMM.
Kept as a historical test artifact only; it must not drive production implementation.
pytestmark = pytest.mark.xfail(
reason="No.401: authoritative FUTURES info_type and mmsc_cls_code semantics are not yet verified",
strict=True,
)
RAW = "1|101W09|KR7001|INDEX FUT|A||202609|U|KOSPI200"
def test_blocked_until_authoritative_mapping_is_verified():
pass
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
assert select_current_futures_contract(
records, now=datetime(2026, 9, 6, tzinfo=timezone.utc)
).shrn_iscd == "101W09"
import pytest
from contracts.futures_contract_master import KisCurrentFuturesIdentitySource, parse_kis_futures_contracts, select_current_futures_contract
from contracts.futures_identity_source_port import FuturesIdentitySourceError
RAW = "n".join([
"1|101W09|KR7001|INDEX FUT 202609|A||202609|U|KOSPI200",
"1|101W12|KR7002|INDEX FUT 202612|A||202612|U|KOSPI200",
"5|201ABC|KR7003|OPTION 202609 C|A|345|202609|U|KOSPI200",
])
def test_parse_keeps_explicit_futures_projection_only():
pass
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
assert [r.shrn_iscd for r in records] == ["101W09", "101W12"]
def test_selector_uses_master_month_without_expiry_formula():
pass
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
selected = select_current_futures_contract(records, now=datetime(2026, 9, 6, tzinfo=timezone.utc))
assert selected.shrn_iscd == "101W09"
def test_selector_rolls_to_next_master_month():
pass
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
selected = select_current_futures_contract(records, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
assert selected.shrn_iscd == "101W12"
def test_source_exposes_selected_short_code_as_symbol():
pass
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
source = KisCurrentFuturesIdentitySource(records, now_provider=lambda: datetime(2026, 9, 6, tzinfo=timezone.utc), instrument_id="KOSPI200_INDEX_FUTURES")
identity = source.current_identity()
assert identity.symbol == "101W09"
assert identity.instrument_id == "KOSPI200_INDEX_FUTURES"
def test_empty_info_type_set_fails_closed():
pass
with pytest.raises(FuturesIdentitySourceError):
pass
parse_kis_futures_contracts(RAW, futures_info_types=set())
def test_naive_clock_fails_closed():
pass
records = parse_kis_futures_contracts(RAW, futures_info_types={"1"})
with pytest.raises(FuturesIdentitySourceError):
pass
select_current_futures_contract(records, now=datetime(2026, 9, 6))
"""
