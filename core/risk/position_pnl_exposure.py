"""Position/PnL/exposure projection from explicit authoritative position lines."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from contracts.trading_state import PositionPnLExposureSnapshot


@dataclass(frozen=True, slots=True)
class ExposureLine:
    instrument_id: str
    asset_type: str
    side: str
    quantity: int
    average_price: Decimal
    current_price: Decimal
    contract_multiplier: Decimal

    def __post_init__(self) -> None:
        if not self.instrument_id or self.quantity <= 0 or self.contract_multiplier <= 0:
            raise ValueError("EXPOSURE_LINE_ID_QUANTITY_MULTIPLIER_REQUIRED")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("EXPOSURE_LINE_SIDE_REQUIRED")


def project_position_pnl_exposure(lines: list[ExposureLine], *, as_of: datetime,
                                  realized_pnl: Decimal | None = None) -> PositionPnLExposureSnapshot:
    """Project explicit position lines; missing account/PnL values remain None."""
    gross = Decimal("0")
    net = Decimal("0")
    option = Decimal("0")
    futures = Decimal("0")
    unrealized = Decimal("0")
    for line in lines:
        notional = abs(line.current_price * line.quantity * line.contract_multiplier)
        signed = notional if line.side == "BUY" else -notional
        gross += notional
        net += signed
        if line.asset_type == "OPTION":
            option += signed
        elif line.asset_type == "FUTURES":
            futures += signed
        else:
            raise ValueError("EXPOSURE_LINE_ASSET_TYPE_UNSUPPORTED")
        direction = Decimal("1") if line.side == "BUY" else Decimal("-1")
        unrealized += (line.current_price - line.average_price) * line.quantity * line.contract_multiplier * direction
    realized = realized_pnl
    daily = realized + unrealized if realized is not None else None
    return PositionPnLExposureSnapshot(
        as_of=as_of,
        gross_exposure=gross,
        net_exposure=net,
        option_exposure=option,
        futures_exposure=futures,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        daily_pnl=daily,
        open_positions=len(lines),
    )
