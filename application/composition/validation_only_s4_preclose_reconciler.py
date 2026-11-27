from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

_TERMINAL_ORDER_STATES = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}

@dataclass(frozen=True)
class S4PrecloseReconciliation:
    status: str
    issues: tuple[str, ...]
    account_signed_quantity: Decimal
    group_signed_quantity: Decimal
    close_quantity: Decimal
    close_side: str | None
    snapshot_as_of: datetime | None

class ValidationOnlyS4PrecloseReconciler:
    """Read-only pre-close evidence gate; never creates or submits an order."""
    def reconcile(self, *, evidence: Any, strategy_id: str, group_id: str, instrument_id: str) -> S4PrecloseReconciliation:
        issues: list[str] = []
        account_id = str(getattr(evidence, "account_id", "") or "").strip()
        run_id = str(getattr(evidence, "run_id", "") or "").strip()
        candidate_id = str(getattr(evidence, "candidate_id", "") or "").strip()
        source = str(getattr(evidence, "source", "") or "").strip()
        as_of = getattr(evidence, "as_of", None)
        if not all((account_id, run_id, candidate_id)) or not source.startswith(("SYNTHETIC:", "VALIDATION_ONLY:")):
            issues.append("ACCOUNT_SCOPE_OR_SOURCE_INVALID")
        if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
            issues.append("SNAPSHOT_AS_OF_TIME_INVALID")

        def normalize(raw: Any, issue: str) -> dict[str, Decimal]:
            if not isinstance(raw, Mapping):
                issues.append(issue)
                return {}
            result: dict[str, Decimal] = {}
            for key, value in raw.items():
                try:
                    quantity = Decimal(str(value))
                except (InvalidOperation, TypeError, ValueError):
                    issues.append(issue)
                    continue
                instrument = str(key or "").strip()
                if not instrument or not quantity.is_finite() or quantity != quantity.to_integral_value():
                    issues.append(issue)
                    continue
                result[instrument] = quantity
            return {key: value for key, value in result.items() if value}

        broker = normalize(getattr(evidence, "broker_positions", None), "BROKER_POSITION_SNAPSHOT_INVALID")
        ledger = normalize(getattr(evidence, "ledger_positions", None), "EXECUTION_LEDGER_POSITION_INVALID")
        if broker != ledger:
            issues.append("BROKER_LEDGER_POSITION_MISMATCH")
        account_lots: dict[str, Decimal] = {}
        group_quantity = Decimal(0)
        for lot in tuple(getattr(evidence, "position_lots", ()) or ()):
            scope = (str(getattr(lot, "account_id", "") or "").strip(), str(getattr(lot, "run_id", "") or "").strip(), str(getattr(lot, "candidate_id", "") or "").strip())
            if scope != (account_id, run_id, candidate_id):
                issues.append("POSITION_LOT_SCOPE_MISMATCH")
                continue
            strategy = str(getattr(lot, "strategy_id", "") or "").strip()
            group = str(getattr(lot, "group_id", "") or "").strip()
            instrument = str(getattr(lot, "instrument_id", "") or "").strip()
            try:
                quantity = Decimal(str(lot.signed_quantity))
            except (InvalidOperation, TypeError, ValueError):
                issues.append("POSITION_LOT_QUANTITY_INVALID")
                continue
            if not strategy or not group or not instrument or not quantity.is_finite():
                issues.append("POSITION_LOT_IDENTITY_OR_QUANTITY_INVALID")
                continue
            account_lots[instrument] = account_lots.get(instrument, Decimal(0)) + quantity
            if (strategy, group, instrument) == (strategy_id, group_id, instrument_id):
                group_quantity += quantity
        account_lots = {key: value for key, value in account_lots.items() if value}
        if account_lots != broker:
            issues.append("BROKER_POSITION_LOT_AGGREGATE_MISMATCH")
        for order in tuple(getattr(evidence, "pending_orders", ()) or ()):
            order_account = str(getattr(order, "account_id", "") or "").strip()
            status = str(getattr(order, "status", "") or "").upper()
            if order_account != account_id or not status:
                issues.append("PENDING_ORDER_SCOPE_OR_STATUS_INVALID")
            elif status not in _TERMINAL_ORDER_STATES:
                issues.append("PENDING_OR_UNKNOWN_ORDER_REQUIRES_RECONCILIATION")
        if issues:
            return S4PrecloseReconciliation("RECONCILIATION_REQUIRED", tuple(dict.fromkeys(issues)), broker.get(instrument_id, Decimal(0)), group_quantity, Decimal(0), None, as_of if isinstance(as_of, datetime) else None)
        return S4PrecloseReconciliation("PRE_CLOSE_RECONCILED", (), broker.get(instrument_id, Decimal(0)), group_quantity, abs(group_quantity), "BUY" if group_quantity < 0 else "SELL" if group_quantity > 0 else None, as_of)

