from dataclasses import dataclass
from typing import Optional
from shared.contracts.canonical import (
    CanonicalAccountSummary, CanonicalAssetType, CanonicalExecutionReport,
    CanonicalMarketTick, CanonicalOptionType, CanonicalOrderCommand, CanonicalOrderSide,
)

@dataclass(frozen=True)
class VSSFOrderResult:
    client_order_id: str
    status: str
    submitted_at: str
    observed_at: str
    remaining_qty: int
    exec_id: Optional[str] = None
    executed_qty: int = 0
    executed_price: Optional[float] = None
    track_id: str = ""
    asset_type: object = None
    side: object = None
    symbol: str = "KOSPI200"

__all__ = [
    "CanonicalAccountSummary", "CanonicalAssetType", "CanonicalExecutionReport",
    "CanonicalMarketTick", "CanonicalOptionType", "CanonicalOrderCommand",
    "CanonicalOrderSide", "VSSFOrderResult",
]
