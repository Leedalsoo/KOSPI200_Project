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
