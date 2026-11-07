class PositionManager:
    def __init__(self):
        self.positions = {}

    def update_market_price(self, symbol, price):
        position = self.positions.get(symbol)
        if position is not None:
            position["mark_price"] = price

    def update_position(self, symbol, side, qty, price, **kwargs):
        if qty <= 0:
            return 0.0
        requested_multiplier = kwargs.get("contract_multiplier")
        requested_multiplier = float(requested_multiplier) if requested_multiplier is not None else None
        if requested_multiplier is not None and requested_multiplier <= 0:
            raise ValueError("CONTRACT_MULTIPLIER_MUST_BE_POSITIVE")
        p = self.positions.get(symbol)
        if p is None:
            self.positions[symbol] = {
                "qty": qty, "avg_price": price, "side": side,
                "contract_multiplier": requested_multiplier or 250000.0,
            }
            return 0.0

        stored_multiplier = float(p.get("contract_multiplier", 250000.0))
        if requested_multiplier is not None and requested_multiplier != stored_multiplier:
            raise ValueError("POSITION_CONTRACT_MULTIPLIER_MISMATCH")
        if p["side"] == side:
            total = p["qty"] + qty
            p["avg_price"] = (p["avg_price"] * p["qty"] + price * qty) / total
            p["qty"] = total
            p["contract_multiplier"] = stored_multiplier
            p.pop("mark_price", None)
            return 0.0

        close_qty = min(p["qty"], qty)
        pnl = (price - p["avg_price"]) * close_qty * stored_multiplier
        if p["side"] == "SELL":
            pnl = -pnl
        remaining_existing = p["qty"] - close_qty
        remaining_new = qty - close_qty
        if remaining_existing:
            p["qty"] = remaining_existing
        else:
            self.positions.pop(symbol, None)
        if remaining_new:
            self.positions[symbol] = {
                "qty": remaining_new, "avg_price": price, "side": side,
                "contract_multiplier": requested_multiplier or stored_multiplier,
            }
        return pnl
