class PositionManager:
    def __init__(self):
        self.positions = {}

    def update_position(self, symbol, side, qty, price, **kwargs):
        p = self.positions.get(symbol, {"qty": 0, "avg_price": 0.0, "side": side})
        if p["qty"] == 0 or p["side"] == side:
            total = p["qty"] + qty
            p["avg_price"] = (p["avg_price"] * p["qty"] + price * qty) / total
            p["qty"] = total
            p["side"] = side
            self.positions[symbol] = p
            return 0.0
        close = min(p["qty"], qty)
        pnl = (price - p["avg_price"]) * close * 250000.0 * (1 if p["side"] == "BUY" else -1)
        p["qty"] -= close
        if p["qty"]:
            self.positions[symbol] = p
        else:
            self.positions.pop(symbol, None)
        return pnl
