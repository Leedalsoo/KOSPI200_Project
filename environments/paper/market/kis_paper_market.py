from environments.paper.contracts import PaperCredential, PaperMarketTick

class KISPaperMarketData:
    """Real KIS VTS market-data boundary. No Virtual/VMS dependency."""
    def __init__(self, credential: PaperCredential, client):
        self.credential = credential
        self.client = client

    def connect(self) -> None:
        self.client.authenticate()

    def next_tick(self) -> PaperMarketTick:
        raise NotImplementedError("bind the verified KIS VTS market-data endpoint")
