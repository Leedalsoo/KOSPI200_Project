from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from contracts.track4_attribution_provider import (
    Track4AttributionSnapshot,
    Track4AttributionSourceUnavailable,
)


class VirtualTrack4AttributionSource:
    """Authoritative Virtual execution-ledger projection for Track4 attribution.

    Premium spent is derived only from executed OPTION BUY reports. Gamma-profit and
    theta-decay attribution are deliberately unavailable until an authoritative
    valuation/attribution ledger supplies those components.
    """

    source_name = "VirtualExchange.VirtualBroker.VSSF.execution_ledger"

    def __init__(self, execution_engine: Any, *, observed_at: datetime) -> None:
        self._execution_engine = execution_engine
        self._observed_at = observed_at

    def snapshot(self) -> Track4AttributionSnapshot:
        return Track4AttributionSnapshot(
            observed_at=self._observed_at,
            premium_spent=self._premium_spent_value(),
            accumulated_gamma_profit=None,
            theta_decay_cost=None,
            source=self.source_name,
        )

    def premium_spent(self) -> Decimal:
        return self._premium_spent_value()

    def accumulated_gamma_profit(self) -> Decimal:
        raise Track4AttributionSourceUnavailable(
            "TRACK4_GAMMA_PROFIT_ATTRIBUTION_SOURCE_UNAVAILABLE"
        )

    def theta_decay_cost(self) -> Decimal:
        raise Track4AttributionSourceUnavailable(
            "TRACK4_THETA_ATTRIBUTION_SOURCE_UNAVAILABLE"
        )

    def _premium_spent_value(self) -> Decimal:
        reports = tuple(getattr(self._execution_engine, "reports", ()))
        total = Decimal("0")
        for report in reports:
            asset_type = str(getattr(getattr(report, "asset_type", None), "value", getattr(report, "asset_type", ""))).upper()
            side = str(getattr(getattr(report, "side", None), "value", getattr(report, "side", ""))).upper()
            if asset_type != "OPTION" or side != "BUY":
                continue
            price = Decimal(str(getattr(report, "executed_price", "0")))
            quantity = int(getattr(report, "executed_qty", 0))
            if price < 0 or quantity < 0:
                raise Track4AttributionSourceUnavailable("TRACK4_EXECUTION_LEDGER_INVALID")
            total += price * quantity
        return total
