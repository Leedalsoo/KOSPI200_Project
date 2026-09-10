"""Test Virtual Account To Risk Input Decimal Integration — 테스트 사양 문서.

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from contracts.types import AccountSnapshot, DataQuality
from core.risk.risk_input import account_snapshot_to_risk_input
from environments.virtual.account.vssf_account_snapshot_adapter import VSSFAccountSnapshotAdapter
@dataclass
class Summary:
total_balance: Decimal = Decimal("25000133.456789123456789")
realized_pnl: Decimal = Decimal("123.456789123456789")
unrealized_pnl: Decimal = Decimal("10.000000000000001")
used_margin: Decimal = Decimal("123456.789123456789")
free_margin: Decimal = Decimal("24876676.667665666667")
timestamp: str = "2026-09-07 12:00:00"
class AccountSource:
def get_canonical_summary(self):
return Summary()
def test_authoritative_account_snapshot_to_risk_input_preserves_decimal_and_semantics():
snapshot = VSSFAccountSnapshotAdapter(AccountSource()).snapshot()
risk = account_snapshot_to_risk_input(snapshot)
assert risk.total_balance == Summary.total_balance
assert risk.realized_pnl == Summary.realized_pnl
assert risk.used_margin == Summary.used_margin
assert risk.free_margin == Summary.free_margin
assert all(isinstance(value, Decimal) for value in (
risk.total_balance,
risk.realized_pnl,
risk.used_margin,
risk.free_margin,
))
def test_risk_input_semantic_mapping_is_not_recalculated():
snapshot = AccountSnapshot(
as_of=datetime(2026, 9, 7, 12, 0, 0),
balances={
"cash": Decimal("101.111111111111111111"),
"margin_used": Decimal("22.222222222222222222"),
"available_cash": Decimal("78.888888888888888889"),
"realized_pnl": Decimal("1.234567891234567891"),
"unrealized_pnl": Decimal("9.999999999999999999"),
},
freshness=DataQuality(True, True, True, "integration"),
)
risk = account_snapshot_to_risk_input(snapshot)
assert risk.total_balance == snapshot.balances["cash"]
assert risk.used_margin == snapshot.balances["margin_used"]
assert risk.free_margin == snapshot.balances["available_cash"]
assert risk.realized_pnl == snapshot.balances["realized_pnl"]
"""
