class OrderBook:
    """Contract-scoped bid/ask book for Virtual execution."""
    def __init__(self):
        self.books = {}
        self.orders = {}

    def update_bid_ask(self, bid, ask, instrument_id=None):
        key = str(instrument_id or "__DEFAULT__")
        self.books[key] = (float(bid), float(ask))

    @property
    def bid(self):
        return self.books.get("__DEFAULT__", (0.0, 0.0))[0]

    @property
    def ask(self):
        return self.books.get("__DEFAULT__", (0.0, 0.0))[1]

    def match_order(self, command):
        identity = getattr(command, "instrument_identity", None)
        key = getattr(identity, "instrument_id", None) or getattr(command, "instrument_id", None) or getattr(command, "symbol", None)
        quote = self.books.get(str(key))
        if quote is None:
            quote = self.books.get("__DEFAULT__")
        if quote is None:
            return 0.0
        return quote[1] if str(getattr(command.side, "value", command.side)) == "BUY" else quote[0]

    def cancel_order(self, client_order_id):
        return self.orders.pop(client_order_id, None) is not None
