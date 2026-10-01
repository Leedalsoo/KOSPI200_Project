"""Common runtime-input assembly kept outside strategy-specific composition."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from contracts.analytics import AnalyticsProvenance, MarketSnapshot
from contracts.risk_guard import RiskGuardStatusSource
from core.analytics.common import COMMON_METRIC_CONTRACTS, build_common_analytics_snapshot
from core.strategy.contracts import CommonStrategyInput
from contracts.track9_fee_ledger import Track9FeeLedger


class CommonRuntimeInputAssembler:
    """Own account/fee/risk aggregation and common AnalyticsSnapshot creation."""

    def __init__(self, *, fee_ledger: Track9FeeLedger | None, run_id: str | None) -> None:
        self.fee_ledger = fee_ledger
        self.run_id = run_id

    @staticmethod
    def account_snapshot(account: Any | None) -> Any | None:
        if account is None:
            return None
        getter = getattr(account, "snapshot", None)
        return getter() if callable(getter) else account

    def common_input(self, data: Any, account: Any | None) -> CommonStrategyInput:
        snapshot = self.account_snapshot(account)
        balances = getattr(snapshot, "balances", {}) if snapshot is not None else {}
        budget = balances.get("available_cash")
        realized = balances.get("realized_pnl")
        unrealized = balances.get("unrealized_pnl")
        pnl = (
            Decimal(str(realized)) + Decimal(str(unrealized))
            if realized is not None and unrealized is not None else None
        )
        return CommonStrategyInput(
            as_of=data.as_of,
            current_price=data.price,
            active_vol=data.active_vol,
            base_vol=data.base_vol,
            budget=Decimal(str(budget)) if budget is not None else None,
            current_pnl=Decimal(str(pnl)) if pnl is not None else None,
            total_fees=(
                self.fee_ledger.total(run_id=self.run_id)
                if self.fee_ledger is not None and self.run_id else None
            ),
            time_str=data.as_of.strftime("%H:%M:%S"),
            date_str=data.as_of.date().isoformat(),
        )

    def analytics_snapshot(
        self,
        data: Any,
        common: CommonStrategyInput,
        *,
        condition: Any | None,
        margin_ratio: Decimal | None,
        risk_guard_status: RiskGuardStatusSource | Any | None,
    ):
        market_snapshot = MarketSnapshot(
            run_id=self.run_id or "virtual",
            as_of=data.as_of,
            provenance=AnalyticsProvenance(source="standard-runtime.common"),
            instrument_identity=None,
            observations={
                "current_price": data.price,
                "active_vol": data.active_vol,
                "base_vol": data.base_vol,
                "current_regime": condition.current_regime if condition is not None else None,
                "call_iv": data.option_iv,
                "put_iv": data.put_iv,
                "current_pnl": common.current_pnl,
                "total_fees": common.total_fees,
                "margin_ratio": margin_ratio,
                "risk_guard_active": (
                    risk_guard_status.admission_allowed
                    if risk_guard_status is not None else None
                ),
                "risk_guard_status": risk_guard_status,
            },
        )
        return build_common_analytics_snapshot(market_snapshot, tuple(COMMON_METRIC_CONTRACTS))
