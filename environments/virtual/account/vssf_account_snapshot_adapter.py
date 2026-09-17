from datetime import datetime
from decimal import Decimal
from typing import Any

from contracts.account import AccountProvider
from contracts.types import AccountSnapshot, DataQuality


class VSSFAccountSnapshotAdapter(AccountProvider):
    """Read-only projection of VSSF authoritative account state."""

    def __init__(self, account_source: Any):
        self._account_source = account_source

    def snapshot(self) -> AccountSnapshot:
        getter = getattr(self._account_source, "get_canonical_summary", None)
        if not callable(getter):
            raise TypeError("VSSF_ACCOUNT_SOURCE_REQUIRED")

        summary = getter()
        required = (
            "total_balance",
            "realized_pnl",
            "unrealized_pnl",
            "used_margin",
            "free_margin",
            "timestamp",
        )
        missing = [name for name in required if not hasattr(summary, name)]
        if missing:
            raise TypeError(f"VSSF_ACCOUNT_FIELDS_REQUIRED: {','.join(missing)}")

        try:
            as_of = datetime.strptime(str(summary.timestamp), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError) as exc:
            raise TypeError("VSSF_ACCOUNT_TIMESTAMP_INVALID") from exc

        try:
            balances = {
                "cash": Decimal(str(summary.total_balance)),
                "margin_used": Decimal(str(summary.used_margin)),
                "realized_pnl": Decimal(str(summary.realized_pnl)),
                "available_cash": Decimal(str(summary.free_margin)),
                "unrealized_pnl": Decimal(str(summary.unrealized_pnl)),
            }
        except Exception as exc:
            raise TypeError("VSSF_ACCOUNT_BALANCE_INVALID") from exc

        return AccountSnapshot(
            as_of=as_of,
            balances=balances,
            freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="vssf_authoritative_account_summary",
            ),
        )
