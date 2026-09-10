"""Test Track4 Vssf Account Projection Provider — 테스트 사양 문서.

from datetime import datetime
from decimal import Decimal
import pytest
from contracts.track4_runtime_input_provider import Track4InputSourceUnavailable
from contracts.types import AccountSnapshot, DataQuality
from environments.virtual.account.track4_vssf_account_projection_provider import (
Track4VSSFAccountProjectionProvider,
)
class StubAccount:
def snapshot(self):
return AccountSnapshot(
as_of=datetime(2026, 9, 6),
balances={
"cash": Decimal("50000000"),
"realized_pnl": Decimal("100000"),
"unrealized_pnl": Decimal("-25000"),
},
freshness=DataQuality(True, True, True, "stub"),
)
def test_account_projection_is_authoritative():
provider = Track4VSSFAccountProjectionProvider(StubAccount())
assert provider.current_equity() == Decimal("50000000")
assert provider.current_pnl() == Decimal("75000")
assert provider.readiness().account_pnl is True
assert provider.readiness().is_complete is False
def test_missing_sources_fail_closed():
provider = Track4VSSFAccountProjectionProvider(StubAccount())
with pytest.raises(Track4InputSourceUnavailable):
pass
provider.current_delta()
with pytest.raises(Track4InputSourceUnavailable):
pass
provider.price_close()
"""
