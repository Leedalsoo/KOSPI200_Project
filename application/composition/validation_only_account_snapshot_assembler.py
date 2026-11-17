"""Validation-only account snapshot bundle assembler.

This module defines an internal normalized fixture contract. It is not a KIS
API schema or a production account adapter.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class SnapshotSection:
    snapshot_id: str
    as_of: datetime
    source: str
    payload_sha256: str
    rows: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class SyntheticSnapshotProvenance:
    namespace: str
    deterministic_rule_id: str
    manifest_sha256: str
    scenario_timestamp: datetime
    source_anchor_refs: tuple[str, ...] = ()
    source_anchor_as_of: datetime | None = None


@dataclass(frozen=True)
class AccountSnapshotBundle:
    orders: SnapshotSection
    executions: SnapshotSection
    positions: SnapshotSection
    opening_positions: SnapshotSection
    provenance: SyntheticSnapshotProvenance


@dataclass(frozen=True)
class AccountSnapshotValidation:
    status: str
    issues: tuple[str, ...]
    normalized_positions: tuple[Mapping[str, Any], ...]
    snapshot_ids: tuple[str, ...]
    as_of: datetime | None
    evidence_sha256: str | None

    @property
    def is_valid(self) -> bool:
        return self.status == "VALIDATION_ONLY_RECONCILED"

    def baseline_positions_payload(self) -> tuple[Mapping[str, Any], ...]:
        if not self.is_valid:
            raise ValueError("ACCOUNT_SNAPSHOT_BUNDLE_NOT_RECONCILED")
        return self.normalized_positions


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def snapshot_rows_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(
        [_json_value(row) for row in rows], sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _signed(side: str, quantity: int) -> int:
    if side in {"BUY", "LONG"}:
        return quantity
    if side in {"SELL", "SHORT"}:
        return -quantity
    if side == "FLAT" and quantity == 0:
        return 0
    raise ValueError("SIDE_OR_QUANTITY_INVALID")


def validate_account_snapshot_bundle(bundle: AccountSnapshotBundle) -> AccountSnapshotValidation:
    """Cross-check order, fill and position identity/quantity without KIS assumptions."""
    issues: list[str] = []
    sections = (bundle.orders, bundle.executions, bundle.positions, bundle.opening_positions)
    ids = tuple(str(section.snapshot_id).strip() for section in sections)
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        issues.append("SNAPSHOT_IDS_MISSING_OR_NOT_DISTINCT")

    for section in sections:
        if not _aware(section.as_of):
            issues.append(f"SNAPSHOT_TIMEZONE_UNSPECIFIED:{section.snapshot_id}")
        if not str(section.source).startswith("VALIDATION_ONLY:"):
            issues.append(f"NON_VALIDATION_SOURCE_REJECTED:{section.snapshot_id}")
        if re.fullmatch(r"[0-9a-f]{64}", str(section.payload_sha256).lower()) is None:
            issues.append(f"SNAPSHOT_SHA256_INVALID:{section.snapshot_id}")
        elif snapshot_rows_sha256(section.rows) != str(section.payload_sha256).lower():
            issues.append(f"SNAPSHOT_SHA256_MISMATCH:{section.snapshot_id}")

    provenance = bundle.provenance
    if provenance.namespace not in {"SYNTHETIC:DERIVED_SCENARIO", "SYNTHETIC_CONTRACT:VALIDATION"}:
        issues.append("SYNTHETIC_NAMESPACE_INVALID")
    if not provenance.deterministic_rule_id.strip():
        issues.append("SYNTHETIC_DETERMINISTIC_RULE_REQUIRED")
    if re.fullmatch(r"[0-9a-f]{64}", provenance.manifest_sha256.lower()) is None:
        issues.append("SYNTHETIC_MANIFEST_SHA256_INVALID")
    if not _aware(provenance.scenario_timestamp):
        issues.append("SYNTHETIC_SCENARIO_TIMESTAMP_UNSPECIFIED")
    if provenance.source_anchor_as_of is not None:
        if not _aware(provenance.source_anchor_as_of):
            issues.append("SYNTHETIC_SOURCE_ANCHOR_TIME_UNSPECIFIED")
        elif _aware(provenance.scenario_timestamp) and _utc(provenance.source_anchor_as_of) > _utc(provenance.scenario_timestamp):
            issues.append("SYNTHETIC_FUTURE_SOURCE_ANCHOR")
    if any(not str(ref).strip() for ref in provenance.source_anchor_refs):
        issues.append("SYNTHETIC_SOURCE_ANCHOR_REF_INVALID")

    if any(not _aware(section.as_of) for section in sections) or not _aware(provenance.scenario_timestamp):
        common_as_of = None
    else:
        common_as_of = _utc(bundle.orders.as_of)
        if any(_utc(section.as_of) != common_as_of for section in sections[:3]):
            issues.append("ORDERS_EXECUTIONS_POSITIONS_AS_OF_MISMATCH")
        if _utc(provenance.scenario_timestamp) != common_as_of:
            issues.append("SCENARIO_TIMESTAMP_NOT_ALIGNED_TO_SNAPSHOT")
        if _utc(bundle.opening_positions.as_of) > common_as_of:
            issues.append("OPENING_POSITION_SNAPSHOT_AFTER_ACCOUNT_SNAPSHOT")

    orders_by_client: dict[str, Mapping[str, Any]] = {}
    orders_by_broker: dict[str, Mapping[str, Any]] = {}
    for row in bundle.orders.rows:
        client_id = str(row.get("client_order_id") or "").strip()
        broker_id = str(row.get("broker_order_id") or "").strip()
        instrument = str(row.get("instrument_id") or "").strip()
        side = str(row.get("side") or "").upper()
        quantity = row.get("order_quantity")
        cumulative = row.get("cumulative_filled_quantity")
        status = str(row.get("status") or "").upper()
        if not client_id or not broker_id or not instrument:
            issues.append("ORDER_IDENTITY_FIELDS_MISSING")
            continue
        if client_id in orders_by_client or broker_id in orders_by_broker:
            issues.append("ORDER_IDENTITY_DUPLICATE")
            continue
        if side not in {"BUY", "SELL"}:
            issues.append(f"ORDER_SIDE_INVALID:{broker_id}")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            issues.append(f"ORDER_QUANTITY_INVALID:{broker_id}")
        if not isinstance(cumulative, int) or isinstance(cumulative, bool) or cumulative < 0:
            issues.append(f"ORDER_CUMULATIVE_QUANTITY_INVALID:{broker_id}")
        elif isinstance(quantity, int) and not isinstance(quantity, bool) and cumulative > quantity:
            issues.append(f"ORDER_OVERFILLED:{broker_id}")
        if status not in {"OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"}:
            issues.append(f"ORDER_STATUS_NOT_IN_NORMALIZED_CONTRACT:{broker_id}")
        if status == "FILLED" and isinstance(quantity, int) and cumulative != quantity:
            issues.append(f"FILLED_ORDER_QUANTITY_MISMATCH:{broker_id}")
        if status == "PARTIALLY_FILLED" and isinstance(quantity, int) and not (0 < cumulative < quantity):
            issues.append(f"PARTIAL_ORDER_QUANTITY_MISMATCH:{broker_id}")
        if status == "OPEN" and cumulative != 0:
            issues.append(f"OPEN_ORDER_HAS_CUMULATIVE_FILLS:{broker_id}")
        if status == "REJECTED" and cumulative != 0:
            issues.append(f"REJECTED_ORDER_HAS_FILLS:{broker_id}")
        orders_by_client[client_id] = row
        orders_by_broker[broker_id] = row

    for broker_id, row in orders_by_broker.items():
        parent_id = str(row.get("replaces_broker_order_id") or "").strip()
        if parent_id:
            parent = orders_by_broker.get(parent_id)
            if parent is None:
                issues.append(f"REPLACEMENT_PARENT_NOT_FOUND:{broker_id}")
            elif any(parent.get(key) != row.get(key) for key in ("instrument_id", "side")):
                issues.append(f"REPLACEMENT_IDENTITY_MISMATCH:{broker_id}")

    fills_by_broker: dict[str, int] = {}
    execution_ids: set[str] = set()
    signed_fill_by_instrument: dict[str, int] = {}
    for row in bundle.executions.rows:
        execution_id = str(row.get("execution_id") or "").strip()
        client_id = str(row.get("client_order_id") or "").strip()
        broker_id = str(row.get("broker_order_id") or "").strip()
        if not execution_id or not client_id or not broker_id:
            issues.append("EXECUTION_IDENTITY_FIELDS_MISSING")
            continue
        if execution_id in execution_ids:
            issues.append(f"EXECUTION_ID_DUPLICATE:{execution_id}")
            continue
        execution_ids.add(execution_id)
        order = orders_by_broker.get(broker_id)
        if order is None or str(order.get("client_order_id")) != client_id:
            issues.append(f"EXECUTION_ORDER_CORRELATION_MISMATCH:{execution_id}")
            continue
        if any(row.get(key) != order.get(key) for key in ("instrument_id", "side")):
            issues.append(f"EXECUTION_ORDER_CONTRACT_MISMATCH:{execution_id}")
            continue
        quantity = row.get("filled_quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            issues.append(f"EXECUTION_QUANTITY_INVALID:{execution_id}")
            continue
        try:
            price = Decimal(str(row.get("execution_price")))
            if not price.is_finite() or price <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            issues.append(f"EXECUTION_PRICE_INVALID:{execution_id}")
            continue
        executed_at = row.get("execution_timestamp")
        if not isinstance(executed_at, datetime) or not _aware(executed_at):
            issues.append(f"EXECUTION_TIMESTAMP_UNSPECIFIED:{execution_id}")
        elif common_as_of is not None:
            if _utc(executed_at) > common_as_of:
                issues.append(f"EXECUTION_AFTER_SNAPSHOT_AS_OF:{execution_id}")
            if _aware(bundle.opening_positions.as_of) and _utc(executed_at) < _utc(bundle.opening_positions.as_of):
                issues.append(f"EXECUTION_BEFORE_OPENING_POSITION_SNAPSHOT:{execution_id}")
        try:
            signed_delta = _signed(str(row.get("side")).upper(), quantity)
        except ValueError:
            issues.append(f"EXECUTION_SIDE_INVALID:{execution_id}")
            continue
        fills_by_broker[broker_id] = fills_by_broker.get(broker_id, 0) + quantity
        instrument = str(row.get("instrument_id"))
        signed_fill_by_instrument[instrument] = signed_fill_by_instrument.get(instrument, 0) + signed_delta

    for broker_id, order in orders_by_broker.items():
        expected = order.get("cumulative_filled_quantity")
        actual = fills_by_broker.get(broker_id, 0)
        if isinstance(expected, int) and not isinstance(expected, bool) and expected != actual:
            issues.append(f"ORDER_EXECUTION_CUMULATIVE_QUANTITY_MISMATCH:{broker_id}:{expected}:{actual}")

    opening_signed: dict[str, int] = {}
    for row in bundle.opening_positions.rows:
        instrument = str(row.get("instrument_id") or "").strip()
        quantity = row.get("quantity")
        side = str(row.get("side") or "").upper()
        if not instrument or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
            issues.append("OPENING_POSITION_IDENTITY_OR_QUANTITY_INVALID")
            continue
        if instrument in opening_signed:
            issues.append(f"OPENING_POSITION_DUPLICATE:{instrument}")
            continue
        try:
            opening_signed[instrument] = _signed(side, quantity)
        except ValueError:
            issues.append(f"OPENING_POSITION_SIDE_INVALID:{instrument}")

    final_signed: dict[str, int] = {}
    normalized_positions: list[Mapping[str, Any]] = []
    for row in bundle.positions.rows:
        instrument = str(row.get("instrument_id") or "").strip()
        quantity = row.get("quantity")
        side = str(row.get("side") or "").upper()
        if not instrument or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
            issues.append("FINAL_POSITION_IDENTITY_OR_QUANTITY_INVALID")
            continue
        if instrument in final_signed:
            issues.append(f"FINAL_POSITION_DUPLICATE:{instrument}")
            continue
        try:
            signed_quantity = _signed(side, quantity)
        except ValueError:
            issues.append(f"FINAL_POSITION_SIDE_INVALID:{instrument}")
            continue
        final_signed[instrument] = signed_quantity
        normalized_positions.append({
            "instrument_id": instrument,
            "side": "LONG" if signed_quantity > 0 else "SHORT" if signed_quantity < 0 else None,
            "qty": abs(signed_quantity),
            "avg_price": row.get("avg_price"),
        })

    all_instruments = set(opening_signed) | set(signed_fill_by_instrument) | set(final_signed)
    for instrument in sorted(all_instruments):
        expected = opening_signed.get(instrument, 0) + signed_fill_by_instrument.get(instrument, 0)
        actual = final_signed.get(instrument, 0)
        if expected != actual:
            issues.append(f"POSITION_EXECUTION_QUANTITY_MISMATCH:{instrument}:{expected}:{actual}")

    canonical_evidence = {
        "snapshot_ids": ids,
        "as_of": common_as_of.isoformat() if common_as_of else None,
        "section_hashes": [section.payload_sha256 for section in sections],
        "provenance": {
            "namespace": provenance.namespace,
            "rule": provenance.deterministic_rule_id,
            "manifest_sha256": provenance.manifest_sha256,
            "scenario_timestamp": provenance.scenario_timestamp.isoformat() if _aware(provenance.scenario_timestamp) else None,
            "source_anchor_refs": list(provenance.source_anchor_refs),
            "source_anchor_as_of": provenance.source_anchor_as_of.isoformat() if provenance.source_anchor_as_of and _aware(provenance.source_anchor_as_of) else None,
        },
    }
    evidence_sha256 = hashlib.sha256(json.dumps(canonical_evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    unique_issues = tuple(dict.fromkeys(issues))
    return AccountSnapshotValidation(
        status="VALIDATION_ONLY_RECONCILED" if not unique_issues else "RECONCILIATION_REQUIRED",
        issues=unique_issues,
        normalized_positions=tuple(normalized_positions) if not unique_issues else (),
        snapshot_ids=ids,
        as_of=common_as_of,
        evidence_sha256=evidence_sha256,
    )
