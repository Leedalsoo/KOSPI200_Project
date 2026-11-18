"""Validation-only cross-source event-time alignment audit (FRESH-49)."""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib, json
from statistics import median
from typing import Any, Mapping, Sequence

class ValidationOnlyCrossSourceAlignmentAuditor:
    REPORT_VERSION = "Q25-A8-VALIDATION-ONLY-CROSS-SOURCE-ALIGNMENT-v1"

    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError("CROSS_SOURCE_ALIGNMENT_VALIDATION_ONLY_OPT_IN_REQUIRED")

    @staticmethod
    def _time(value: Any, label: str) -> datetime:
        if isinstance(value, datetime): parsed = value
        elif isinstance(value, str):
            try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc: raise ValueError(f"{label}_INVALID") from exc
        else: raise ValueError(f"{label}_INVALID")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{label}_TIMEZONE_REQUIRED")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _hash(value: Mapping[str, Any]) -> str:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _stats(values: Sequence[float]) -> dict[str, float | int | None]:
        if not values: return {"count": 0, "min_seconds": None, "median_seconds": None, "p90_seconds": None, "max_seconds": None}
        v = sorted(values)
        return {"count": len(v), "min_seconds": v[0], "median_seconds": median(v), "p90_seconds": v[int(.9*(len(v)-1))], "max_seconds": v[-1]}

    def audit(self, *, timestamp_groups: Sequence[Mapping[str, Any]], rest_observations: Sequence[Mapping[str, Any]], as_of: datetime | str, accepted_manifest_sha256: str, rest_source_manifest_sha256: str) -> dict[str, Any]:
        issues: list[str] = []
        try: audit_as_of = self._time(as_of, "AUDIT_AS_OF")
        except ValueError as exc: audit_as_of = None; issues.append(str(exc))
        for label, digest in (("ACCEPTED_MANIFEST", accepted_manifest_sha256), ("REST_SOURCE_MANIFEST", rest_source_manifest_sha256)):
            if len(str(digest)) != 64 or any(c not in "0123456789abcdefABCDEF" for c in str(digest)): issues.append(f"{label}_SHA256_INVALID")

        rest_index: dict[tuple[str,str], list[dict[str, Any]]] = defaultdict(list)
        rest_counts: Counter[str] = Counter()
        rest_lags: list[float] = []
        rest_identity_conflicts: list[dict[str, Any]] = []
        for i, row in enumerate(rest_observations):
            day, symbol = str(row.get("trading_date") or ""), str(row.get("symbol") or "")
            if not day or not symbol: issues.append(f"REST_IDENTITY_REQUIRED:{i}"); continue
            req, resp = str(row.get("request_symbol") or symbol), str(row.get("response_symbol") or symbol)
            if req != resp or resp != symbol:
                rest_identity_conflicts.append({"row_index":i,"symbol":symbol,"request_symbol":req,"response_symbol":resp})
                rest_counts["identity_mismatch"] += 1; continue
            try:
                collected = self._time(row.get("collected_at"), f"REST_COLLECTED_AT_{i}")
                source = self._time(row.get("source_event_time"), f"REST_SOURCE_EVENT_TIME_{i}") if row.get("source_event_time") else None
            except ValueError as exc: issues.append(f"REST_ROW_TIME_INVALID:{i}:{exc}"); continue
            if audit_as_of and collected > audit_as_of: issues.append(f"REST_COLLECTION_AFTER_AUDIT_AS_OF:{i}")
            rest_counts["rows"] += 1
            if source is None: rest_counts["missing_source_event_time"] += 1
            else:
                rest_counts["valid_source_event_time"] += 1
                lag = (collected-source).total_seconds(); rest_lags.append(lag)
                if lag < 0: rest_counts["negative_collection_lag"] += 1
            rest_index[(day,symbol)].append({"source":source,"collected":collected,"hash":str(row.get("payload_sha256") or ""),"identity":row.get("identity") or {}})

        totals: Counter[str] = Counter()
        by_day: dict[str,Counter[str]] = defaultdict(Counter)
        option_align: Counter[str] = Counter()
        underlying_align: Counter[str] = Counter()
        underlying_ages: dict[str, list[float]] = defaultdict(list)
        anchor_ages: list[float] = []
        option_lags: list[float] = []
        identity_conflicts: list[dict[str,Any]] = []
        details: list[dict[str,Any]] = []
        seen: set[str] = set()
        ordered = sorted(timestamp_groups, key=lambda g:(str(g.get("trading_date") or ""),str(g.get("timestamp") or "")))
        for gi, group in enumerate(ordered):
            day = str(group.get("trading_date") or "")
            gid = str(group.get("group_id") or f"{day}:{gi}")
            if gid in seen: issues.append(f"DUPLICATE_TIMESTAMP_GROUP_ID:{gid}")
            seen.add(gid)
            try: gt = self._time(group.get("timestamp"), f"GROUP_TIMESTAMP_{gi}")
            except ValueError as exc: issues.append(f"GROUP_TIME_INVALID:{gi}:{exc}"); continue
            if audit_as_of and gt > audit_as_of: issues.append(f"GROUP_AFTER_AUDIT_AS_OF:{gid}")
            totals["timestamp_groups"] += 1; by_day[day]["timestamp_groups"] += 1
            options = group.get("option_rows")
            if not isinstance(options,(list,tuple)) or not options: issues.append(f"GROUP_OPTION_ROWS_REQUIRED:{gid}"); options=()
            row_details=[]; has_anchor=False
            for oi, option in enumerate(options):
                symbol=str(option.get("symbol") or "")
                if not symbol: issues.append(f"OPTION_SYMBOL_REQUIRED:{gid}:{oi}"); continue
                totals["option_symbol_rows"] += 1; by_day[day]["option_symbol_rows"] += 1
                try:
                    event=self._time(option.get("source_observed_at"),"OPTION_SOURCE_EVENT_TIME")
                    received=self._time(option.get("collected_at"),"OPTION_COLLECTED_AT")
                    tick_time=self._time(option.get("timestamp"),"OPTION_TICK_TIMESTAMP")
                    if event != tick_time or tick_time != gt: issues.append(f"OPTION_EVENT_TIME_MISMATCH:{gid}:{symbol}")
                    if event > received: issues.append(f"OPTION_EVENT_AFTER_RECEIVE:{gid}:{symbol}")
                    if audit_as_of and received > audit_as_of: issues.append(f"OPTION_RECEIVE_AFTER_AUDIT_AS_OF:{gid}:{symbol}")
                    option_lags.append((received-event).total_seconds())
                except ValueError as exc: issues.append(f"OPTION_TIME_INVALID:{gid}:{symbol}:{exc}")
                candidates=rest_index.get((day,symbol),[])
                valid=[r for r in candidates if r["source"] is not None]
                prior=[r for r in valid if r["source"] <= gt]
                if prior:
                    chosen=max(prior,key=lambda r:r["source"]); age=(gt-chosen["source"]).total_seconds()
                    cls="REST_EXACT" if age==0 else "REST_NEAREST_PRIOR"
                    option_align[cls]+=1; by_day[day][cls]+=1; anchor_ages.append(age); has_anchor=True
                    oi_data=option.get("identity") or {}; ri=chosen["identity"]
                    mismatch={k:{"accepted":oi_data.get(k),"rest":ri.get(k)} for k in ("expiry","strike","option_type") if oi_data.get(k) is not None and ri.get(k) is not None and str(oi_data[k]) != str(ri[k])}
                    if mismatch: identity_conflicts.append({"group_id":gid,"symbol":symbol,"mismatches":mismatch})
                    row_details.append({"symbol":symbol,"rest_alignment":cls,"rest_anchor_time":chosen["source"].isoformat(),"rest_anchor_age_seconds":age,"rest_collected_at":chosen["collected"].isoformat(),"rest_payload_sha256":chosen["hash"],"identity_mismatches":mismatch})
                elif not candidates:
                    cls="NO_REST_SYMBOL"; option_align[cls]+=1; by_day[day][cls]+=1; row_details.append({"symbol":symbol,"rest_alignment":cls})
                elif not valid:
                    cls="NO_VALID_REST_SOURCE_TIME"; option_align[cls]+=1; by_day[day][cls]+=1; row_details.append({"symbol":symbol,"rest_alignment":cls})
                else:
                    cls="REST_FUTURE_ONLY"; option_align[cls]+=1; by_day[day][cls]+=1
                    row_details.append({"symbol":symbol,"rest_alignment":cls,"nearest_future_rest_time":min(r["source"] for r in valid).isoformat()})
            if has_anchor: totals["groups_with_rest_anchor"]+=1; by_day[day]["groups_with_rest_anchor"]+=1
            else: totals["groups_without_rest_anchor"]+=1; by_day[day]["groups_without_rest_anchor"]+=1

            under=group.get("underlying") or {}; src=str(under.get("source") or "")
            try: ut=self._time(under.get("source_event_time"),"UNDERLYING_SOURCE_EVENT_TIME") if under.get("source_event_time") else None
            except ValueError as exc: ut=None; issues.append(f"UNDERLYING_TIME_INVALID:{gid}:{exc}")
            if src == "SYNTHETIC:KRX_SHOCK_V4_NEAREST_SPOT": ucls="SYNTHETIC_DERIVED_ANCHOR"
            elif src == "KIS:H0UPCNT0:GROUP_MEDIAN": ucls="KIS_GROUP_MEDIAN_DERIVED"
            elif ut is None: ucls="UNDERLYING_SOURCE_TIME_MISSING"
            elif ut == gt: ucls="KIS_EXACT_TIMESTAMP"
            elif ut < gt: ucls="KIS_NEAREST_PRIOR"
            else: ucls="KIS_FUTURE_RELATIVE_TO_OPTION"; issues.append(f"UNDERLYING_FUTURE_ANCHOR:{gid}")
            underlying_align[ucls]+=1; by_day[day][ucls]+=1
            underlying_age=(gt-ut).total_seconds() if ut is not None else None
            if underlying_age is not None: underlying_ages[ucls].append(underlying_age)
            details.append({"group_id":gid,"trading_date":day,"timestamp":gt.isoformat(),"option_symbol_count":len(row_details),"rest_anchor_coverage":"HAS_PRIOR_OR_EXACT" if has_anchor else "NO_PRIOR_OR_EXACT","underlying_alignment":ucls,"underlying_source_event_time":ut.isoformat() if ut else None,"underlying_anchor_age_seconds":underlying_age,"underlying_source":src,"underlying_selection_method":under.get("selection_method"),"original_accepted_source":under.get("original_accepted_source"),"original_accepted_anchor_time":under.get("original_accepted_anchor_time"),"underlying_value":under.get("value"),"underlying_source_ref":under.get("source_ref"),"underlying_source_sha256":under.get("source_sha256"),"underlying_received_at":under.get("received_at"),"option_rows":row_details})

        report={"report_version":self.REPORT_VERSION,"scope":{"timestamp_groups":totals["timestamp_groups"],"option_symbol_rows":totals["option_symbol_rows"],"trading_dates":sorted(by_day),"accepted_manifest_sha256":accepted_manifest_sha256.lower(),"rest_source_manifest_sha256":rest_source_manifest_sha256.lower()},"rest_source_inventory":{**dict(rest_counts),"identity_mismatches":rest_identity_conflicts,"collection_lag_seconds":self._stats(rest_lags)},"accepted_option_event_to_collection_lag_seconds":self._stats(option_lags),"option_to_rest_alignment":{**dict(option_align),"rest_anchor_age_seconds":self._stats(anchor_ages)},"underlying_alignment":dict(underlying_align),"underlying_anchor_age_seconds_by_class":{k:self._stats(v) for k,v in sorted(underlying_ages.items())},"by_trading_date":{d:dict(c) for d,c in sorted(by_day.items())},"identity_mismatches":identity_conflicts,"timestamp_groups":details,"issues":sorted(set(issues)),"authority_claimed":False,"gate_release_permitted":False,"mutation_applied":False}
        report["report_sha256"]=self._hash(report)
        return report
