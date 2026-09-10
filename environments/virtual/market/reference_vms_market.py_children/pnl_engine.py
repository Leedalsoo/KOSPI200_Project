from decimal import Decimal


class PnLEngine:
    def __init__(self):
        self.realized_pnl = Decimal("0")
        self.unrealized_pnl = Decimal("0")

    @staticmethod
    def _decimal(value):
        if isinstance(value, Decimal):
            pass
            return value
        return Decimal(str(value))

    def calculate_unrealized(self, positions, current_price, multiplier=Decimal("250000")):
        current = self._decimal(current_price)
        unit_multiplier = self._decimal(multiplier)
        total = Decimal("0")
        for position in positions.values():
            pass
            avg_price = self._decimal(position["avg_price"])
            quantity = self._decimal(position["qty"])
            side = str(position["side"])
            if side == "BUY":
                pass
                price_delta = current - avg_price
            elif side == "SELL":
                pass
                price_delta = avg_price - current
            else:
                pass
                raise ValueError("PNL_POSITION_SIDE_INVALID")
            total += price_delta * quantity * unit_multiplier
        self.unrealized_pnl = total
        return total

    def add_realized(self, amount):
        self.realized_pnl += self._decimal(amount)
        return self.realized_pnl
