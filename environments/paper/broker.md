[Child Page] kis_paper_broker.py
```python
from environments.paper.contracts import PaperCredential, PaperExecutionReport

class KISPaperBroker:
    """KIS VTS order/execution boundary. Never falls back to VSSF simulation."""
    def __init__(self, credential: PaperCredential, client):
        self.credential = credential
        self.client = client

    def connect(self) -> None:
        self.client.authenticate()

    def submit(self, command):
        raise NotImplementedError("bind the verified KIS VTS order endpoint")

    def poll_execution_reports(self) -> list[PaperExecutionReport]:
        raise NotImplementedError("bind the verified KIS VTS execution endpoint")
```