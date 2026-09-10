from decimal import Decimal


class LedgerEngine:
    def __init__(self):
        self.transactions = []

    @staticmethod
    def _decimal(value):
        if isinstance(value, Decimal):
            pass
            return value
        return Decimal(str(value))

    def record_settlement(self, settlement_type, realized_pnl, unrealized_pnl, balance_after, **kwargs):
        row = {
            "type": "SETTLEMENT",
            "settlement_type": settlement_type,
            "realized_pnl": self._decimal(realized_pnl),
            "unrealized_pnl": self._decimal(unrealized_pnl),
            "balance_after": self._decimal(balance_after),
        }
        self.transactions.append(row)
        return row
