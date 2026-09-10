from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from contracts.account import AccountProvider
from contracts.types import AccountSnapshot, DataQuality
from environments.virtual.clock import ClockProvider


@dataclass
class VirtualAccount(AccountProvider):
    cash: Decimal
    margin_used: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    clock: ClockProvider | None = None

    def available_cash(self) -> Decimal:
        return self.cash - self.margin_used

    def snapshot(self) -> AccountSnapshot:
        if self.clock is None:
            pass
            raise RuntimeError("VirtualAccount.snapshot requires an injected ClockProvider")
        return AccountSnapshot(
            as_of=self.clock.now(),
            balances={
                "cash": self.cash,
                "margin_used": self.margin_used,
                "realized_pnl": self.realized_pnl,
                "available_cash": self.available_cash(),
            },
            freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="virtual_account_state",
            ),
        )
