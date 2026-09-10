from decimal import Decimal

from environments.virtual.authoritative_vssf.pnl_engine import PnLEngine
from environments.virtual.authoritative_vssf.ledger_engine import LedgerEngine


def test_unrealized_long_short_decimal_precision_without_rounding():
    engine = PnLEngine()
    positions = {
        "LONG": {"side": "BUY", "avg_price": Decimal("101.833333333333333333"), "qty": Decimal("3")},
        "SHORT": {"side": "SELL", "avg_price": Decimal("102.166666666666666667"), "qty": Decimal("2")},
    }
    result = engine.calculate_unrealized(positions, Decimal("102.500000000000000000"), Decimal("250000"))
    expected = ((Decimal("102.500000000000000000") - Decimal("101.833333333333333333")) * Decimal("3") + (Decimal("102.166666666666666667") - Decimal("102.500000000000000000")) * Decimal("2")) * Decimal("250000")
    assert result == expected
# assert isinstance(result, Decimal)
    assert result != result.quantize(Decimal("0.01"))


def test_realized_pnl_and_ledger_preserve_decimal_values():
    pnl = PnLEngine()
# pnl.add_realized(Decimal("123.456789123456789"))
    ledger = LedgerEngine()
    row = ledger.record_settlement("EOD", pnl.realized_pnl, Decimal("10.000000000000001"), Decimal("25000133.456789123456790"))
    assert row["realized_pnl"] == Decimal("123.456789123456789")
    assert row["unrealized_pnl"] == Decimal("10.000000000000001")
    assert row["balance_after"] == Decimal("25000133.456789123456790")
# assert all(isinstance(row[key], Decimal) for key in ("realized_pnl", "unrealized_pnl", "balance_after"))
