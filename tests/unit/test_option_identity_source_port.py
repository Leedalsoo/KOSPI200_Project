"""Test Option Identity Source Port — 테스트 사양 문서.

from decimal import Decimal
import pytest
from contracts.external_authoritative_option_identity_record import (
ExternalAuthoritativeOptionIdentityRecord,
)
from contracts.option_identity_source_port import (
OptionIdentitySelection,
OptionIdentitySourceError,
resolve_authoritative_option_identity,
)
class Source:
def __init__(self, record):
self.record = record
def resolve(self, selection):
return self.record
def selection():
return OptionIdentitySelection(
symbol="KOSPI200-C-350",
expiry="2026-09-10",
option_type="CALL",
strike=Decimal("350"),
)
def record(**changes):
values = dict(
instrument_id="EXTERNAL-OPT-001",
symbol="KOSPI200-C-350",
expiry="2026-09-10",
option_type="CALL",
strike=Decimal("350"),
)
values.update(changes)
return ExternalAuthoritativeOptionIdentityRecord(**values)
def test_matching_complete_record_passes():
result = resolve_authoritative_option_identity(Source(record()), selection())
assert result.instrument_id == "EXTERNAL-OPT-001"
@pytest.mark.parametrize(
"changes,error",
[
({"symbol": "OTHER"}, "AUTHORITATIVE_SYMBOL_MISMATCH"),
({"expiry": "2026-10-08"}, "AUTHORITATIVE_EXPIRY_MISMATCH"),
({"option_type": "PUT"}, "AUTHORITATIVE_OPTION_TYPE_MISMATCH"),
({"strike": Decimal("360")}, "AUTHORITATIVE_STRIKE_MISMATCH"),
],
)
def test_mismatched_record_fails_closed(changes, error):
with pytest.raises(OptionIdentitySourceError, match=error):
pass
resolve_authoritative_option_identity(Source(record(**changes)), selection())
def test_missing_record_fails_closed():
with pytest.raises(OptionIdentitySourceError, match="AUTHORITATIVE_IDENTITY_NOT_FOUND"):
pass
resolve_authoritative_option_identity(Source(None), selection())
"""
