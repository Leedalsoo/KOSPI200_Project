from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from application.composition.validation_only_runtime_evidence_supervisor import (
    ValidationOnlyRuntimeEvidenceCandidate,
)
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionEvent,
    U19ExecutionLedgerSnapshot,
    U19ExpectedGroupManifest,
    U19Position,
)


class ValidationOnlyVSSFRuntimeEvidenceAdapter:
    """Read-only bridge from the current Virtual VSSF/PositionLot/Fee read models.

    Broker snapshots and freshness verdicts are injected independently. The
    adapter never turns its own VSSF account projection into broker evidence.
    """

    VERSION = "Q25-A8-T6-VSSF-RUNTIME-EVIDENCE-v1"

    def __init__(
        self, *, bridge: Any, vssf_runtime: Any, run_id: str,
        candidate_id: str = "S2-CANDIDATE-001",
    ) -> None:
        if not str(run_id).strip():
            raise ValueError("T6_RUN_ID_REQUIRED")
        if not str(candidate_id).strip():
            raise ValueError("T6_CANDIDATE_ID_REQUIRED")
        if getattr(bridge, "run_id", None) != run_id:
            raise ValueError("T6_BRIDGE_RUN_ID_MISMATCH")
        store = getattr(bridge, "position_lot_store", None)
        fees = getattr(bridge, "fee_ledger", None)
        if not callable(getattr(store, "history", None)) or not callable(getattr(store, "open_lots", None)):
            raise TypeError("T6_VSSF_POSITION_LOT_STORE_REQUIRED")
        if not callable(getattr(fees, "snapshot", None)):
            raise TypeError("T6_VSSF_FEE_LEDGER_REQUIRED")
        if getattr(vssf_runtime, "account", None) is None:
            raise TypeError("T6_VSSF_ACCOUNT_REQUIRED")
        self.bridge = bridge
        self.vssf_runtime = vssf_runtime
        self.run_id = str(run_id)
        self.candidate_id = str(candidate_id)
        self.scope_group_id = (
            f"VALIDATION_ONLY:RUN:{self.run_id}:CANDIDATE:{self.candidate_id}"
        )

    @staticmethod
    def _aware(value: Any, code: str) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(code)
        return value.astimezone(UTC)

    @staticmethod
    def _sha256(value: Any) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _value(row: Any, key: str, default: Any = None) -> Any:
        return row.get(key, default) if isinstance(row, Mapping) else getattr(row, key, default)

    def build_candidate(
        self,
        *,
        as_of: datetime,
        broker_snapshot: U19BrokerPositionSnapshot,
        expected_group_manifest: U19ExpectedGroupManifest,
        freshness_verdict: Any,
        source_namespace: str,
        deterministic_rule_id: str,
        source_manifest_sha256: str,
        source_anchor_refs: tuple[str, ...],
        source_anchor_as_of: datetime,
        scenario_timestamp: datetime,
        evidence_refs: tuple[str, ...],
    ) -> ValidationOnlyRuntimeEvidenceCandidate:
        as_of_utc = self._aware(as_of, "T6_AS_OF_TIMEZONE_REQUIRED")
        anchor_utc = self._aware(source_anchor_as_of, "T6_SOURCE_ANCHOR_TIMEZONE_REQUIRED")
        scenario_utc = self._aware(scenario_timestamp, "T6_SCENARIO_TIMEZONE_REQUIRED")
        if anchor_utc > scenario_utc or scenario_utc > as_of_utc:
            raise ValueError("T6_SOURCE_SCENARIO_TIME_ORDER_INVALID")
        if not str(source_namespace).startswith(("SYNTHETIC:", "SYNTHETIC_CONTRACT:")):
            raise ValueError("T6_VALIDATION_SYNTHETIC_NAMESPACE_REQUIRED")
        if not str(deterministic_rule_id).strip():
            raise ValueError("T6_DETERMINISTIC_RULE_ID_REQUIRED")
        digest = str(source_manifest_sha256 or "")
        if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
            raise ValueError("T6_SOURCE_MANIFEST_SHA256_REQUIRED")
        if not source_anchor_refs or not evidence_refs:
            raise ValueError("T6_SOURCE_AND_EVIDENCE_REFS_REQUIRED")
        if not isinstance(broker_snapshot, U19BrokerPositionSnapshot):
            raise TypeError("T6_INDEPENDENT_VALIDATION_BROKER_SNAPSHOT_REQUIRED")
        if broker_snapshot.source != "VALIDATION_ONLY:BROKER_EXCHANGE":
            raise ValueError("T6_SYNTHETIC_BROKER_SNAPSHOT_CANNOT_CLAIM_LIVE_AUTHORITY")
        if not isinstance(expected_group_manifest, U19ExpectedGroupManifest):
            raise TypeError("T6_VALIDATION_EXPECTED_GROUP_MANIFEST_REQUIRED")

        scope_group_id = self.scope_group_id
        candidate_group_prefix = f"VALIDATION_ONLY:RUN:{self.run_id}:CANDIDATE:"
        other_candidate_groups = {
            str(group_id) for group_id in getattr(self.bridge, "groups", {})
            if str(group_id).startswith(candidate_group_prefix) and str(group_id) != scope_group_id
        }
        if other_candidate_groups:
            runtime_candidate_id = (
                getattr(self.vssf_runtime, "validation_candidate_id", None)
                or getattr(self.vssf_runtime.account, "validation_candidate_id", None)
            )
            if runtime_candidate_id != self.candidate_id:
                raise ValueError("T6_VSSF_RUNTIME_CANDIDATE_SCOPE_REQUIRED")
        if broker_snapshot.group_id != scope_group_id or expected_group_manifest.group_id != scope_group_id:
            raise ValueError("T6_BROKER_OR_EXPECTED_MANIFEST_RUN_SCOPE_MISMATCH")
        if self._aware(broker_snapshot.as_of, "T6_BROKER_SNAPSHOT_AS_OF_INVALID") != as_of_utc:
            raise ValueError("T6_BROKER_SNAPSHOT_AS_OF_MISMATCH")

        provenance = getattr(self.bridge, "provenance", {})
        execution_legs = getattr(self.bridge, "execution_legs", {})
        execution_rows: list[dict[str, Any]] = []
        order_accumulator: dict[str, dict[str, Any]] = {}
        seen_execution_ids: set[str] = set()

        report_group_by_execution_id: dict[str, str] = {}
        for group_id, reports in sorted(getattr(self.bridge, "groups", {}).items()):
            for report in tuple(reports):
                report_group_id = str(self._value(report, "group_id", group_id) or group_id)
                execution_key = str(self._value(report, "execution_id", "") or "").strip()
                if execution_key:
                    prior_group = report_group_by_execution_id.get(execution_key)
                    if prior_group is not None and prior_group != group_id:
                        raise ValueError(f"T6_VSSF_EXECUTION_CROSS_GROUP_COLLISION:{execution_key}")
                    report_group_by_execution_id[execution_key] = group_id
                if group_id != scope_group_id:
                    continue
                if report_group_id != scope_group_id:
                    raise ValueError(f"T6_VSSF_REPORT_GROUP_SCOPE_MISMATCH:{execution_key}")
                client_order_id = str(self._value(report, "client_order_id", "") or "").strip()
                if not client_order_id:
                    raise ValueError("T6_VSSF_ORDER_CLIENT_ID_MISSING")
                execution_id = str(self._value(report, "execution_id", "") or "").strip()
                filled_quantity = int(self._value(report, "filled_quantity", 0) or 0)
                remaining_quantity = int(self._value(report, "remaining_quantity", 0) or 0)
                status = str(self._value(report, "status", "") or "").upper()
                if not status:
                    raise ValueError(f"T6_VSSF_ORDER_STATUS_MISSING:{client_order_id}")

                item = order_accumulator.setdefault(client_order_id, {
                    "client_order_id": client_order_id,
                    "broker_order_id": self._value(report, "broker_order_id") or client_order_id,
                    "group_id": str(self._value(report, "group_id", group_id) or group_id),
                    "leg_id": str(self._value(report, "leg_id", "") or ""),
                    "instrument_id": None,
                    "side": None,
                    "quantity_filled": 0,
                    "remaining_quantity": remaining_quantity,
                    "status": status,
                })
                item["quantity_filled"] += filled_quantity
                item["remaining_quantity"] = max(item["remaining_quantity"], remaining_quantity)
                item["status"] = status
                item["group_id"] = str(self._value(report, "group_id", group_id) or group_id)
                item["leg_id"] = str(self._value(report, "leg_id", item["leg_id"]) or item["leg_id"])

                if filled_quantity <= 0:
                    continue
                if not execution_id or execution_id in seen_execution_ids:
                    raise ValueError(f"T6_VSSF_EXECUTION_ID_MISSING_OR_DUPLICATE:{execution_id}")
                seen_execution_ids.add(execution_id)
                source = provenance.get(execution_id)
                leg_meta = execution_legs.get(execution_id)
                if not isinstance(source, Mapping) or not isinstance(leg_meta, Mapping):
                    raise TypeError(f"T6_VSSF_EXECUTION_PROVENANCE_MISSING:{execution_id}")
                if str(source.get("group_id") or "") != scope_group_id:
                    raise ValueError(f"T6_VSSF_EXECUTION_PROVENANCE_GROUP_MISMATCH:{execution_id}")
                instrument_id = str(source.get("instrument_id") or "").strip()
                leg_id = str(source.get("leg_id") or self._value(report, "leg_id", "") or "").strip()
                side = str(leg_meta.get("side") or "").upper()
                multiplier = leg_meta.get("contract_multiplier")
                price = self._value(report, "execution_price")
                executed_at = self._value(report, "execution_timestamp")
                fee = self._value(report, "fee")
                if not instrument_id or not leg_id or side not in {"BUY", "SELL"} or multiplier is None or price is None or executed_at is None or fee is None:
                    raise ValueError(f"T6_VSSF_EXECUTION_FIELDS_INCOMPLETE:{execution_id}")
                executed_at_utc = self._aware(executed_at, "T6_VSSF_EXECUTION_TIME_INVALID")
                if executed_at_utc > as_of_utc:
                    raise ValueError(f"T6_VSSF_EXECUTION_AFTER_AS_OF:{execution_id}")
                price_value = Decimal(str(price))
                fee_value = Decimal(str(fee))
                multiplier_value = Decimal(str(multiplier))
                if price_value <= 0 or fee_value < 0 or multiplier_value <= 0:
                    raise ValueError(f"T6_VSSF_EXECUTION_VALUE_INVALID:{execution_id}")
                row = {
                    "execution_id": execution_id,
                    "client_order_id": client_order_id,
                    "broker_order_id": str(self._value(report, "broker_order_id") or client_order_id),
                    "group_id": str(source.get("group_id") or group_id),
                    "leg_id": leg_id,
                    "instrument_id": instrument_id,
                    "side": side,
                    "quantity": int(filled_quantity),
                    "price": price_value,
                    "contract_multiplier": multiplier_value,
                    "executed_at": executed_at_utc,
                    "fee_amount": fee_value,
                }
                execution_rows.append(row)
                item["instrument_id"] = instrument_id
                item["side"] = side

        for _plan, leg, command in getattr(self.bridge, "pending_legs", {}).values():
            command_group_id = str(getattr(command, "group_id", "") or "")
            if command_group_id != scope_group_id:
                continue
            client_id = str(getattr(command, "client_order_id", "") or "").strip()
            if not client_id:
                raise ValueError("T6_PENDING_VSSF_ORDER_CLIENT_ID_MISSING")
            identity = getattr(command, "instrument_identity", None)
            item = order_accumulator.setdefault(client_id, {
                "client_order_id": client_id,
                "broker_order_id": client_id,
                "group_id": str(getattr(command, "group_id", "") or ""),
                "leg_id": str(getattr(command, "leg_id", "") or getattr(leg, "leg_id", "")),
                "instrument_id": getattr(identity, "instrument_id", None),
                "side": str(getattr(command, "side", "")).upper(),
                "quantity_filled": 0,
                "remaining_quantity": int(getattr(command, "quantity", 0) or 0),
                "status": "NEW",
            })
            item["remaining_quantity"] = max(item["remaining_quantity"], int(getattr(command, "quantity", 0) or 0))

        order_rows: list[dict[str, Any]] = []
        pending_order_ids: list[str] = []
        for client_id, item in sorted(order_accumulator.items()):
            quantity_filled = int(item["quantity_filled"])
            remaining = int(item["remaining_quantity"])
            quantity = quantity_filled + remaining
            if quantity <= 0:
                raise ValueError(f"T6_VSSF_ORDER_QUANTITY_UNRESOLVED:{client_id}")
            if not item["group_id"] or not item["leg_id"]:
                raise ValueError(f"T6_VSSF_ORDER_GROUP_LEG_LINEAGE_MISSING:{client_id}")
            if item["instrument_id"] is None or item["side"] is None:
                raise ValueError(f"T6_VSSF_ORDER_INSTRUMENT_SIDE_UNRESOLVED:{client_id}")
            order_rows.append({
                "client_order_id": client_id,
                "broker_order_id": str(item["broker_order_id"]),
                "group_id": str(item["group_id"]),
                "leg_id": str(item["leg_id"]),
                "instrument_id": str(item["instrument_id"]),
                "side": str(item["side"]),
                "quantity": quantity,
                "filled_quantity": quantity_filled,
                "status": str(item["status"]),
            })
            if remaining > 0 and str(item["status"]).upper() not in {"FILLED", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED"}:
                pending_order_ids.append(client_id)

        signed_quantities: dict[str, int] = {}
        for row in execution_rows:
            signed_quantities[row["instrument_id"]] = signed_quantities.get(row["instrument_id"], 0) + (
                row["quantity"] if row["side"] == "BUY" else -row["quantity"]
            )
        ledger_positions = tuple(
            U19Position(instrument_id, Decimal(quantity))
            for instrument_id, quantity in sorted(signed_quantities.items()) if quantity
        )
        execution_events = tuple(
            U19ExecutionEvent(row["execution_id"], self._sha256(row))
            for row in sorted(execution_rows, key=lambda value: value["execution_id"])
        )
        ledger_payload = {
            "group_id": scope_group_id,
            "as_of": as_of_utc.isoformat(),
            "positions": [{"instrument_id": row.instrument_id, "signed_quantity": str(row.signed_quantity)} for row in ledger_positions],
            "execution_events": [{"execution_id": row.execution_id, "fingerprint": row.fingerprint} for row in execution_events],
            "pending_order_ids": sorted(set(pending_order_ids)),
            "source": "VALIDATION_ONLY:EXECUTION_LEDGER",
        }
        ledger_snapshot = U19ExecutionLedgerSnapshot(
            group_id=scope_group_id,
            snapshot_id=f"{self.run_id}:{as_of_utc.isoformat()}",
            as_of=as_of_utc,
            source="VALIDATION_ONLY:EXECUTION_LEDGER",
            positions=ledger_positions,
            complete=True,
            payload_sha256=self._sha256(ledger_payload),
            execution_events=execution_events,
            pending_order_ids=tuple(sorted(set(pending_order_ids))),
        )

        lot_store = self.bridge.position_lot_store
        all_run_history = tuple(lot for lot in lot_store.history() if getattr(lot, "run_id", None) == self.run_id)
        all_run_open_lots = tuple(lot for lot in lot_store.open_lots() if getattr(lot, "run_id", None) == self.run_id)
        lot_group_by_execution_id: dict[str, str] = {}
        for lot in (*all_run_history, *all_run_open_lots):
            lot_group_id = str(getattr(lot, "group_id", "") or "")
            lot_execution_id = str(getattr(lot, "execution_id", "") or "")
            if not lot_group_id or not lot_execution_id:
                raise ValueError("T6_VSSF_POSITION_LOT_GROUP_LINEAGE_MISSING")
            prior_group = lot_group_by_execution_id.get(lot_execution_id)
            if prior_group is not None and prior_group != lot_group_id:
                raise ValueError(f"T6_VSSF_POSITION_LOT_CROSS_GROUP_COLLISION:{lot_execution_id}")
            lot_group_by_execution_id[lot_execution_id] = lot_group_id
        history = tuple(lot for lot in all_run_history if getattr(lot, "group_id", None) == scope_group_id)
        open_lots = tuple(lot for lot in all_run_open_lots if getattr(lot, "group_id", None) == scope_group_id)
        close_events_all = tuple(lot_store.close_events())
        close_events_list = []
        for event in close_events_all:
            closing_id = str(getattr(event, "execution_id", "") or "")
            source_lot_id = str(getattr(event, "source_lot_execution_id", "") or "")
            closing_group = report_group_by_execution_id.get(closing_id) or lot_group_by_execution_id.get(closing_id)
            source_group = lot_group_by_execution_id.get(source_lot_id)
            if scope_group_id not in {closing_group, source_group}:
                continue
            if not closing_group or not source_group:
                raise ValueError("T6_VSSF_CLOSE_EVENT_GROUP_LINEAGE_INCOMPLETE")
            if closing_group != source_group:
                raise ValueError("T6_VSSF_CROSS_GROUP_POSITION_LOT_CLOSE")
            if closing_group == scope_group_id:
                close_events_list.append(event)
        close_events = tuple(close_events_list)
        fees_all = tuple(self.bridge.fee_ledger.snapshot(run_id=self.run_id))
        for fee in fees_all:
            if not str(self._value(fee, "group_id", "") or "").strip():
                raise ValueError("T6_VSSF_FEE_GROUP_LINEAGE_MISSING")
        fees = tuple(fee for fee in fees_all if self._value(fee, "group_id") == scope_group_id)
        # This is a run-from-flat ledger: every VSSF fill is in executions.
        # Do not also seed those same fills as opening_lots (that double counts).
        opening_lots: tuple[dict[str, Any], ...] = ()

        symbol_to_instrument: dict[str, str] = {}
        for value in provenance.values():
            if not isinstance(value, Mapping) or str(value.get("group_id") or "") != scope_group_id:
                continue
            symbol = str(value.get("symbol") or "").strip()
            instrument = str(value.get("instrument_id") or "").strip()
            if symbol and instrument:
                prior = symbol_to_instrument.get(symbol)
                if prior is not None and prior != instrument:
                    raise ValueError(f"T6_VSSF_ACCOUNT_SYMBOL_IDENTITY_AMBIGUOUS:{symbol}")
                symbol_to_instrument[symbol] = instrument

        vssf_positions: dict[str, dict[str, Any]] = {}
        mark_prices: dict[str, Decimal] = {}
        account_positions = getattr(self.vssf_runtime.account, "positions", None)
        if not isinstance(account_positions, Mapping):
            raise TypeError("T6_VSSF_ACCOUNT_POSITIONS_UNAVAILABLE")
        execution_instruments = {row["instrument_id"] for row in execution_rows}
        for symbol, state in account_positions.items():
            if not isinstance(state, Mapping):
                raise TypeError(f"T6_VSSF_ACCOUNT_POSITION_INVALID:{symbol}")
            instrument_id = str(symbol) if str(symbol) in execution_instruments else symbol_to_instrument.get(str(symbol))
            if not instrument_id:
                raise ValueError(f"T6_VSSF_ACCOUNT_POSITION_IDENTITY_UNRESOLVED:{symbol}")
            vssf_positions[instrument_id] = {
                "side": str(state.get("side") or "").upper(),
                "qty": int(state.get("qty", 0)),
                "avg_price": Decimal(str(state.get("avg_price"))),
            }
            mark = state.get("mark_price")
            if mark is not None:
                mark_prices[instrument_id] = Decimal(str(mark))

        if set(vssf_positions) != {row.instrument_id for row in ledger_positions}:
            raise ValueError("T6_VSSF_ACCOUNT_AND_EXECUTION_POSITION_SET_MISMATCH")
        if any(instrument not in mark_prices for instrument in vssf_positions):
            raise ValueError("T6_VSSF_OPEN_POSITION_MARK_PRICE_UNAVAILABLE")

        expected_fee_records = [{
            "execution_id": row["execution_id"],
            "fee_amount": row["fee_amount"],
            "quantity": row["quantity"],
            "price": row["price"],
        } for row in execution_rows]
        invariant_inputs = {
            "order_commands": tuple(order_rows),
            "executions": tuple(execution_rows),
            "ledger_evidence": {
                "opening_lots": tuple(opening_lots),
                "executions": tuple(execution_rows),
                "expected_fee_records": tuple(expected_fee_records),
                "actual_position_lot_history": history,
                "actual_open_position_lots": open_lots,
                "actual_close_events": close_events,
                "actual_fee_records": fees,
                "vssf_positions": vssf_positions,
                "vssf_realized_pnl_delta": Decimal(str(self.vssf_runtime.account.realized_pnl)),
                "vssf_unrealized_pnl": Decimal(str(self.vssf_runtime.account.unrealized_pnl)),
                "mark_prices": mark_prices,
                "source_namespace": source_namespace,
                "deterministic_rule_id": deterministic_rule_id,
                "source_manifest_sha256": digest.lower(),
                "source_anchor_refs": source_anchor_refs,
                "source_anchor_as_of": anchor_utc,
                "scenario_timestamp": scenario_utc,
                "evidence_refs": evidence_refs,
            },
            "source_namespace": source_namespace,
            "deterministic_rule_id": deterministic_rule_id,
            "source_manifest_sha256": digest.lower(),
            "source_anchor_refs": source_anchor_refs,
            "source_anchor_as_of": anchor_utc,
            "scenario_timestamp": scenario_utc,
            "evidence_refs": evidence_refs,
        }
        return ValidationOnlyRuntimeEvidenceCandidate(
            group_id=scope_group_id,
            broker_snapshot=broker_snapshot,
            ledger_snapshot=ledger_snapshot,
            invariant_inputs=invariant_inputs,
            freshness_verdict=freshness_verdict,
            expected_group_manifest=expected_group_manifest,
        )
