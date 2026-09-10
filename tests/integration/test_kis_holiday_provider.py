"""Test Kis Holiday Provider — 테스트 사양 문서.

from datetime import date
from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.holiday_provider import (
KISHolidayProvider,
KISHolidayUnavailableError,
parse_kis_holiday_output,
)
def test_parse_kis_holiday_output_extracts_only_closed_days():
result = parse_kis_holiday_output([
{"bass_dt": "20260101", "opnd_yn": "N"},
{"bass_dt": "20260102", "opnd_yn": "Y"},
])
assert result == {date(2026, 1, 1)}
def test_response_load_preserves_holiday_query_contract():
provider = KISHolidayProvider()
count = provider.load_from_response_data({
"rt_cd": "0",
"output": [{"bass_dt": "20260101", "opnd_yn": "N"}],
}, year=2026)
assert count == 1
assert provider.is_holiday(date(2026, 1, 1))
assert provider.is_loaded
def test_strict_mode_rejects_unloaded_year():
provider = KISHolidayProvider(strict_mode=True)
try:
pass
provider.is_holiday(date(2026, 1, 1))
except KISHolidayUnavailableError:
pass
pass
else:
pass
raise AssertionError("strict mode must reject unavailable holiday data")
def test_api_load_uses_auth_headers_and_continuation_free_response():
class Response:
def read(self):
return b'{"rt_cd":"0","output":[{"bass_dt":"20260101","opnd_yn":"N"}]}'
def __enter__(self):
return self
def __exit__(self, *args):
return False
auth = KISAuthManager(
app_key="key",
app_secret="secret",
cache_file_path=None,
)
auth.get_auth_headers = lambda tr_id="": {"tr_id": tr_id}  # test transport boundary
provider = KISHolidayProvider(
auth_manager=auth,
urlopen=lambda request, timeout: Response(),
)
assert provider.load_from_kis_api(2026) == 1
assert provider.get_holidays_for_year(2026) == {date(2026, 1, 1)}
"""
