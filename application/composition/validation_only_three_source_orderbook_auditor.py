from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib, json, statistics
from typing import Any, Mapping, Sequence

class ValidationOnlyThreeSourceOrderBookAuditor:
    def __init__(self, *, validation_only: bool = False) -> None:
        if validation_only is not True:
            raise ValueError('THREE_SOURCE_VALIDATION_ONLY_OPT_IN_REQUIRED')

    @staticmethod
    def _time(value: Any, label: str) -> datetime | None:
        if value in (None,''): return None
        if not isinstance(value,str): raise ValueError(f'{label}_INVALID')
        try: t=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError as exc: raise ValueError(f'{label}_INVALID') from exc
        if t.tzinfo is None or t.utcoffset() is None: raise ValueError(f'{label}_TIMEZONE_REQUIRED')
        return t.astimezone(timezone.utc)

    @staticmethod
    def _num(value: Any) -> Decimal | None:
        if value in (None,''): return None
        try:
            n=Decimal(str(value))
            return n if n.is_finite() else None
        except (InvalidOperation,ValueError): return None

    @staticmethod
    def _stats(values: Sequence[float]) -> dict[str,Any]:
        if not values: return {'count':0,'min':None,'median':None,'p90':None,'max':None}
        x=sorted(values)
        return {'count':len(x),'min':x[0],'median':statistics.median(x),'p90':x[int(.9*(len(x)-1))],'max':x[-1]}

    @staticmethod
    def _hash(value: Mapping[str,Any]) -> str:
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()

    @staticmethod
    def _compare(a: Decimal | None,b: Decimal | None) -> str:
        if a is None or b is None: return 'MISSING'
        if a==0 and b==0: return 'BOTH_EMPTY'
        if a==0 or b==0: return 'ONE_EMPTY'
        return 'EQUAL' if a==b else 'DIFFERENT'

    def audit(self, *, triples: Sequence[Mapping[str,Any]], source_hashes: Mapping[str,str]) -> dict[str,Any]:
        counts=defaultdict(int); issues=[]; rest_ages=[]; trade_ages=[]; ws_lags=[]; rest_lags=[]; trade_lags=[]
        metrics={}
        for pair in ('rest_vs_ws','trade_vs_ws','rest_vs_trade'):
            metrics[pair]={side:{'price_equal':0,'price_different':0,'price_both_empty':0,'price_one_empty':0,'price_missing':0,'price_delta':[]} for side in ('bid','ask')}
        quantities={side:{'equal':0,'different':0,'both_empty':0,'one_empty':0,'missing':0,'delta':[]} for side in ('bid','ask')}
        consensus={side:{'all_three_equal':0,'all_three_different_or_mixed':0,'missing_or_empty':0} for side in ('bid','ask')}
        rows=[]
        for i,x in enumerate(triples):
            day=str(x.get('trading_date') or ''); symbol=str(x.get('symbol') or '')
            if not day or not symbol: issues.append(f'IDENTITY_MISSING:{i}'); continue
            candidate=self._time(x.get('ws_time_candidate'),f'WS_TIME_{i}')
            received=self._time(x.get('ws_received_at'),f'WS_RECEIVED_{i}')
            if candidate is None: counts['ws_time_missing']+=1; continue
            if received:
                lag=(received-candidate).total_seconds(); ws_lags.append(lag)
                if lag<0: issues.append(f'WS_CANDIDATE_AFTER_RECEIVED:{x.get("record_id",i)}')
            rest=x.get('rest_anchor'); trade=x.get('trade_anchor'); ws=x.get('ws_orderbook') or {}
            if not rest: counts['no_rest_anchor']+=1
            if not trade: counts['no_trade_anchor']+=1
            rest_age=None; trade_age=None
            if rest:
                if str(rest.get('trading_date') or day)!=day: issues.append(f'REST_CROSS_DAY_ANCHOR:{x.get("record_id",i)}'); rest=None
                else:
                    rt=self._time(rest.get('source_timestamp_candidate'),f'REST_TIME_{i}')
                    if rt is None: counts['rest_anchor_time_missing']+=1; rest=None
                    elif rt>candidate: counts['future_rest_anchor']+=1; rest=None
                    else:
                        rest_age=(candidate-rt).total_seconds(); rest_ages.append(rest_age)
                        counts['exact_rest_anchor' if rest_age==0 else 'nearest_prior_rest_anchor']+=1
                        collected=self._time(rest.get('collected_at'),f'REST_COLLECTED_{i}')
                        if collected:
                            lag=(collected-rt).total_seconds(); rest_lags.append(lag)
                            if lag<0: issues.append(f'REST_SOURCE_AFTER_COLLECTION:{x.get("record_id",i)}')
            if trade:
                if str(trade.get('trading_date') or day)!=day: issues.append(f'TRADE_CROSS_DAY_ANCHOR:{x.get("record_id",i)}'); trade=None
                else:
                    tt=self._time(trade.get('source_timestamp_candidate'),f'TRADE_TIME_{i}')
                    if tt is None: counts['trade_anchor_time_missing']+=1; trade=None
                    elif tt>candidate: counts['future_trade_anchor']+=1; trade=None
                    else:
                        trade_age=(candidate-tt).total_seconds(); trade_ages.append(trade_age)
                        counts['exact_trade_anchor' if trade_age==0 else 'nearest_prior_trade_anchor']+=1
                        received_trade=self._time(trade.get('received_at'),f'TRADE_RECEIVED_{i}')
                        if received_trade:
                            lag=(received_trade-tt).total_seconds(); trade_lags.append(lag)
                            if lag<0: issues.append(f'TRADE_SOURCE_AFTER_RECEIVED:{x.get("record_id",i)}')
            values={}
            for side in ('bid','ask'):
                wprice=self._num(ws.get(f'{side}_price')); wqty=self._num(ws.get(f'{side}_quantity'))
                rprice=self._num(rest.get(f'{side}_price')) if rest else None; rqty=self._num(rest.get(f'{side}_quantity')) if rest else None
                tprice=self._num(trade.get(f'{side}_price')) if trade else None
                comparisons={'rest_vs_ws':(rprice,wprice),'trade_vs_ws':(tprice,wprice),'rest_vs_trade':(rprice,tprice)}
                side_values={}
                for pair,(a,b) in comparisons.items():
                    status=self._compare(a,b); m=metrics[pair][side]
                    key={'EQUAL':'price_equal','DIFFERENT':'price_different','BOTH_EMPTY':'price_both_empty','ONE_EMPTY':'price_one_empty','MISSING':'price_missing'}[status]
                    m[key]+=1; counts[f'{pair}_{side}_{status.lower()}']+=1
                    if a is not None and b is not None and a>0 and b>0: m['price_delta'].append(float(a-b))
                    side_values[pair]=status
                qstatus=self._compare(rqty,wqty); qkey={'EQUAL':'equal','DIFFERENT':'different','BOTH_EMPTY':'both_empty','ONE_EMPTY':'one_empty','MISSING':'missing'}[qstatus]
                quantities[side][qkey]+=1
                if rqty is not None and wqty is not None: quantities[side]['delta'].append(float(rqty-wqty))
                statuses=[side_values['rest_vs_ws'],side_values['trade_vs_ws'],side_values['rest_vs_trade']]
                if all(s=='EQUAL' for s in statuses): consensus[side]['all_three_equal']+=1
                elif any(s in ('MISSING','BOTH_EMPTY','ONE_EMPTY') for s in statuses): consensus[side]['missing_or_empty']+=1
                else: consensus[side]['all_three_different_or_mixed']+=1
                values[side]=side_values|{'rest_vs_ws_quantity':qstatus}
            rows.append({'record_id':x.get('record_id'),'trading_date':day,'symbol':symbol,'rest_anchor_age_seconds':rest_age,'trade_anchor_age_seconds':trade_age,'rest_anchor_record_id':rest.get('record_id') if rest else None,'trade_anchor_record_id':trade.get('record_id') if trade else None,'rest_anchor_timestamp':rest.get('source_timestamp_candidate') if rest else None,'trade_anchor_timestamp':trade.get('source_timestamp_candidate') if trade else None,'ws_time_candidate':x.get('ws_time_candidate'),'comparisons':values,'source_hashes':{'rest':rest.get('payload_sha256') if rest else None,'trade':trade.get('payload_sha256') if trade else None,'ws':x.get('ws_payload_sha256')}})
        for pair in metrics:
            for side,m in metrics[pair].items(): m['price_delta_stats']=self._stats(m.pop('price_delta'))
        for side,m in quantities.items(): m['delta_stats']=self._stats(m.pop('delta'))
        report={'report_version':'Q25-A8-VALIDATION-ONLY-REST-WS-TRADE-TRIANGULATION-v1','scope':{'trading_date':'20261001','triples':len(triples),'source_hashes':dict(sorted(source_hashes.items()))},'counts':dict(sorted(counts.items())),'rest_anchor_age_seconds':self._stats(rest_ages),'trade_anchor_age_seconds':self._stats(trade_ages),'rest_source_to_collected_lag_seconds':self._stats(rest_lags),'trade_source_to_received_lag_seconds':self._stats(trade_lags),'ws_candidate_to_received_lag_seconds':self._stats(ws_lags),'pairwise_price_comparison':metrics,'rest_vs_ws_quantity_comparison':quantities,'three_source_consensus':consensus,'rows':rows,'issues':sorted(set(issues)),'time_fields_are_candidates_not_official_event_time':True,'h0iocnt0_is_broker_execution':False,'orderbook_semantics_authoritatively_certified':False,'freshness_threshold_applied':False,'authority_claimed':False,'gate_release_permitted':False,'mutation_applied':False}
        report['report_sha256']=self._hash(report); return report
