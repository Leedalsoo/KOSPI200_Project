"""Validation-only Option Master -> Quote -> OrderBook -> Execution lineage audit."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


class ValidationOnlyOptionLineageAuditor:
    REPORT_VERSION = "Q25-A8-VALIDATION-ONLY-OPTION-LINEAGE-v1"

    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError("OPTION_LINEAGE_VALIDATION_ONLY_OPT_IN_REQUIRED")

    @staticmethod
    def _time(value: Any, label: str) -> datetime | None:
        if value in (None, ""):
            return None
        if not isinstance(value, str):
            raise ValueError(f"{label}_INVALID")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label}_INVALID") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{label}_TIMEZONE_REQUIRED")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _identity(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
        strike = str(row.get("strike") or "")
        try:
            strike = format(Decimal(strike).normalize(), "f") if strike else ""
        except InvalidOperation:
            pass
        return (
            str(row.get("symbol") or row.get("instrument_id") or ""),
            str(row.get("expiry") or ""),
            str(row.get("option_type") or ""),
            strike,
        )

    @staticmethod
    def _hash(value: Mapping[str, Any]) -> str:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def audit(
        self,
        *,
        master_records: Sequence[Mapping[str, Any]],
        quote_records: Sequence[Mapping[str, Any]],
        orderbook_records: Sequence[Mapping[str, Any]],
        execution_records: Sequence[Mapping[str, Any]],
        source_manifest_hashes: Mapping[str, str],
    ) -> dict[str, Any]:
        issues: list[str] = []
        counts: Counter[str] = Counter()
        master_by_symbol: dict[str, list[Mapping[str, Any]]] = {}
        for row in master_records:
            symbol = str(row.get("symbol") or "")
            if not symbol:
                issues.append("MASTER_SYMBOL_REQUIRED")
                continue
            master_by_symbol.setdefault(symbol, []).append(row)
            if not row.get("master_sha256"):
                issues.append(f"MASTER_HASH_MISSING:{symbol}")
            counts["master_records"] += 1

        def master_match(row: Mapping[str, Any]) -> tuple[bool, str]:
            symbol = str(row.get("symbol") or row.get("instrument_id") or "")
            candidates = master_by_symbol.get(symbol, [])
            if not candidates:
                return False, "MASTER_SYMBOL_NOT_FOUND"
            identity = self._identity(row)
            exact = [m for m in candidates if self._identity(m) == identity]
            if not exact:
                return False, "MASTER_CONTRACT_IDENTITY_MISMATCH"
            digest = str(row.get("master_sha256") or "")
            if digest and not any(str(m.get("master_sha256") or "") == digest for m in exact):
                return True, "MASTER_SNAPSHOT_HASH_NOT_IN_CROSSWALK"
            return True, "MASTER_IDENTITY_MATCH"

        quote_by_id: dict[str, Mapping[str, Any]] = {}
        quote_by_symbol: dict[str, list[Mapping[str, Any]]] = {}
        quote_rows: list[dict[str, Any]] = []
        for i, row in enumerate(quote_records):
            symbol = str(row.get("symbol") or "")
            record_id = str(row.get("record_id") or f"quote:{i}")
            if not symbol:
                issues.append(f"QUOTE_SYMBOL_REQUIRED:{record_id}")
                continue
            ok, master_status = master_match(row)
            source_time = self._time(row.get("source_timestamp"), f"QUOTE_SOURCE_TIME_{i}")
            received = self._time(row.get("received_at"), f"QUOTE_RECEIVED_AT_{i}")
            if source_time is None:
                time_status = "SOURCE_TIME_MISSING_RECEIVE_ONLY" if received else "SOURCE_AND_RECEIVE_TIME_MISSING"
                counts["quote_missing_source_time"] += 1
            elif received and source_time > received:
                time_status = "SOURCE_AFTER_RECEIVE"
                issues.append(f"QUOTE_SOURCE_AFTER_RECEIVE:{record_id}")
            else:
                time_status = "SOURCE_TIME_PRESENT"
            if not ok:
                issues.append(f"QUOTE_MASTER_LINK:{record_id}:{master_status}")
            quote_by_id[record_id] = row
            quote_by_symbol.setdefault(symbol, []).append(row)
            quote_rows.append({
                "record_id": record_id,
                "symbol": symbol,
                "master_link": master_status,
                "identity_match": ok,
                "source_time_status": time_status,
                "source_timestamp": row.get("source_timestamp"),
                "source_timestamp_raw": row.get("source_timestamp_raw"),
                "generated_at": row.get("generated_at"),
                "source_anchor_timestamp": row.get("source_anchor_timestamp"),
                "received_at": row.get("received_at"),
                "provenance": row.get("provenance"),
                "synthetic": bool(row.get("synthetic")),
                "source_anchor_sha256": row.get("source_anchor_sha256"),
                "dataset_sha256": row.get("dataset_sha256"),
            })
            counts["quote_records"] += 1
            if ok:
                counts["quote_identity_matches"] += 1

        orderbook_rows: list[dict[str, Any]] = []
        orderbook_by_id: dict[str, Mapping[str, Any]] = {}
        for i, row in enumerate(orderbook_records):
            symbol = str(row.get("symbol") or "")
            record_id = str(row.get("record_id") or f"orderbook:{i}")
            ok, master_status = master_match(row)
            quote_ref = str(row.get("quote_record_id") or "")
            quote_ref_row = quote_by_id.get(quote_ref)
            quote_link = bool(
                quote_ref_row
                and self._identity(quote_ref_row) == self._identity(row)
                and str(row.get("quote_dataset_sha256") or "")
                == str(quote_ref_row.get("dataset_sha256") or "")
                and str(row.get("source_anchor_sha256") or "")
                == str(quote_ref_row.get("source_anchor_sha256") or "")
                and str(row.get("generated_at") or "")
                == str(quote_ref_row.get("generated_at") or "")
            )
            source_time = self._time(row.get("source_timestamp"), f"ORDERBOOK_SOURCE_TIME_{i}")
            received = self._time(row.get("received_at"), f"ORDERBOOK_RECEIVED_AT_{i}")
            levels = row.get("levels") or {}
            bids = levels.get("bids") or []
            asks = levels.get("asks") or []
            bid_populated = sum(1 for x in bids if float(x.get("price") or 0) > 0 and float(x.get("quantity") or 0) > 0)
            ask_populated = sum(1 for x in asks if float(x.get("price") or 0) > 0 and float(x.get("quantity") or 0) > 0)
            depth_status = "TWO_SIDED_DEPTH_PRESENT" if bid_populated and ask_populated else "ONE_SIDED_OR_EMPTY"
            if not ok:
                issues.append(f"ORDERBOOK_MASTER_LINK:{record_id}:{master_status}")
            if quote_ref and not quote_link:
                issues.append(f"ORDERBOOK_QUOTE_LINEAGE_MISMATCH:{record_id}")
            orderbook_by_id[record_id] = row
            orderbook_rows.append({
                "record_id": record_id,
                "symbol": symbol,
                "master_link": master_status,
                "identity_match": ok,
                "quote_lineage_linked": quote_link,
                "source_timestamp": row.get("source_timestamp"),
                "source_timestamp_raw": row.get("source_timestamp_raw"),
                "generated_at": row.get("generated_at"),
                "source_anchor_timestamp": row.get("source_anchor_timestamp"),
                "received_at": row.get("received_at"),
                "source_time_status": "SOURCE_TIME_MISSING" if source_time is None else "SOURCE_TIME_PRESENT",
                "depth_status": depth_status,
                "populated_bid_levels": bid_populated,
                "populated_ask_levels": ask_populated,
                "provenance": row.get("provenance"),
                "synthetic": bool(row.get("synthetic")),
                "source_anchor_sha256": row.get("source_anchor_sha256"),
                "dataset_sha256": row.get("dataset_sha256"),
            })
            counts["orderbook_records"] += 1
            if ok:
                counts["orderbook_identity_matches"] += 1
            if quote_link:
                counts["orderbook_quote_lineage_matches"] += 1
            if depth_status == "ONE_SIDED_OR_EMPTY":
                counts["orderbook_one_sided_or_empty"] += 1

        execution_rows: list[dict[str, Any]] = []
        for i, row in enumerate(execution_records):
            identity = row.get("instrument_identity") or {}
            normalized = {
                "symbol": row.get("broker_symbol") or row.get("instrument_id"),
                "expiry": identity.get("expiry"),
                "option_type": identity.get("option_type"),
                "strike": identity.get("strike"),
                "master_sha256": row.get("master_sha256") or identity.get("master_sha256"),
            }
            ok, master_status = master_match(normalized)
            instrument_id = str(row.get("instrument_id") or "")
            broker_symbol = str(row.get("broker_symbol") or "")
            same_symbol = bool(instrument_id and instrument_id == broker_symbol)
            execution_time = self._time(row.get("execution_timestamp"), f"EXECUTION_TIME_{i}")
            if not ok:
                issues.append(f"EXECUTION_MASTER_LINK:{row.get('execution_id')}:{master_status}")
            if not same_symbol:
                issues.append(f"EXECUTION_SYMBOL_MISMATCH:{row.get('execution_id')}")
            multiplier_source = str(identity.get("multiplier_source") or "")
            multiplier = identity.get("contract_multiplier")
            multiplier_status = (
                "VALIDATION_ONLY_ASSUMPTION"
                if multiplier is not None and "VALIDATION_ONLY" in multiplier_source
                else "UNVERIFIED_OR_MISSING"
            )
            linked_book = orderbook_by_id.get(str(row.get("orderbook_record_id") or ""))
            direct_book_link = bool(
                linked_book
                and (
                    str(row.get("execution_id") or "") in [str(x) for x in (linked_book.get("execution_ids") or [])]
                    or str(row.get("client_order_id") or "") in [str(x) for x in (linked_book.get("client_order_ids") or [])]
                )
            )
            execution_rows.append({
                "execution_id": row.get("execution_id"),
                "client_order_id": row.get("client_order_id"),
                "instrument_id": instrument_id,
                "broker_symbol": broker_symbol,
                "symbol_match": same_symbol,
                "master_link": master_status,
                "identity_match": ok,
                "execution_timestamp": row.get("execution_timestamp"),
                "adapter": row.get("adapter"),
                "execution_kind": row.get("execution_kind"),
                "multiplier": multiplier,
                "multiplier_status": multiplier_status,
                "orderbook_record_id": row.get("orderbook_record_id"),
                "orderbook_evidence_sha256": row.get("orderbook_evidence_sha256"),
                "multiplier_source": multiplier_source,
                "orderbook_lineage_linked": direct_book_link,
                "validation_only": bool(row.get("validation_only")),
            })
            counts["execution_records"] += 1
            if ok and same_symbol:
                counts["execution_identity_matches"] += 1
            if multiplier_status == "VALIDATION_ONLY_ASSUMPTION":
                counts["execution_validation_only_multiplier"] += 1

        report = {
            "report_version": self.REPORT_VERSION,
            "scope": {
                "master_records": len(master_records),
                "quote_records": len(quote_records),
                "orderbook_records": len(orderbook_records),
                "execution_records": len(execution_records),
                "source_manifest_hashes": dict(sorted(source_manifest_hashes.items())),
            },
            "counts": dict(sorted(counts.items())),
            "master_snapshot_crosswalk": [
                {
                    "symbol": symbol,
                    "identity_variants": len({self._identity(x) for x in rows}),
                    "master_hashes": sorted({str(x.get("master_sha256") or "") for x in rows}),
                }
                for symbol, rows in sorted(master_by_symbol.items())
            ],
            "quotes": quote_rows,
            "orderbooks": orderbook_rows,
            "executions": execution_rows,
            "chain_judgement": {
                "contract_identity_linked": bool(counts["execution_identity_matches"]),
                "quote_to_orderbook_lineage_linked": bool(counts["orderbook_quote_lineage_matches"]),
                "complete_observed_orderbook_available": any(x["depth_status"] == "TWO_SIDED_DEPTH_PRESENT" and not x["synthetic"] for x in orderbook_rows),
                "execution_to_orderbook_direct_linked": any(x["orderbook_lineage_linked"] for x in execution_rows),
                "real_execution_evidence": any(x.get("execution_kind") == "REAL_BROKER_EXECUTION" for x in execution_rows),
                "authoritative_multiplier_proven": any(x["multiplier_status"] == "AUTHORITATIVE" for x in execution_rows),
            },
            "issues": sorted(set(issues)),
            "authority_claimed": False,
            "gate_release_permitted": False,
            "mutation_applied": False,
        }
        report["report_sha256"] = self._hash(report)
        return report
