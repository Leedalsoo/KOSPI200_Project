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
