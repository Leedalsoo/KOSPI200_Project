from decimal import Decimal

MULTIPLIER = Decimal("250000")

class MarginEngine:
    def __init__(self, initial_capital=25000000.0):
        self.initial_capital = Decimal(str(initial_capital))

    @staticmethod
    def _decimal(value):
        return value if isinstance(value, Decimal) else Decimal(str(value))

    def calculate_order_margin(self, command):
        identity = getattr(command, "instrument_identity", None)
        multiplier = getattr(identity, "contract_multiplier", None)
        multiplier = getattr(command, "contract_multiplier", multiplier)
        asset_type = getattr(getattr(command, "asset_type", None), "value", getattr(command, "asset_type", None))
        if asset_type == "FUTURES" and multiplier is None:
            raise ValueError("FUTURES_CONTRACT_MULTIPLIER_REQUIRED")
        multiplier = self._decimal(multiplier if multiplier is not None else MULTIPLIER)
        return self._decimal(command.price) * self._decimal(command.qty) * multiplier

    def calculate_used_margin(self, positions, multiplier=MULTIPLIER):
        unit_multiplier = self._decimal(multiplier)
        total = Decimal("0")
        for position in positions.values():
            position_multiplier = self._decimal(position.get("contract_multiplier", unit_multiplier)) if isinstance(position, dict) else unit_multiplier
            total += self._decimal(position["avg_price"]) * self._decimal(position["qty"]) * position_multiplier
        return total

    def calculate_free_margin(self, total_equity, used_margin):
        return max(Decimal("0"), self._decimal(total_equity) - self._decimal(used_margin))
