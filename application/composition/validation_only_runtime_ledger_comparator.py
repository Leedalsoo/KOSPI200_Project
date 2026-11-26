from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ValidationOnlyRuntimeLedgerComparison:
    status: str
    issues: tuple[str, ...]
    manifest: Mapping[str, Any]
    manifest_sha256: str | None


class ValidationOnlyRuntimeLedgerComparator:
    """Read-only FIFO/PositionLot/close-event/fee/VSSF aggregate cross-check."""

    VERSION = "Q25-A8-FRESH30-v1"

    @staticmethod
    def _decimal(value: Any, label: str) -> Decimal:
        try:
            result = value if isinstance(value, Decimal) else Decimal(str(value))
        except Exception as exc:
            raise ValueError(f"{label}_INVALID") from exc
        if not result.is_finite():
            raise ValueError(f"{label}_INVALID")
        return result

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("RUNTIME_LEDGER_TIMESTAMP_TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _get(row: Any, key: str) -> Any:
        return row.get(key) if isinstance(row, Mapping) else getattr(row, key)

    def compare(
        self, *, opening_lots: Sequence[Mapping[str, Any]],
        executions: Sequence[Mapping[str, Any]],
        expected_fee_records: Sequence[Mapping[str, Any]],
        actual_position_lot_history: Sequence[Any],
        actual_open_position_lots: Sequence[Any],
        actual_close_events: Sequence[Any],
        actual_fee_records: Sequence[Any],
        vssf_positions: Mapping[str, Mapping[str, Any]],
        vssf_realized_pnl_delta: Any, vssf_unrealized_pnl: Any,
        mark_prices: Mapping[str, Any], source_namespace: str,
        deterministic_rule_id: str, source_manifest_sha256: str,
        source_anchor_refs: Sequence[str], source_anchor_as_of: Any,
        scenario_timestamp: Any, evidence_refs: Sequence[str],
    ) -> ValidationOnlyRuntimeLedgerComparison:
        issues: list[str] = []
        if not source_namespace.startswith(("SYNTHETIC:", "SYNTHETIC_CONTRACT:")):
            issues.append("RUNTIME_LEDGER_SYNTHETIC_NAMESPACE_REQUIRED")
        if not deterministic_rule_id.strip():
            issues.append("RUNTIME_LEDGER_DETERMINISTIC_RULE_REQUIRED")
        if len(str(source_manifest_sha256)) != 64:
            issues.append("RUNTIME_LEDGER_SOURCE_MANIFEST_HASH_REQUIRED")
        if not source_anchor_refs or not evidence_refs:
            issues.append("RUNTIME_LEDGER_PROVENANCE_REFS_REQUIRED")
        try:
            anchor = self._timestamp(source_anchor_as_of)
            scenario = self._timestamp(scenario_timestamp)
            if anchor > scenario:
                issues.append("RUNTIME_LEDGER_FUTURE_ANCHOR_REJECTED")
        except (TypeError, ValueError):
            anchor = scenario = None
            issues.append("RUNTIME_LEDGER_TIMESTAMP_INVALID")

        queues: dict[str, list[dict[str, Any]]] = {}
        expected_history: dict[str, tuple[str, int, Decimal]] = {}
        for row in opening_lots:
            instrument = str(row["instrument_id"])
            execution_id = str(row["execution_id"])
            side = str(row["side"]).upper()
            qty = int(row["quantity"])
            multiplier = self._decimal(row["contract_multiplier"], "OPENING_MULTIPLIER")
            queues.setdefault(instrument, []).append({
                "execution_id": execution_id, "side": side, "qty": qty,
                "price": self._decimal(row["unit_price"], "OPENING_PRICE"),
                "multiplier": multiplier, "timestamp": self._timestamp(row["executed_at"]),
            })
            expected_history[execution_id] = (side, qty, multiplier)

        expected_closes: list[tuple[str, str, int, datetime]] = []
        ordered = sorted(executions, key=lambda x: (self._timestamp(x["executed_at"]), str(x["execution_id"])))
        for row in ordered:
            execution_id = str(row["execution_id"])
            instrument = str(row["instrument_id"])
            side = str(row["side"]).upper()
            qty = int(row["quantity"])
            price = self._decimal(row["price"], "EXECUTION_PRICE")
            multiplier = self._decimal(row["contract_multiplier"], "EXECUTION_MULTIPLIER")
            timestamp = self._timestamp(row["executed_at"])
            if side not in {"BUY", "SELL"} or qty <= 0 or multiplier <= 0:
                issues.append(f"RUNTIME_LEDGER_EXECUTION_INVALID:{execution_id}")
                continue
            queue = queues.setdefault(instrument, [])
            remaining = qty
            for lot in list(queue):
                if remaining <= 0 or lot["side"] == side:
                    continue
                if lot["multiplier"] != multiplier:
                    issues.append(f"RUNTIME_LEDGER_MULTIPLIER_MISMATCH:{instrument}")
                    break
                matched = min(remaining, lot["qty"])
                expected_closes.append((execution_id, lot["execution_id"], matched, timestamp))
                lot["qty"] -= matched
                remaining -= matched
                if lot["qty"] == 0:
                    queue.remove(lot)
            if remaining:
                queue.append({
                    "execution_id": execution_id, "side": side, "qty": remaining,
                    "price": price, "multiplier": multiplier, "timestamp": timestamp,
                })
                expected_history[execution_id] = (side, remaining, multiplier)

        actual_close = sorted((
            str(self._get(x, "execution_id")),
            str(self._get(x, "source_lot_execution_id")),
            int(self._get(x, "quantity")),
            self._timestamp(self._get(x, "execution_timestamp")),
        ) for x in actual_close_events)
        if actual_close != sorted(expected_closes):
            issues.append("RUNTIME_LEDGER_CLOSE_EVENT_FIFO_MISMATCH")

        actual_history = {}
        for lot in actual_position_lot_history:
            execution_id = str(self._get(lot, "execution_id"))
            if execution_id in actual_history:
                issues.append(f"RUNTIME_LEDGER_DUPLICATE_POSITION_LOT_HISTORY_EXECUTION_ID:{execution_id}")
            actual_history[execution_id] = (
                str(self._get(lot, "side")).upper(),
                int(self._get(lot, "opened_quantity")),
                self._decimal(self._get(lot, "contract_multiplier"), "HISTORY_MULTIPLIER"),
            )
        if actual_history != expected_history:
            issues.append("RUNTIME_LEDGER_POSITION_LOT_HISTORY_MISMATCH")

        expected_open = {
            (instrument, lot["execution_id"]): (
                lot["side"], lot["qty"], lot["multiplier"], lot["timestamp"]
            )
            for instrument, queue in queues.items() for lot in queue if lot["qty"] > 0
        }
        actual_open = {}
        for lot in actual_open_position_lots:
            key = (str(self._get(lot, "instrument_id")), str(self._get(lot, "execution_id")))
            if key in actual_open:
                issues.append(f"RUNTIME_LEDGER_DUPLICATE_OPEN_POSITION_LOT_KEY:{key[0]}:{key[1]}")
            actual_open[key] = (
                str(self._get(lot, "side")).upper(),
                int(self._get(lot, "remaining_quantity")),
                self._decimal(self._get(lot, "contract_multiplier"), "OPEN_LOT_MULTIPLIER"),
                self._timestamp(self._get(lot, "execution_timestamp")),
            )
        if actual_open != expected_open:
            issues.append("RUNTIME_LEDGER_OPEN_POSITION_LOTS_MISMATCH")

        expected_fees = {str(x["execution_id"]): x for x in expected_fee_records}
        actual_fees = {str(self._get(x, "execution_id")): x for x in actual_fee_records}
        if len(expected_fees) != len(expected_fee_records) or len(actual_fees) != len(actual_fee_records):
            issues.append("RUNTIME_LEDGER_DUPLICATE_FEE_EXECUTION_ID")
        if set(expected_fees) != set(actual_fees) or set(expected_fees) != {str(x["execution_id"]) for x in executions}:
            issues.append("RUNTIME_LEDGER_EXECUTION_FEE_COVERAGE_MISMATCH")
        expected_fee_total = Decimal("0")
        actual_fee_total = Decimal("0")
        for execution_id, expected in expected_fees.items():
            expected_amount = self._decimal(expected["fee_amount"], "EXPECTED_FEE")
            expected_fee_total += expected_amount
            actual = actual_fees.get(execution_id)
            if actual is None:
                continue
            actual_amount = self._decimal(self._get(actual, "fee_amount"), "ACTUAL_FEE")
            actual_fee_total += actual_amount
            expected_qty = int(expected.get("quantity", expected.get("executed_quantity", 0)))
            expected_price = self._decimal(expected.get("price", expected.get("executed_price")), "EXPECTED_FEE_PRICE")
            if (actual_amount != expected_amount
                or int(self._get(actual, "executed_quantity")) != expected_qty
                or self._decimal(self._get(actual, "executed_price"), "ACTUAL_FEE_PRICE") != expected_price):
                issues.append(f"RUNTIME_LEDGER_FEE_VALUE_MISMATCH:{execution_id}")

        # Simulate VSSF weighted-average aggregate separately from FIFO lots.
        vssf_state: dict[str, dict[str, Any]] = {}
        expected_fifo_realized = Decimal("0")
        for row in opening_lots:
            instrument = str(row["instrument_id"])
            side = str(row["side"]).upper()
            qty = int(row["quantity"])
            price = self._decimal(row["unit_price"], "OPENING_PRICE")
            multiplier = self._decimal(row["contract_multiplier"], "OPENING_MULTIPLIER")
            state = vssf_state.get(instrument)
            if state is None:
                vssf_state[instrument] = {"side": side, "qty": qty, "avg": price, "multiplier": multiplier}
            elif state["side"] == side:
                total = state["qty"] + qty
                state["avg"] = (state["avg"] * state["qty"] + price * qty) / Decimal(total)
                state["qty"] = total

        opening_by_id = {str(x["execution_id"]): x for x in opening_lots}
        for close_id, source_id, close_qty, _ in expected_closes:
            close_row = next(x for x in ordered if str(x["execution_id"]) == close_id)
            source = opening_by_id.get(source_id) or next(
                (x for x in ordered if str(x["execution_id"]) == source_id), None
            )
            if source is None:
                issues.append(f"RUNTIME_LEDGER_SOURCE_LOT_NOT_FOUND:{source_id}")
                continue
            source_side = str(source["side"]).upper()
            source_price = self._decimal(source.get("unit_price", source.get("price")), "SOURCE_LOT_PRICE")
            close_price = self._decimal(close_row["price"], "CLOSE_PRICE")
            multiplier = self._decimal(close_row["contract_multiplier"], "CLOSE_MULTIPLIER")
            delta = close_price - source_price if source_side == "BUY" else source_price - close_price
            expected_fifo_realized += delta * close_qty * multiplier

        expected_vssf_realized = Decimal("0")
        for row in ordered:
            instrument = str(row["instrument_id"])
            side = str(row["side"]).upper()
            qty = int(row["quantity"])
            price = self._decimal(row["price"], "EXECUTION_PRICE")
            multiplier = self._decimal(row["contract_multiplier"], "EXECUTION_MULTIPLIER")
            state = vssf_state.get(instrument)
            if state is None:
                vssf_state[instrument] = {"side": side, "qty": qty, "avg": price, "multiplier": multiplier}
            elif state["side"] == side:
                total = state["qty"] + qty
                state["avg"] = (state["avg"] * state["qty"] + price * qty) / Decimal(total)
                state["qty"] = total
            else:
                close_qty = min(state["qty"], qty)
                delta = price - state["avg"] if state["side"] == "BUY" else state["avg"] - price
                expected_vssf_realized += delta * close_qty * state["multiplier"]
                old_left, new_left = state["qty"] - close_qty, qty - close_qty
                if old_left:
                    state["qty"] = old_left
                elif new_left:
                    vssf_state[instrument] = {"side": side, "qty": new_left, "avg": price, "multiplier": multiplier}
                else:
                    vssf_state.pop(instrument, None)

        expected_positions = {
            instrument: {"side": state["side"], "quantity": state["qty"], "average_price": state["avg"]}
            for instrument, state in vssf_state.items()
        }
        actual_positions = {
            instrument: {"side": str(row["side"]).upper(), "quantity": int(row["qty"]),
                         "average_price": self._decimal(row["avg_price"], "VSSF_AVERAGE_PRICE")}
            for instrument, row in vssf_positions.items()
        }
        if set(actual_positions) != set(expected_positions):
            issues.append("RUNTIME_LEDGER_VSSF_POSITION_AGGREGATE_MISMATCH")
        else:
            for instrument, expected in expected_positions.items():
                actual = actual_positions[instrument]
                if (actual["side"] != expected["side"] or actual["quantity"] != expected["quantity"]
                    or abs(actual["average_price"] - expected["average_price"]) > Decimal("0.000001")):
                    issues.append(f"RUNTIME_LEDGER_VSSF_POSITION_AGGREGATE_MISMATCH:{instrument}")

        expected_unrealized = Decimal("0")
        for instrument, state in vssf_state.items():
            if instrument not in mark_prices:
                issues.append(f"RUNTIME_LEDGER_MARK_PRICE_MISSING:{instrument}")
                continue
            mark = self._decimal(mark_prices[instrument], "MARK_PRICE")
            delta = mark - state["avg"] if state["side"] == "BUY" else state["avg"] - mark
            expected_unrealized += delta * state["qty"] * state["multiplier"]
        realized_delta = self._decimal(vssf_realized_pnl_delta, "VSSF_REALIZED_PNL")
        unrealized = self._decimal(vssf_unrealized_pnl, "VSSF_UNREALIZED_PNL")
        if abs(realized_delta - expected_vssf_realized) > Decimal("0.000001"):
            issues.append("RUNTIME_LEDGER_VSSF_REALIZED_PNL_DIVERGENCE")
        if abs(unrealized - expected_unrealized) > Decimal("0.000001"):
            issues.append("RUNTIME_LEDGER_VSSF_UNREALIZED_PNL_DIVERGENCE")

        manifest = {
            "version": self.VERSION, "source_namespace": source_namespace,
            "deterministic_rule_id": deterministic_rule_id,
            "source_manifest_sha256": str(source_manifest_sha256).lower(),
            "source_anchor_refs": sorted(str(x) for x in source_anchor_refs),
            "source_anchor_as_of": anchor.isoformat() if anchor else None,
            "scenario_timestamp": scenario.isoformat() if scenario else None,
            "evidence_refs": sorted(str(x) for x in evidence_refs),
            "execution_ids": sorted(str(x["execution_id"]) for x in executions),
            "expected_close_events": len(expected_closes), "actual_close_events": len(actual_close_events),
            "expected_fee_total": str(expected_fee_total), "actual_fee_total": str(actual_fee_total),
            "fifo_realized_pnl": str(expected_fifo_realized),
            "expected_vssf_average_cost_realized_pnl": str(expected_vssf_realized),
            "vssf_realized_pnl_delta": str(realized_delta),
            "expected_vssf_unrealized_pnl": str(expected_unrealized),
            "vssf_unrealized_pnl": str(unrealized),
            "fifo_vs_vssf_realized_method_delta": str(expected_fifo_realized - expected_vssf_realized),
            "read_only": True, "migration_applied": False,
        }
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        unique_issues = tuple(dict.fromkeys(issues))
        return ValidationOnlyRuntimeLedgerComparison(
            status="VALIDATION_ONLY_RUNTIME_LEDGER_RECONCILED" if not unique_issues else "RECONCILIATION_REQUIRED",
            issues=unique_issues, manifest=manifest, manifest_sha256=digest if not unique_issues else None,
        )
