from decimal import Decimal

MULTIPLIER = Decimal("250000")

class MarginEngine:
    def __init__(self, initial_capital=25000000.0):
        self.initial_capital = Decimal(str(initial_capital))

    @staticmethod
    def _decimal(value):
        return value if isinstance(value, Decimal) else Decimal(str(value))

    def calculate_order_margin(self, command):
        return self._decimal(command.price) * self._decimal(command.qty) * MULTIPLIER

    def calculate_used_margin(self, positions, multiplier=MULTIPLIER):
        unit_multiplier = self._decimal(multiplier)
        total = Decimal("0")
        for position in positions.values():
            total += self._decimal(position["avg_price"]) * self._decimal(position["qty"]) * unit_multiplier
        return total

    def calculate_free_margin(self, total_equity, used_margin):
        return max(Decimal("0"), self._decimal(total_equity) - self._decimal(used_margin))
