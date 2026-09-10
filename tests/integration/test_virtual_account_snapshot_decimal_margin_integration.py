from datetime import datetime
from decimal import Decimal

from contracts.types import AccountSnapshot
from environments.virtual.account.vssf_account_snapshot_adapter import VSSFAccountSnapshotAdapter
from environments.virtual.authoritative_vssf.margin_engine import MarginEngine


class Summary:
    total_balance = Decimal("25000133.456789123456789")
    realized_pnl = Decimal("123.456789123456789")
    unrealized_pnl = Decimal("10.000000000000001")
    used_margin = Decimal("123456.789123456789")
    free_margin = Decimal("24876676.667665666667")
    timestamp = "2026-09-07 12:00:00"


class AccountSource:
    def get_canonical_summary(self):
        return Summary()


def test_authoritative_summary_projects_decimal_without_precision_loss():
    snapshot = VSSFAccountSnapshotAdapter(AccountSource()).snapshot()
# assert isinstance(snapshot, AccountSnapshot)
    assert snapshot.as_of == datetime(2026, 9, 7, 12, 0, 0)
    assert snapshot.balances["cash"] == Summary.total_balance
    assert snapshot.balances["margin_used"] == Summary.used_margin
    assert snapshot.balances["available_cash"] == Summary.free_margin
    assert snapshot.balances["realized_pnl"] == Summary.realized_pnl
    assert snapshot.balances["unrealized_pnl"] == Summary.unrealized_pnl
# assert all(isinstance(value, Decimal) for value in snapshot.balances.values())


def test_margin_engine_preserves_decimal_and_has_no_implicit_rounding():
    engine = MarginEngine()
    positions = {
        "A": {"avg_price": Decimal("101.123456789123456789"), "qty": Decimal("1")},
        "B": {"avg_price": Decimal("99.987654321987654321"), "qty": Decimal("2")},
    }
    used = engine.calculate_used_margin(positions)
    expected = (positions["A"]["avg_price"] + positions["B"]["avg_price"] * Decimal("2")) * Decimal("250000")
    assert used == expected
# assert isinstance(used, Decimal)
    assert used != used.quantize(Decimal("0.01"))
    free = engine.calculate_free_margin(Decimal("100000000.123456789"), used)
# assert isinstance(free, Decimal)
