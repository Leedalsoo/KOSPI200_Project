"""Validation-only alignment of H0IOASP0 OrderBook snapshots to H0IOCNT0 trade prints."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib, json, statistics
from typing import Any, Mapping, Sequence

class ValidationOnlyTradeOrderBookCrossAuditor:
    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError("TRADE_ORDERBOOK_VALIDATION_ONLY_OPT_IN_REQUIRED")

    @staticmethod
    def _time(value: Any, label: str) -> datetime | None:
        if value in (None, ""): return None
        if not isinstance(value, str): raise ValueError(f"{label}_INVALID")
        try: parsed=datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc: raise ValueError(f"{label}_INVALID") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError(f"{label}_TIMEZONE_REQUIRED")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _number(value: Any) -> Decimal | None:
        if value in (None, ""): return None
        try: return Decimal(str(value))
        except InvalidOperation: return None

    @staticmethod
    def _stats(values: Sequence[float]) -> dict[str, Any]:
        if not values: return {"count":0,"min":None,"median":None,"p90":None,"max":None}
        x=sorted(values)
        return {"count":len(x),"min":x[0],"median":statistics.median(x),"p90":x[int(.9*(len(x)-1))],"max":x[-1]}

    @staticmethod
    def _hash(value: Mapping[str, Any]) -> str:
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()

    def audit(self, *, trade_records: Sequence[Mapping[str, Any]], orderbook_records: Sequence[Mapping[str, Any]], source_manifest_hashes: Mapping[str,str]) -> dict[str,Any]:
        by_symbol=defaultdict(list);trade_lags=[];issues=[]
        for i,r in enumerate(trade_records):
            s=str(r.get("symbol") or "")
            if not s: issues.append(f"TRADE_SYMBOL_REQUIRED:{i}");continue
            t=self._time(r.get("source_timestamp_candidate"),f"TRADE_TIME_{i}");recv=self._time(r.get("received_at"),f"TRADE_RECEIVED_{i}")
            if t is None: issues.append(f"TRADE_SOURCE_TIME_MISSING:{r.get('record_id',i)}");continue
            if recv is not None:
                lag=(recv-t).total_seconds();trade_lags.append(lag)
                if lag<0:issues.append(f"TRADE_SOURCE_AFTER_RECEIVED:{r.get('record_id',i)}")
            by_symbol[s].append((t,r))
        for s in by_symbol:by_symbol[s].sort(key=lambda x:(x[0],str(x[1].get("record_id",""))))
        rows=[];ages=[];book_lags=[];counts={"exact_same_time":0,"nearest_prior_trade":0,"future_trade_only":0,"no_trade_source":0,"bid_equal":0,"ask_equal":0,"both_equal":0,"both_different":0,"missing_top_price":0}
        per=defaultdict(lambda:{"orderbook_rows":0,"exact_same_time":0,"nearest_prior_trade":0,"future_trade_only":0,"no_trade_source":0,"anchor_ages":[],"bid_equal":0,"ask_equal":0,"both_equal":0,"both_different":0,"missing_top_price":0})
        for i,b in enumerate(orderbook_records):
            s=str(b.get("symbol") or "")
            if not s:issues.append(f"ORDERBOOK_SYMBOL_REQUIRED:{i}");continue
            t=self._time(b.get("source_timestamp_candidate"),f"ORDERBOOK_TIME_{i}");recv=self._time(b.get("received_at"),f"ORDERBOOK_RECEIVED_{i}");x=per[s];x["orderbook_rows"]+=1
            if t is None:
                counts["no_trade_source"]+=1;x["no_trade_source"]+=1;rows.append({"record_id":b.get("record_id"),"symbol":s,"alignment":"ORDERBOOK_SOURCE_TIME_MISSING"});continue
            if recv is not None:
                lag=(recv-t).total_seconds();book_lags.append(lag)
                if lag<0:issues.append(f"ORDERBOOK_SOURCE_AFTER_RECEIVED:{b.get('record_id',i)}")
            candidates=by_symbol.get(s,[]);prior=[z for z in candidates if z[0]<=t]
            if not prior:
                status="FUTURE_TRADE_ONLY" if candidates else "NO_TRADE_SOURCE";key="future_trade_only" if candidates else "no_trade_source";counts[key]+=1;x[key]+=1;rows.append({"record_id":b.get("record_id"),"symbol":s,"alignment":status});continue
            at,a=prior[-1];age=(t-at).total_seconds();ages.append(age);x["anchor_ages"].append(age);exact=age==0;status="EXACT_SAME_TIME" if exact else "NEAREST_PRIOR_TRADE";key="exact_same_time" if exact else "nearest_prior_trade";counts[key]+=1;x[key]+=1
            bb=self._number(b.get("bid_price"));ba=self._number(a.get("bid_price"));ab=self._number(b.get("ask_price"));aa=self._number(a.get("ask_price"));missing=any(v is None for v in (bb,ba,ab,aa));beq=not missing and bb==ba;aeq=not missing and ab==aa;both=beq and aeq
            if missing:counts["missing_top_price"]+=1;x["missing_top_price"]+=1
            else:
                counts["bid_equal"]+=int(beq);counts["ask_equal"]+=int(aeq);counts["both_equal"]+=int(both);counts["both_different"]+=int(not both)
                x["bid_equal"]+=int(beq);x["ask_equal"]+=int(aeq);x["both_equal"]+=int(both);x["both_different"]+=int(not both)
            rows.append({"record_id":b.get("record_id"),"symbol":s,"alignment":status,"anchor_record_id":a.get("record_id"),"anchor_age_seconds":age,"trade_source_timestamp_candidate":a.get("source_timestamp_candidate"),"trade_received_at":a.get("received_at"),"orderbook_source_timestamp_candidate":b.get("source_timestamp_candidate"),"orderbook_received_at":b.get("received_at"),"trade_last_price":a.get("last_price"),"trade_volume":a.get("volume"),"trade_bid_price":a.get("bid_price"),"orderbook_bid_price":b.get("bid_price"),"bid_equal":beq,"trade_ask_price":a.get("ask_price"),"orderbook_ask_price":b.get("ask_price"),"ask_equal":aeq,"trade_payload_sha256":a.get("payload_sha256"),"orderbook_payload_sha256":b.get("payload_sha256")})
        for x in per.values():x["anchor_age_stats"]=self._stats(x.pop("anchor_ages"))
        report={"report_version":"Q25-A8-VALIDATION-ONLY-TRADE-ORDERBOOK-CROSS-v1","scope":{"trade_records":len(trade_records),"orderbook_records":len(orderbook_records),"symbols":len(per),"source_manifest_hashes":dict(sorted(source_manifest_hashes.items()))},"counts":counts,"trade_source_to_received_lag_seconds":self._stats(trade_lags),"orderbook_candidate_to_received_lag_seconds":self._stats(book_lags),"nearest_prior_trade_age_seconds":self._stats(ages),"per_symbol":dict(sorted(per.items())),"alignments":rows,"issues":sorted(set(issues)),"freshness_threshold_applied":False,"official_orderbook_event_time_claimed":False,"market_trade_is_broker_execution":False,"authority_claimed":False,"gate_release_permitted":False,"mutation_applied":False}
        report["report_sha256"]=self._hash(report);return report
