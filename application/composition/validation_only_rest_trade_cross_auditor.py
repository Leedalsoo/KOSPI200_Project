from __future__ import annotations
from collections import defaultdict
from datetime import datetime, date, time, timezone
from decimal import Decimal, InvalidOperation
import hashlib, json, statistics
from typing import Any, Mapping, Sequence

class ValidationOnlyRestTradeCrossAuditor:
    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError('REST_TRADE_VALIDATION_ONLY_OPT_IN_REQUIRED')

    @staticmethod
    def _time(value: Any, label: str) -> datetime | None:
        if value in (None, ''): return None
        if not isinstance(value, str): raise ValueError(f'{label}_INVALID')
        try: parsed=datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as exc: raise ValueError(f'{label}_INVALID') from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError(f'{label}_TIMEZONE_REQUIRED')
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _num(value: Any) -> Decimal | None:
        if value in (None, ''): return None
        try:
            x=Decimal(str(value).strip())
            return x if x.is_finite() else None
        except (InvalidOperation, ValueError): return None

    @staticmethod
    def _stats(values: Sequence[float]) -> dict[str, Any]:
        if not values: return {'count':0,'min':None,'median':None,'p90':None,'max':None}
        x=sorted(values)
        return {'count':len(x),'min':x[0],'median':statistics.median(x),'p90':x[int(.9*(len(x)-1))],'max':x[-1]}

    @staticmethod
    def _hash(value: Mapping[str, Any]) -> str:
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()

    def audit(self, *, trades: Sequence[Mapping[str, Any]], rest: Sequence[Mapping[str, Any]], source_hashes: Mapping[str,str]) -> dict[str,Any]:
        by_symbol=defaultdict(list); issues=[]; trade_lags=[]
        for i,t in enumerate(trades):
            symbol=str(t.get('symbol') or '')
            trading_date=str(t.get('trading_date') or '')
            if not symbol: issues.append(f'TRADE_SYMBOL_MISSING:{i}'); continue
            ts=self._time(t.get('source_timestamp_candidate'),f'TRADE_TIME_{i}')
            received=self._time(t.get('received_at'),f'TRADE_RECEIVED_{i}')
            if ts is None: issues.append(f'TRADE_TIME_MISSING:{t.get("record_id",i)}'); continue
            if received:
                lag=(received-ts).total_seconds(); trade_lags.append(lag)
                if lag < 0: issues.append(f'TRADE_AFTER_RECEIVED:{t.get("record_id",i)}')
            by_symbol[(trading_date,symbol)].append((ts,t))
        for values in by_symbol.values(): values.sort(key=lambda x:(x[0],str(x[1].get('record_id',''))))
        counts={'exact_source_time':0,'nearest_prior_source_time':0,'nearest_prior_receive_time_proxy':0,'future_trade_only':0,'no_trade_source':0,'missing_rest_price':0,'last_equal':0,'bid_equal':0,'ask_equal':0,'all_three_equal':0,'any_price_different':0}
        rows=[]; ages=[]; source_ages=[]; proxy_ages=[]; deltas={'last':[],'bid':[],'ask':[]}; per=defaultdict(lambda:{'rows':0,'source_time_rows':0,'receive_proxy_rows':0,'no_trade_source':0,'future_trade_only':0,'ages':[],'last_equal':0,'bid_equal':0,'ask_equal':0,'all_three_equal':0,'any_price_different':0})
        for i,r in enumerate(rest):
            symbol=str(r.get('symbol') or '')
            trading_date=str(r.get('trading_date') or '')
            if not symbol: issues.append(f'REST_SYMBOL_MISSING:{i}'); continue
            target=self._time(r.get('source_timestamp'),f'REST_SOURCE_TIME_{i}')
            mode='REST_SOURCE_TIME'
            if target is None:
                target=self._time(r.get('collected_at'),f'REST_COLLECTED_AT_{i}')
                mode='COLLECTED_AT_RECEIVE_TIME_PROXY'
            x=per[symbol]; x['rows']+=1
            if target is None:
                counts['no_trade_source']+=1; x['no_trade_source']+=1
                rows.append({'record_id':r.get('record_id'),'trading_date':trading_date,'symbol':symbol,'alignment':'REST_TIME_UNAVAILABLE'}); continue
            candidates=by_symbol.get((trading_date,symbol),[]); prior=[z for z in candidates if z[0] <= target]
            if not prior:
                status='FUTURE_TRADE_ONLY' if candidates else 'NO_TRADE_SOURCE'
                key='future_trade_only' if candidates else 'no_trade_source'
                counts[key]+=1; x[key]+=1
                rows.append({'record_id':r.get('record_id'),'trading_date':trading_date,'symbol':symbol,'alignment':status,'comparison_time_mode':mode,'comparison_time':target.isoformat()}); continue
            ts,t=prior[-1]; age=(target-ts).total_seconds(); ages.append(age); x['ages'].append(age)
            if mode=='REST_SOURCE_TIME':
                counts['exact_source_time' if age==0 else 'nearest_prior_source_time']+=1; x['source_time_rows']+=1; source_ages.append(age)
            else:
                counts['nearest_prior_receive_time_proxy']+=1; x['receive_proxy_rows']+=1; proxy_ages.append(age)
            rest_last=self._num(r.get('last_price')); rest_bid=self._num(r.get('bid_price')); rest_ask=self._num(r.get('ask_price'))
            trade_last=self._num(t.get('last_price')); trade_bid=self._num(t.get('bid_price')); trade_ask=self._num(t.get('ask_price'))
            pairs={'last':(rest_last,trade_last),'bid':(rest_bid,trade_bid),'ask':(rest_ask,trade_ask)}
            eq={k:(a is not None and b is not None and a==b) for k,(a,b) in pairs.items()}
            valid={k:(a is not None and b is not None) for k,(a,b) in pairs.items()}
            for k,(a,b) in pairs.items():
                if valid[k]: deltas[k].append(float(a-b))
            if not all(valid.values()): counts['missing_rest_price']+=1
            for k in ('last','bid','ask'):
                if eq[k]: counts[f'{k}_equal']+=1; x[f'{k}_equal']+=1
            all_eq=all(eq.values()) and all(valid.values())
            any_diff=all(valid.values()) and not all_eq
            if all_eq: counts['all_three_equal']+=1; x['all_three_equal']+=1
            if any_diff: counts['any_price_different']+=1; x['any_price_different']+=1
            rows.append({'record_id':r.get('record_id'),'trading_date':trading_date,'symbol':symbol,'alignment':'EXACT_SOURCE_TIME' if age==0 and mode=='REST_SOURCE_TIME' else 'NEAREST_PRIOR_TRADE','comparison_time_mode':mode,'comparison_time':target.isoformat(),'trade_record_id':t.get('record_id'),'trade_source_timestamp_candidate':t.get('source_timestamp_candidate'),'trade_received_at':t.get('received_at'),'anchor_age_seconds':age,'rest_last':str(rest_last) if rest_last is not None else None,'trade_last':str(trade_last) if trade_last is not None else None,'last_equal':eq['last'],'rest_bid':str(rest_bid) if rest_bid is not None else None,'trade_bid':str(trade_bid) if trade_bid is not None else None,'bid_equal':eq['bid'],'rest_ask':str(rest_ask) if rest_ask is not None else None,'trade_ask':str(trade_ask) if trade_ask is not None else None,'ask_equal':eq['ask'],'rest_payload_sha256':r.get('payload_sha256'),'trade_payload_sha256':t.get('payload_sha256')})
        for x in per.values(): x['anchor_age_stats']=self._stats(x.pop('ages'))
        report={'report_version':'Q25-A8-VALIDATION-ONLY-REST-TRADE-CROSS-v1','scope':{'rest_records':len(rest),'trade_records':len(trades),'symbols':len(per),'source_hashes':dict(sorted(source_hashes.items()))},'counts':counts,'trade_source_to_received_lag_seconds':self._stats(trade_lags),'all_anchor_age_seconds':self._stats(ages),'rest_source_time_anchor_age_seconds':self._stats(source_ages),'collected_at_proxy_anchor_age_seconds':self._stats(proxy_ages),'price_delta_rest_minus_trade':{k:self._stats(v) for k,v in deltas.items()},'per_symbol':dict(sorted(per.items())),'alignments':rows,'issues':sorted(set(issues)),'rest_source_time_preferred':True,'collected_at_used_only_as_receive_time_proxy':True,'trade_time_semantics':'H0IOCNT0 BSOP_HOUR candidate; not independently certified official event time','rest_price_semantics':'KIS REST futs_prpr; source event time may be absent; collected_at is receive/collection time only','price_equality_is_not_execution_proof':True,'market_trade_is_broker_execution':False,'authority_claimed':False,'freshness_threshold_applied':False,'gate_release_permitted':False,'mutation_applied':False}
        report['report_sha256']=self._hash(report); return report
