"""Validation-only nearest-prior alignment of REST quote timestamps to WS OrderBook candidates."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import statistics
from typing import Any, Mapping, Sequence


class ValidationOnlyRestWsOrderBookAlignmentAuditor:
    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError("REST_WS_ALIGNMENT_VALIDATION_ONLY_OPT_IN_REQUIRED")

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
    def _stats(values: Sequence[float]) -> dict[str, float | int | None]:
        if not values:
            return {"count": 0, "min": None, "median": None, "p90": None, "max": None}
        ordered = sorted(values)
        return {
            "count": len(ordered),
            "min": ordered[0],
            "median": statistics.median(ordered),
            "p90": ordered[int(0.9 * (len(ordered) - 1))],
            "max": ordered[-1],
        }

    @staticmethod
    def _hash(value: Mapping[str, Any]) -> str:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def audit(
        self,
        *,
        rest_records: Sequence[Mapping[str, Any]],
        orderbook_records: Sequence[Mapping[str, Any]],
        source_manifest_hashes: Mapping[str, str],
    ) -> dict[str, Any]:
        rest_by_symbol: dict[str, list[tuple[datetime, Mapping[str, Any]]]] = defaultdict(list)
        rest_lags: list[float] = []
        issues: list[str] = []
        for index, row in enumerate(rest_records):
            symbol = str(row.get("symbol") or "")
            if not symbol:
                issues.append(f"REST_SYMBOL_REQUIRED:{index}")
                continue
            source_time = self._time(row.get("source_timestamp"), f"REST_SOURCE_TIME_{index}")
            collected = self._time(row.get("collected_at"), f"REST_COLLECTED_AT_{index}")
            if source_time is None:
                continue
            if collected is not None:
                lag = (collected - source_time).total_seconds()
                rest_lags.append(lag)
                if lag < 0:
                    issues.append(f"REST_SOURCE_AFTER_COLLECTED:{row.get('record_id', index)}")
            rest_by_symbol[symbol].append((source_time, row))
        for symbol in rest_by_symbol:
            rest_by_symbol[symbol].sort(key=lambda item: (item[0], str(item[1].get("record_id", ""))))

        per_symbol: dict[str, dict[str, Any]] = {}
        all_ages: list[float] = []
        ws_lags: list[float] = []
        aligned_rows: list[dict[str, Any]] = []
        totals = {"exact_same_time": 0, "nearest_prior": 0, "future_only": 0, "no_rest_source_time": 0, "ws_source_after_received": 0}
        for index, row in enumerate(orderbook_records):
            symbol = str(row.get("symbol") or "")
            if not symbol:
                issues.append(f"ORDERBOOK_SYMBOL_REQUIRED:{index}")
                continue
            candidate = self._time(row.get("source_timestamp_candidate"), f"ORDERBOOK_CANDIDATE_TIME_{index}")
            received = self._time(row.get("received_at"), f"ORDERBOOK_RECEIVED_AT_{index}")
            bucket = per_symbol.setdefault(symbol, {"orderbook_rows": 0, "exact_same_time": 0, "nearest_prior": 0, "future_only": 0, "no_rest_source_time": 0, "anchor_ages_seconds": [], "source_timestamp_semantics": "RAW_HHMMSS_CANDIDATE_ONLY_NOT_OFFICIAL_EVENT_TIME"})
            bucket["orderbook_rows"] += 1
            if candidate is None:
                bucket["no_rest_source_time"] += 1
                totals["no_rest_source_time"] += 1
                aligned_rows.append({"record_id": row.get("record_id"), "symbol": symbol, "alignment": "ORDERBOOK_CANDIDATE_TIME_MISSING", "anchor_record_id": None, "anchor_age_seconds": None})
                continue
            if received is not None:
                lag = (received - candidate).total_seconds()
                ws_lags.append(lag)
                if lag < 0:
                    totals["ws_source_after_received"] += 1
                    issues.append(f"ORDERBOOK_CANDIDATE_AFTER_RECEIVED:{row.get('record_id', index)}")
            candidates = rest_by_symbol.get(symbol, [])
            prior = [item for item in candidates if item[0] <= candidate]
            if not prior:
                status = "FUTURE_REST_ONLY" if candidates else "NO_REST_SOURCE_TIME"
                bucket["future_only" if candidates else "no_rest_source_time"] += 1
                totals["future_only" if candidates else "no_rest_source_time"] += 1
                aligned_rows.append({"record_id": row.get("record_id"), "symbol": symbol, "alignment": status, "anchor_record_id": None, "anchor_age_seconds": None})
                continue
            anchor_time, anchor = prior[-1]
            age = (candidate - anchor_time).total_seconds()
            exact = age == 0
            status = "EXACT_SAME_TIME" if exact else "NEAREST_PRIOR"
            bucket["exact_same_time" if exact else "nearest_prior"] += 1
            totals["exact_same_time" if exact else "nearest_prior"] += 1
            bucket["anchor_ages_seconds"].append(age)
            all_ages.append(age)
            aligned_rows.append({
                "record_id": row.get("record_id"), "symbol": symbol, "alignment": status,
                "anchor_record_id": anchor.get("record_id"), "anchor_source_timestamp": anchor.get("source_timestamp"),
                "anchor_collected_at": anchor.get("collected_at"), "anchor_age_seconds": age,
                "anchor_content_sha256": anchor.get("content_sha256"),
                "orderbook_payload_sha256": row.get("payload_sha256"),
                "source_timestamp_candidate": row.get("source_timestamp_candidate"), "received_at": row.get("received_at"),
            })

        for bucket in per_symbol.values():
            bucket["anchor_age_stats"] = self._stats(bucket.pop("anchor_ages_seconds"))
        report = {
            "report_version": "Q25-A8-VALIDATION-ONLY-REST-WS-ORDERBOOK-ALIGNMENT-v1",
            "scope": {"rest_records": len(rest_records), "orderbook_records": len(orderbook_records), "symbols": len(per_symbol), "source_manifest_hashes": dict(sorted(source_manifest_hashes.items()))},
            "counts": totals,
            "rest_source_to_collection_lag_seconds": self._stats(rest_lags),
            "orderbook_candidate_to_received_lag_seconds": self._stats(ws_lags),
            "nearest_prior_anchor_age_seconds": self._stats(all_ages),
            "per_symbol": dict(sorted(per_symbol.items())),
            "alignments": aligned_rows,
            "issues": sorted(set(issues)),
            "freshness_threshold_applied": False,
            "official_event_time_semantics_claimed": False,
            "authority_claimed": False,
            "gate_release_permitted": False,
            "mutation_applied": False,
        }
        report["report_sha256"] = self._hash(report)
        return report
