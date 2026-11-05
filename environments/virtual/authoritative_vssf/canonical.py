from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from shared.contracts.canonical import (
    CanonicalAccountSummary, CanonicalAssetType, CanonicalExecutionReport,
    CanonicalMarketTick, CanonicalOptionType, CanonicalOrderCommand, CanonicalOrderSide,
)

@dataclass(frozen=True)
class VSSFExecutionFill:
    exec_id: str
    executed_qty: int
    executed_price: Decimal
    fee: Decimal
    timestamp: str


@dataclass(frozen=True)
class VSSFOrderResult:
    client_order_id: str
    status: str
    submitted_at: str
    observed_at: str
    remaining_qty: int
    exec_id: Optional[str] = None
    executed_qty: int = 0
    executed_price: Optional[Decimal] = None
    track_id: str = ""
    asset_type: object = None
    side: object = None
    symbol: str = "KOSPI200"
    fee: Optional[Decimal] = None
    lifecycle_reason: Optional[str] = None
    executed_at: Optional[str] = None
    execution_fills: tuple[VSSFExecutionFill, ...] = ()

__all__ = [
    "CanonicalAccountSummary", "CanonicalAssetType", "CanonicalExecutionReport",
    "CanonicalMarketTick", "CanonicalOptionType", "CanonicalOrderCommand",
    "CanonicalOrderSide", "VSSFExecutionFill", "VSSFOrderResult",
]
