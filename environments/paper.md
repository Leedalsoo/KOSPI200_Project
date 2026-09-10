폴더 페이지

[Child Page] market
[Child Page] kis_paper_market.py
```python
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
```

[Child Page] broker
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

[Child Page] account

[Child Page] paper_account.py
```python
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

@dataclass(frozen=True)
class PaperAccountSnapshot:
    observed_at: datetime
    available_margin: Decimal
    equity: Decimal
    source: str
    is_stale: bool = False
```

[Child Page] position
[Child Page] paper_position.py
```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class PaperPositionSnapshot:
    instrument_id: str
    quantity: int
    average_price: float
    observed_at: datetime
    source: str
    is_stale: bool = False
```

[Child Page] reconciliation
[Child Page] reconciler.py
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ReconciliationResult:
    matched: bool
    differences: tuple[str, ...]

class PaperReconciler:
    def compare(self, broker_snapshot, internal_snapshot) -> ReconciliationResult:
        differences = []
        if broker_snapshot is None or internal_snapshot is None:
            differences.append("missing_snapshot")
        elif getattr(broker_snapshot, "is_stale", False):
            differences.append("stale_broker_snapshot")
        return ReconciliationResult(not differences, tuple(differences))
```

[Child Page] bundle.py
```python
from contracts.types import EnvironmentType

class PaperEnvironmentBundle:
    environment = EnvironmentType.PAPER

    def __init__(self, config, policy):
        self.config = config
        self.policy = policy
        self.market = None
        self.broker = None

    def initialize(self):
        # Credential and endpoint construction belongs here, not in Core/Strategy.
        pass

    def connect(self):
        if self.market is None or self.broker is None:
            raise RuntimeError("Paper adapters are not configured")
        self.market.connect()
        self.broker.connect()

    def start(self):
        pass

    def stop(self):
        pass

    def shutdown(self):
        self.market = None
        self.broker = None
```

[Child Page] README.md
Paper Trading means the actual broker's VTS/paper system, not the existing VSSF virtual broker.
The environment owns KIS Paper credentials, endpoint, market-data adapter, broker/execution adapter, account/position snapshots and reconciliation.
Synthetic VMS/VSSF data must never be silently substituted for a failed Paper connection. Real API evidence remains a separate verification gate.

[Child Page] contracts.py
```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass(frozen=True)
class PaperCredential:
    app_key: str
    app_secret: str
    account_no: str
    base_url: str
    is_vts: bool = True

@dataclass(frozen=True)
class PaperMarketTick:
    instrument_id: str
    observed_at: datetime
    price: Decimal
    volume: Decimal | None
    source: str

@dataclass(frozen=True)
class PaperExecutionReport:
    client_order_id: str
    broker_order_id: str | None
    exec_id: str | None
    status: str
    filled_quantity: int
    filled_price: Decimal | None
    observed_at: datetime
    source: str
```