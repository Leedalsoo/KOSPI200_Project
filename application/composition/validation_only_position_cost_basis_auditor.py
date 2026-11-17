"""Read-only FIFO cost-basis and realized-PnL reconciliation for validation data."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class ValidationOnlyCostBasisResult:
    status: str
    issues: tuple[str, ...]
    manifest: Mapping[str, Any]
    manifest_sha256: str | None
    realized_gross_pnl: Decimal | None
    realized_net_pnl: Decimal | None
    total_fees: Decimal | None
    closing_fees: Decimal | None
    opening_fees_realized: Decimal | None
    opening_fees_remaining: Decimal | None
    target_positions: tuple[Mapping[str, Any], ...]
    calculation_method: str = "FIFO"
    migration_applied: bool = False

    @property
    def is_reconciled(self) -> bool:
        return self.status == "VALIDATION_ONLY_COST_BASIS_RECONCILED"


class ValidationOnlyPositionCostBasisAuditor:
    """Reconcile opening lots + fills + fee ledger against target position cost basis."""

    MANIFEST_VERSION = "Q25-A8-VALIDATION-ONLY-COST-BASIS-v1"

    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError("COST_BASIS_VALIDATION_ONLY_OPT_IN_REQUIRED")

    @staticmethod
    def _decimal(value: Any, label: str, *, nonnegative: bool = False, positive: bool = False) -> Decimal:
        try:
            result = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"{label}_INVALID")
        if not result.is_finite() or (positive and result <= 0) or (nonnegative and result < 0):
            raise ValueError(f"{label}_INVALID")
        return result

    @staticmethod
    def _timestamp(value: Any, label: str) -> datetime:
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, str):
            try:
                result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError(f"{label}_INVALID")
        else:
            raise ValueError(f"{label}_INVALID")
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError(f"{label}_TIMEZONE_REQUIRED")
        return result.astimezone(timezone.utc)

    @staticmethod
    def _side(value: Any) -> str:
        side = str(value or "").upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("COST_BASIS_SIDE_INVALID")
        return side

    def audit(
        self, *, opening_lots, executions, fee_records, target_positions,
        source_namespace: str, deterministic_rule_id: str, source_manifest_sha256: str,
        source_anchor_refs, source_anchor_as_of, scenario_timestamp,
        evidence_refs, opening_snapshot_as_of, as_of,
    ) -> ValidationOnlyCostBasisResult:
        issues: list[str] = []
        opening_by_instrument: dict[str, deque] = defaultdict(deque)
        exec_rows: dict[str, dict] = {}
        fee_rows: dict[str, dict] = {}
        targets: dict[str, dict] = {}
        realized_gross = Decimal("0")
        realized_net = Decimal("0")
        total_fees = Decimal("0")
        closing_fees = Decimal("0")
        opening_fees_realized = Decimal("0")
        opening_fees_remaining = Decimal("0")

        if not source_namespace.startswith(("SYNTHETIC:", "SYNTHETIC_CONTRACT:")):
            issues.append("COST_BASIS_SYNTHETIC_NAMESPACE_REQUIRED")
        if not deterministic_rule_id.strip():
            issues.append("COST_BASIS_DETERMINISTIC_RULE_REQUIRED")
        if re.fullmatch(r"[0-9a-f]{64}", str(source_manifest_sha256).lower()) is None:
            issues.append("COST_BASIS_SOURCE_MANIFEST_HASH_REQUIRED")
        if not evidence_refs:
            issues.append("COST_BASIS_EVIDENCE_REFS_REQUIRED")
        if not source_anchor_refs or source_anchor_as_of is None or scenario_timestamp is None:
            issues.append("COST_BASIS_SOURCE_ANCHOR_PROVENANCE_REQUIRED")

        try:
            scenario_at = self._timestamp(scenario_timestamp, "COST_BASIS_SCENARIO_TIMESTAMP")
            anchor_at = self._timestamp(source_anchor_as_of, "COST_BASIS_SOURCE_ANCHOR")
            opening_as_of_at = self._timestamp(opening_snapshot_as_of, "COST_BASIS_OPENING_SNAPSHOT_AS_OF")
            as_of_at = self._timestamp(as_of, "COST_BASIS_AS_OF")
            if anchor_at > scenario_at:
                issues.append("COST_BASIS_FUTURE_SOURCE_ANCHOR_REJECTED")
            if scenario_at > as_of_at:
                issues.append("COST_BASIS_SCENARIO_AFTER_AS_OF")
        except ValueError as exc:
            scenario_at = anchor_at = opening_as_of_at = as_of_at = None
            issues.append(str(exc))

        try:
            for row in opening_lots:
                instrument = str(row.get("instrument_id") or "").strip()
                execution_id = str(row.get("execution_id") or "").strip()
                if not instrument or not execution_id:
                    raise ValueError("COST_BASIS_OPENING_LOT_IDENTITY_REQUIRED")
                qty = row.get("quantity")
                if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                    raise ValueError("COST_BASIS_OPENING_QUANTITY_INVALID")
                side = self._side(row.get("side"))
                price = self._decimal(row.get("unit_price"), "COST_BASIS_OPENING_UNIT_PRICE", positive=True)
                multiplier = self._decimal(row.get("contract_multiplier"), "COST_BASIS_MULTIPLIER", positive=True)
                fee = self._decimal(row.get("remaining_opening_fee"), "COST_BASIS_OPENING_FEE", nonnegative=True)
                timestamp = self._timestamp(row.get("executed_at"), "COST_BASIS_OPENING_TIMESTAMP")
                if timestamp > (as_of_at or timestamp):
                    raise ValueError("COST_BASIS_OPENING_AFTER_AS_OF")
                opening_by_instrument[instrument].append({
                    "side": side, "qty": qty, "price": price, "multiplier": multiplier,
                    "fee": fee, "execution_id": execution_id, "timestamp": timestamp,
                })
        except (AttributeError, TypeError, ValueError) as exc:
            issues.append(str(exc))

        try:
            for row in executions:
                execution_id = str(row.get("execution_id") or "").strip()
                instrument = str(row.get("instrument_id") or "").strip()
                if not execution_id or not instrument or execution_id in exec_rows:
                    raise ValueError("COST_BASIS_EXECUTION_IDENTITY_MISSING_OR_DUPLICATE")
                qty = row.get("quantity")
                if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                    raise ValueError("COST_BASIS_EXECUTION_QUANTITY_INVALID")
                price = self._decimal(row.get("price"), "COST_BASIS_EXECUTION_PRICE", positive=True)
                multiplier = self._decimal(row.get("contract_multiplier"), "COST_BASIS_MULTIPLIER", positive=True)
                timestamp = self._timestamp(row.get("executed_at"), "COST_BASIS_EXECUTION_TIMESTAMP")
                if timestamp > (as_of_at or timestamp):
                    raise ValueError("COST_BASIS_EXECUTION_AFTER_AS_OF")
                if opening_as_of_at is not None and timestamp < opening_as_of_at:
                    raise ValueError("COST_BASIS_EXECUTION_BEFORE_OPENING_SNAPSHOT")
                row_copy = dict(row, execution_id=execution_id, instrument_id=instrument,
                                side=self._side(row.get("side")), quantity=qty, price=price,
                                contract_multiplier=multiplier, timestamp=timestamp)
                for key in ("client_order_id", "strategy_id", "group_id", "leg_id"):
                    if not str(row_copy.get(key) or "").strip():
                        raise ValueError(f"COST_BASIS_EXECUTION_{key.upper()}_REQUIRED")
                if not str(row_copy.get("source") or "").strip():
                    raise ValueError("COST_BASIS_EXECUTION_SOURCE_REQUIRED")
                exec_rows[execution_id] = row_copy
        except (AttributeError, TypeError, ValueError) as exc:
            issues.append(str(exc))

        try:
            for row in fee_records:
                execution_id = str(row.get("execution_id") or "").strip()
                if not execution_id or execution_id in fee_rows:
                    raise ValueError("COST_BASIS_FEE_EXECUTION_ID_MISSING_OR_DUPLICATE")
                fee_rows[execution_id] = {
                    "fee": self._decimal(row.get("fee_amount"), "COST_BASIS_FEE_AMOUNT", nonnegative=True),
                    "qty": row.get("quantity"),
                    "price": self._decimal(row.get("price"), "COST_BASIS_FEE_PRICE", positive=True),
                    "instrument_id": str(row.get("instrument_id") or ""),
                    "client_order_id": str(row.get("client_order_id") or ""),
                    "strategy_id": str(row.get("strategy_id") or ""),
                    "group_id": str(row.get("group_id") or ""),
                    "leg_id": str(row.get("leg_id") or ""),
                    "source": str(row.get("source") or ""),
                    "timestamp": self._timestamp(row.get("executed_at"), "COST_BASIS_FEE_TIMESTAMP"),
                }
        except (AttributeError, TypeError, ValueError) as exc:
            issues.append(str(exc))

        if set(exec_rows) != set(fee_rows):
            issues.append("COST_BASIS_EXECUTION_FEE_LEDGER_COVERAGE_MISMATCH")
        for execution_id, execution in exec_rows.items():
            fee = fee_rows.get(execution_id)
            if fee is None:
                continue
            for left, right, label in (
                (fee["qty"], execution["quantity"], "QUANTITY"),
                (fee["price"], execution["price"], "PRICE"),
                (fee["instrument_id"], execution["instrument_id"], "INSTRUMENT"),
                (fee["client_order_id"], execution["client_order_id"], "CLIENT_ORDER"),
                (fee["strategy_id"], execution["strategy_id"], "STRATEGY"),
                (fee["group_id"], execution["group_id"], "GROUP"),
                (fee["leg_id"], execution["leg_id"], "LEG"),
                (fee["timestamp"], execution["timestamp"], "TIMESTAMP"),
            ):
                if left != right:
                    issues.append(f"COST_BASIS_FEE_EXECUTION_{label}_MISMATCH:{execution_id}")
            if not fee["source"]:
                issues.append(f"COST_BASIS_FEE_SOURCE_REQUIRED:{execution_id}")

        if not issues:
            for instrument, queue in opening_by_instrument.items():
                for lot in queue:
                    if lot["side"] == "BUY":
                        lot["signed_side"] = 1
                    else:
                        lot["signed_side"] = -1
            for instrument, queue in opening_by_instrument.items():
                opening_by_instrument[instrument] = deque(sorted(queue, key=lambda x: (x["timestamp"], x["execution_id"])))
            ordered = sorted(exec_rows.values(), key=lambda x: (x["timestamp"], x["execution_id"]))
            for execution in ordered:
                instrument = execution["instrument_id"]
                side = execution["side"]
                qty = execution["quantity"]
                multiplier = execution["contract_multiplier"]
                fee = fee_rows[execution["execution_id"]]["fee"]
                total_fees += fee
                queue = opening_by_instrument[instrument]
                close_qty = sum(lot["qty"] for lot in queue if lot["side"] != side)
                remaining = qty
                close_fee_remaining = fee
                for lot in list(queue):
                    if remaining <= 0 or lot["side"] == side:
                        continue
                    if lot["multiplier"] != multiplier:
                        issues.append(f"COST_BASIS_MULTIPLIER_MISMATCH:{instrument}")
                        break
                    matched = min(remaining, lot["qty"])
                    fee_piece = fee * Decimal(matched) / Decimal(qty)
                    open_fee_piece = lot["fee"] * Decimal(matched) / Decimal(lot["qty"])
                    if lot["side"] == "BUY":
                        gross = (execution["price"] - lot["price"]) * Decimal(matched) * multiplier
                    else:
                        gross = (lot["price"] - execution["price"]) * Decimal(matched) * multiplier
                    realized_gross += gross
                    realized_net += gross - fee_piece - open_fee_piece
                    closing_fees += fee_piece
                    opening_fees_realized += open_fee_piece
                    lot["fee"] -= open_fee_piece
                    lot["qty"] -= matched
                    remaining -= matched
                    close_fee_remaining -= fee_piece
                    if lot["qty"] == 0:
                        queue.remove(lot)
                if issues:
                    break
                if remaining:
                    opening_fee = close_fee_remaining
                    queue.append({"side": side, "qty": remaining, "price": execution["price"],
                                  "multiplier": multiplier, "fee": opening_fee,
                                  "execution_id": execution["execution_id"], "timestamp": execution["timestamp"]})
                elif close_fee_remaining != 0:
                    closing_fees += close_fee_remaining
                    realized_net -= close_fee_remaining
            for queue in opening_by_instrument.values():
                for lot in queue:
                    opening_fees_remaining += lot["fee"]

        try:
            for row in target_positions:
                instrument = str(row.get("instrument_id") or "").strip()
                if not instrument or instrument in targets:
                    raise ValueError("COST_BASIS_TARGET_IDENTITY_MISSING_OR_DUPLICATE")
                qty = row.get("quantity")
                if not isinstance(qty, int) or isinstance(qty, bool) or qty < 0:
                    raise ValueError("COST_BASIS_TARGET_QUANTITY_INVALID")
                side = self._side(row.get("side")) if qty else "FLAT"
                avg_price = self._decimal(row.get("average_price"), "COST_BASIS_TARGET_AVERAGE_PRICE", nonnegative=True) if qty else Decimal("0")
                targets[instrument] = {"side": side, "quantity": qty, "average_price": avg_price}
        except (AttributeError, TypeError, ValueError) as exc:
            issues.append(str(exc))

        calculated = []
        for instrument in sorted(set(opening_by_instrument) | set(targets)):
            lots = list(opening_by_instrument.get(instrument, ()))
            signed = sum(lot["qty"] if lot["side"] == "BUY" else -lot["qty"] for lot in lots)
            quantity = abs(signed)
            side = "BUY" if signed > 0 else "SELL" if signed < 0 else "FLAT"
            notional = sum((lot["price"] * Decimal(lot["qty"]) for lot in lots), Decimal("0"))
            average = notional / Decimal(quantity) if quantity else Decimal("0")
            calculated.append({"instrument_id": instrument, "side": side, "quantity": quantity,
                               "average_price": average, "remaining_opening_fee": sum((lot["fee"] for lot in lots), Decimal("0"))})
            target = targets.get(instrument, {"side": "FLAT", "quantity": 0, "average_price": Decimal("0")})
            if (side, quantity) != (target["side"], target["quantity"]):
                issues.append(f"COST_BASIS_TARGET_POSITION_QUANTITY_MISMATCH:{instrument}")
            elif quantity and average != target["average_price"]:
                issues.append(f"COST_BASIS_TARGET_AVERAGE_PRICE_MISMATCH:{instrument}")

        manifest = {
            "manifest_version": self.MANIFEST_VERSION,
            "source_namespace": source_namespace,
            "deterministic_rule_id": deterministic_rule_id,
            "source_manifest_sha256": str(source_manifest_sha256).lower(),
            "source_anchor_refs": list(source_anchor_refs or ()),
            "source_anchor_as_of": anchor_at.isoformat() if anchor_at else None,
            "scenario_timestamp": scenario_at.isoformat() if scenario_at else None,
            "opening_snapshot_as_of": opening_as_of_at.isoformat() if opening_as_of_at else None,
            "as_of": as_of_at.isoformat() if as_of_at else None,
            "opening_lot_ids": sorted(str(row.get("execution_id")) for row in opening_lots),
            "execution_ids": sorted(exec_rows),
            "fee_execution_ids": sorted(fee_rows),
            "evidence_refs": sorted(str(x) for x in evidence_refs or ()),
            "realized_gross_pnl": str(realized_gross) if not issues else None,
            "realized_net_pnl": str(realized_net) if not issues else None,
            "total_fees": str(total_fees) if not issues else None,
            "closing_fees": str(closing_fees) if not issues else None,
            "opening_fees_realized": str(opening_fees_realized) if not issues else None,
            "opening_fees_remaining": str(opening_fees_remaining) if not issues else None,
            "calculation_method": "FIFO",
            "migration_applied": False,
        }
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        unique_issues = tuple(dict.fromkeys(issues))
        valid = not unique_issues
        return ValidationOnlyCostBasisResult(
            status="VALIDATION_ONLY_COST_BASIS_RECONCILED" if valid else "RECONCILIATION_REQUIRED",
            issues=unique_issues, manifest=manifest, manifest_sha256=digest if valid else None,
            realized_gross_pnl=realized_gross if valid else None,
            realized_net_pnl=realized_net if valid else None,
            total_fees=(total_fees + opening_fees_realized) if valid else None,
            closing_fees=closing_fees if valid else None,
            opening_fees_realized=opening_fees_realized if valid else None,
            opening_fees_remaining=opening_fees_remaining if valid else None,
            target_positions=tuple(calculated),
        )
