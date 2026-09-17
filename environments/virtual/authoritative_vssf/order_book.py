class OrderBook:
    """Contract-scoped quote book and pending-order registry for Virtual execution."""

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

    def _quote_for(self, command):
        identity = getattr(command, "instrument_identity", None)
        key = getattr(identity, "instrument_id", None) or getattr(command, "instrument_id", None)
        key = key or getattr(command, "symbol", None)
        return self.books.get(str(key)) or self.books.get("__DEFAULT__")

    def match_order(self, command):
        quote = self._quote_for(command)
        if quote is None:
            return 0.0
        return quote[1] if str(getattr(command.side, "value", command.side)) == "BUY" else quote[0]

    def add_pending_order(self, command):
        self.orders[command.client_order_id] = command

    def pending_orders(self):
        return tuple(self.orders.values())

    def get_pending_order(self, client_order_id):
        return self.orders.get(client_order_id)

    def remove_pending_order(self, client_order_id):
        return self.orders.pop(client_order_id, None)

    def cancel_order(self, client_order_id):
        return self.remove_pending_order(client_order_id) is not None
