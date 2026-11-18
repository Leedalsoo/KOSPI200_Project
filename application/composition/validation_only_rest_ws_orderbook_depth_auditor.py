from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib, json, statistics
from typing import Any, Mapping, Sequence

class ValidationOnlyRestWsOrderBookDepthAuditor:
    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError('REST_WS_ORDERBOOK_VALIDATION_ONLY_OPT_IN_REQUIRED')

    @staticmethod
    def _time(value: Any, label: str) -> datetime | None:
        if value in (None, ''): return None
        if not isinstance(value, str): raise ValueError(f'{label}_INVALID')
        try: parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError as exc: raise ValueError(f'{label}_INVALID') from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError(f'{label}_TIMEZONE_REQUIRED')
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _num(value: Any) -> Decimal | None:
        if value in (None, ''): return None
        try:
            n=Decimal(str(value))
            return n if n.is_finite() else None
        except (InvalidOperation, ValueError): return None

    @staticmethod
    def _stats(values: Sequence[float]) -> dict[str,Any]:
        if not values: return {'count':0,'min':None,'median':None,'p90':None,'max':None}
        x=sorted(values)
        return {'count':len(x),'min':x[0],'median':statistics.median(x),'p90':x[int(.9*(len(x)-1))],'max':x[-1]}

    @staticmethod
    def _hash(value: Mapping[str,Any]) -> str:
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()

    def audit(self, *, rest_records: Sequence[Mapping[str,Any]], ws_records: Sequence[Mapping[str,Any]], source_hashes: Mapping[str,str]) -> dict[str,Any]:
        by_symbol=defaultdict(list); issues=[]; rest_lags=[]; ws_lags=[]
        for i,r in enumerate(rest_records):
            symbol=str(r.get('symbol') or ''); day=str(r.get('trading_date') or '')
            if not symbol or not day: issues.append(f'REST_IDENTITY_MISSING:{i}'); continue
            ts=self._time(r.get('source_timestamp_candidate'),f'REST_SOURCE_TIME_{i}')
            collected=self._time(r.get('collected_at'),f'REST_COLLECTED_AT_{i}')
            if ts is None: continue
            if collected:
                lag=(collected-ts).total_seconds(); rest_lags.append(lag)
                if lag<0: issues.append(f'REST_SOURCE_AFTER_COLLECTION:{r.get("record_id",i)}')
            by_symbol[(day,symbol)].append((ts,r))
        for values in by_symbol.values(): values.sort(key=lambda x:(x[0],str(x[1].get('record_id',''))))
        counts={'exact_source_time':0,'nearest_prior':0,'future_only':0,'no_rest_source':0,'rest_source_time_missing':0,'price_equal':0,'price_different':0,'price_both_empty':0,'price_one_empty':0,'price_missing':0,'quantity_equal':0,'quantity_different':0,'quantity_missing':0}
        per_level={side:{str(level):{'price_equal':0,'price_different':0,'price_both_empty':0,'price_one_empty':0,'price_missing':0,'quantity_equal':0,'quantity_different':0,'quantity_missing':0,'price_delta':[],'quantity_delta':[]} for level in range(1,6)} for side in ('bid','ask')}
        rows=[]; anchor_ages=[]; depth_rows=defaultdict(lambda:{'snapshots':0,'matched':0,'rest_time_missing':0,'future_only':0,'no_rest_source':0,'anchor_ages':[]})
        for i,w in enumerate(ws_records):
            symbol=str(w.get('symbol') or ''); day=str(w.get('trading_date') or '')
            if not symbol or not day: issues.append(f'WS_IDENTITY_MISSING:{i}'); continue
            candidate=self._time(w.get('source_timestamp_candidate'),f'WS_CANDIDATE_{i}')
            received=self._time(w.get('received_at'),f'WS_RECEIVED_{i}')
            if candidate is None:
                counts['rest_source_time_missing']+=1; rows.append({'record_id':w.get('record_id'),'trading_date':day,'symbol':symbol,'alignment':'WS_TIME_CANDIDATE_MISSING'}); continue
            if received:
                lag=(received-candidate).total_seconds(); ws_lags.append(lag)
                if lag<0: issues.append(f'WS_CANDIDATE_AFTER_RECEIVED:{w.get("record_id",i)}')
            candidates=by_symbol.get((day,symbol),[]); prior=[x for x in candidates if x[0]<=candidate]
            d=depth_rows[(day,symbol)]; d['snapshots']+=1
            if not prior:
                status='FUTURE_ONLY' if candidates else 'NO_REST_SOURCE'; key='future_only' if candidates else 'no_rest_source'; counts[key]+=1; d[key]+=1
                rows.append({'record_id':w.get('record_id'),'trading_date':day,'symbol':symbol,'alignment':status,'ws_time_candidate':w.get('source_timestamp_candidate'),'ws_received_at':w.get('received_at')}); continue
            rt,r=prior[-1]; age=(candidate-rt).total_seconds(); anchor_ages.append(age); d['matched']+=1; d['anchor_ages'].append(age)
            status='EXACT_SOURCE_TIME' if age==0 else 'NEAREST_PRIOR'; counts['exact_source_time' if age==0 else 'nearest_prior']+=1
            level_result={}
            for side in ('bid','ask'):
                rest_levels=r.get(f'{side}s') or []; ws_levels=w.get(f'{side}s') or []
                for idx in range(5):
                    a=rest_levels[idx] if idx<len(rest_levels) else {}; b=ws_levels[idx] if idx<len(ws_levels) else {}
                    rp=self._num(a.get('price')); wp=self._num(b.get('price')); rq=self._num(a.get('quantity')); wq=self._num(b.get('quantity'))
                    m=per_level[side][str(idx+1)]
                    if rp is None or wp is None:
                        m['price_missing']+=1; counts['price_missing']+=1; price_status='MISSING'
                    elif rp==0 and wp==0:
                        m['price_both_empty']+=1; counts['price_both_empty']+=1; price_status='BOTH_EMPTY'
                    elif rp==0 or wp==0:
                        m['price_one_empty']+=1; counts['price_one_empty']+=1; price_status='ONE_EMPTY'
                    elif rp==wp:
                        m['price_equal']+=1; counts['price_equal']+=1; price_status='EQUAL'
                    else:
                        m['price_different']+=1; counts['price_different']+=1; price_status='DIFFERENT'
                    if rp is not None and wp is not None and rp>0 and wp>0: m['price_delta'].append(float(rp-wp))
                    if rq is None or wq is None:
                        m['quantity_missing']+=1; counts['quantity_missing']+=1; qty_status='MISSING'
                    elif rq==wq:
                        m['quantity_equal']+=1; counts['quantity_equal']+=1; qty_status='EQUAL'
                    else:
                        m['quantity_different']+=1; counts['quantity_different']+=1; qty_status='DIFFERENT'
                    if rq is not None and wq is not None: m['quantity_delta'].append(float(rq-wq))
                    level_result[f'{side}{idx+1}']={'rest_price':str(rp) if rp is not None else None,'ws_price':str(wp) if wp is not None else None,'price_status':price_status,'rest_quantity':str(rq) if rq is not None else None,'ws_quantity':str(wq) if wq is not None else None,'quantity_status':qty_status}
            rows.append({'record_id':w.get('record_id'),'trading_date':day,'symbol':symbol,'alignment':status,'anchor_age_seconds':age,'rest_record_id':r.get('record_id'),'rest_source_timestamp_candidate':r.get('source_timestamp_candidate'),'rest_collected_at':r.get('collected_at'),'ws_time_candidate':w.get('source_timestamp_candidate'),'ws_received_at':w.get('received_at'),'levels':level_result,'rest_payload_sha256':r.get('payload_sha256'),'ws_payload_sha256':w.get('payload_sha256')})
        for side in per_level.values():
            for m in side.values():
                m['price_delta_stats']=self._stats(m.pop('price_delta')); m['quantity_delta_stats']=self._stats(m.pop('quantity_delta'))
        per_contract={}
        for (day,symbol),d in sorted(depth_rows.items()):
            ages=d.pop('anchor_ages'); d['anchor_age_stats']=self._stats(ages); per_contract[f'{day}:{symbol}']=d
        report={'report_version':'Q25-A8-VALIDATION-ONLY-REST-WS-ORDERBOOK-DEPTH-CROSS-v1','scope':{'trading_date':'20261001','rest_records':len(rest_records),'ws_orderbook_records':len(ws_records),'contracts':len(depth_rows),'source_hashes':dict(sorted(source_hashes.items()))},'counts':counts,'rest_source_to_collected_lag_seconds':self._stats(rest_lags),'ws_candidate_to_received_lag_seconds':self._stats(ws_lags),'rest_anchor_age_seconds':self._stats(anchor_ages),'per_level':per_level,'per_contract':per_contract,'alignments':rows,'issues':sorted(set(issues)),'rest_time_field':'order_book.output2.aspr_acpt_hour; candidate for paired REST response','ws_time_field':'H0IOASP0 payload HHMMSS; unverified candidate','official_event_time_claimed':False,'orderbook_is_broker_execution':False,'price_or_depth_semantics_authoritatively_certified':False,'freshness_threshold_applied':False,'authority_claimed':False,'gate_release_permitted':False,'mutation_applied':False}
        report['report_sha256']=self._hash(report); return report
