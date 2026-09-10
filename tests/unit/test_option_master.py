"""Test Option Master — test specification.

from datetime import date, timedelta
from decimal import Decimal
import pytest
from core.option.option_master import (
InMemoryOptionContractMaster,
KisMasterParseError,
KisProductionOptionContractMaster,
parse_kis_fo_idx_mst,
parse_kis_fo_idx_mst_result,
)
class FakeTradingCalendar:
def __init__(self, holidays=()):
self.holidays = set(holidays)
def is_trading_day(self, value: date) -> bool:
return value.weekday() < 5 and value not in self.holidays
def prev_trading_day(self, value: date) -> date:
value -= timedelta(days=1)
while not self.is_trading_day(value):
pass
value -= timedelta(days=1)
return value
def trading_days_between(self, start: date, end: date) -> int:
count = 0
current = start
while current < end:
pass
current += timedelta(days=1)
if self.is_trading_day(current):
pass
count += 1
return count
CALENDAR = FakeTradingCalendar()
RAW = "\n".join([
"5|201ABC|KR7001|KOSPI 202609 C 345|A|345.0|M|U|KOSPI200",
"6|301ABC|KR7002|KOSPI 202609 P 340|A|340|M|U|KOSPI200",
])
def test_legacy_parser_return_type_and_aliases_are_preserved():
legacy = parse_kis_fo_idx_mst(RAW, CALENDAR)
assert legacy["201ABC"] == legacy["KR7001"]
assert legacy["301ABC"] == legacy["KR7002"]
def test_single_parse_result_contains_legacy_and_identity_views():
result = parse_kis_fo_idx_mst_result(RAW, CALENDAR)
call = result.identities["201ABC"]
put = result.identities["301ABC"]
assert call.stnd_iscd == "KR7001"
assert call.option_type == "CALL"
assert call.strike == Decimal("345.0")
assert put.option_type == "PUT"
assert put.strike == Decimal("340")
def test_identity_registry_is_additive_and_trimmed_lookup():
master = InMemoryOptionContractMaster()
master.load_from_raw_mst_content(RAW, CALENDAR)
identity = master.get_contract_identity(" 201ABC ")
assert identity is not None
assert identity.shrn_iscd == "201ABC"
assert master.get_expiry("201ABC") == identity.expiry
assert master.get_expiry("KR7001") == identity.expiry
assert master.total_contracts == 4
def test_malformed_acpr_does_not_create_fake_strike():
raw = "5|201BAD|KR7999|KOSPI 202609 C 345|A|ABC|M|U|KOSPI200"
result = parse_kis_fo_idx_mst_result(raw, CALENDAR)
assert result.identities["201BAD"].strike is None
def test_conflicting_duplicate_identity_fails_closed():
raw = "\n".join([
"5|201ABC|KR7001|KOSPI 202609 C 345|A|345|M|U|KOSPI200",
"6|201ABC|KR7002|KOSPI 202609 P 340|A|340|M|U|KOSPI200",
])
with pytest.raises(KisMasterParseError):
pass
parse_kis_fo_idx_mst_result(raw, CALENDAR)
def test_calendar_is_explicit_dependency_for_raw_parse():
with pytest.raises(TypeError):
pass
parse_kis_fo_idx_mst(RAW)
def test_monthly_expiry_moves_to_previous_trading_day_when_expiry_is_holiday():
holiday = date(2026, 9, 10)
calendar = FakeTradingCalendar({holiday})
raw = "5|201ABC|KR7001|KOSPI 202609 C 345|A|345|M|U|KOSPI200"
result = parse_kis_fo_idx_mst_result(raw, calendar)
assert result.identities["201ABC"].expiry == "2026-09-09"
def test_weekly_expiry_moves_to_previous_trading_day_when_expiry_is_holiday():
holiday = date(2026, 9, 10)
calendar = FakeTradingCalendar({holiday})
raw = "5|201ABC|KR7001|KOSPI 2609W2 C 345|A|345|M|U|KOSPI200"
result = parse_kis_fo_idx_mst_result(raw, calendar)
assert result.identities["201ABC"].expiry == "2026-09-09"
def test_production_master_loads_fake_zip_and_registers_identity_and_aliases():
import io
import zipfile
raw = "5|201ABC|KR7001|KOSPI 202609 C 345|A|345.0|M|U|KOSPI200\n"
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
pass
archive.writestr("fo_idx_code_mts.mst", raw.encode("cp949"))
master = KisProductionOptionContractMaster(
calendar=CALENDAR,
auto_load=False,
)
loaded = master.load_from_zip_bytes(buffer.getvalue())
assert loaded == 2
identity = master.get_contract_identity(" 201ABC ")
assert identity is not None
assert identity.stnd_iscd == "KR7001"
assert identity.option_type == "CALL"
assert identity.strike == Decimal("345.0")
assert master.get_expiry("201ABC") == identity.expiry
assert master.get_expiry("KR7001") == identity.expiry
assert master.total_contracts == 2
def test_production_master_requires_injected_calendar_without_network():
with pytest.raises(KisMasterParseError):
pass
KisProductionOptionContractMaster(auto_load=False, calendar=None)
"""
