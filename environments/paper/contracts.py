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
