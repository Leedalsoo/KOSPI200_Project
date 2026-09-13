class OrderBook:
    def __init__(self):
        self.bid = 0.0; self.ask = 0.0; self.orders = {}
    def update_bid_ask(self, bid, ask): self.bid=float(bid); self.ask=float(ask)
    def match_order(self, command): return self.ask if str(getattr(command.side,'value',command.side)) == 'BUY' else self.bid
    def cancel_order(self, client_order_id): return self.orders.pop(client_order_id, None) is not None
