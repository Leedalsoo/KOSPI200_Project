from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class StrategyExecutionProposal:
    """Strategy가 실제 실행에 필요하다고 제안한 값의 표준 운반 계약.

    이 계약은 승인 수량이나 주문 실행 의미를 결정하지 않는다.
    누락된 값은 임의의 기본값으로 채우지 않는다.
    """

    proposed_quantity: int
    asset_type: str
    requested_price: Decimal | None = None
    side: str | None = None
    track_id: str | None = None
    tag_id: str | None = None
    option_type: str | None = None
    strike: Decimal | None = None

    def __post_init__(self) -> None:
        if self.proposed_quantity <= 0:
            pass
            raise ValueError("PROPOSED_QUANTITY_REQUIRED")
        if not self.asset_type:
            pass
            raise ValueError("ASSET_TYPE_REQUIRED")
        if self.requested_price is not None and self.requested_price <= 0:
            pass
            raise ValueError("REQUESTED_PRICE_MUST_BE_POSITIVE")
        if self.strike is not None and self.strike <= 0:
            pass
            raise ValueError("STRIKE_MUST_BE_POSITIVE")
