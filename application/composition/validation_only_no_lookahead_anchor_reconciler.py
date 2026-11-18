from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from typing import Any, Mapping, Sequence


def parse_kst(value: str) -> datetime:
    dt=datetime.fromisoformat(value)
    if dt.tzinfo is None: raise ValueError('TIMESTAMP_TIMEZONE_REQUIRED')
    return dt


def nearest_prior_anchor(target_timestamp: str, anchors: Sequence[Mapping[str,Any]]) -> Mapping[str,Any]:
    target=parse_kst(target_timestamp)
    eligible=[]
    for anchor in anchors:
        at=parse_kst(str(anchor['timestamp']))
        if at<=target: eligible.append((at,anchor))
    if not eligible: raise ValueError('NO_SAME_DAY_PRIOR_ANCHOR')
    return max(eligible,key=lambda x:x[0])[1]


def nearest_same_time_option_spread(*, target_timestamp: str, target_expiry: str,
                                    target_option_type: str, target_strike: Any,
                                    candidates: Sequence[Mapping[str,Any]]) -> Mapping[str,Any]:
    target=parse_kst(target_timestamp); strike=Decimal(str(target_strike))
    eligible=[]
    for row in candidates:
        at=parse_kst(str(row['timestamp']))
        if at!=target: continue
        if str(row.get('expiry'))!=target_expiry or str(row.get('option_type'))!=target_option_type: continue
        bid=Decimal(str(row['bid_price'])); ask=Decimal(str(row['ask_price']))
        if bid<=0 or ask<=bid: continue
        eligible.append((abs(Decimal(str(row['strike_price']))-strike),Decimal(str(row['strike_price'])),row))
    if not eligible: raise ValueError('NO_SAME_TIME_SAME_EXPIRY_RIGHT_SPREAD_PROXY')
    return min(eligible,key=lambda x:(x[0],x[1]))[2]


def apply_prior_underlying_anchor(row: Mapping[str,Any], anchor: Mapping[str,Any], *,
                                   source_manifest_sha256: str, source_file_sha256: str) -> dict[str,Any]:
    out=deepcopy(row); tick=out['tick']; meta=out['scenario_metadata']; fp=meta.setdefault('field_provenance',{})
    target=str(meta['source_observed_at']); donor_time=str(anchor['timestamp'])
    age=(parse_kst(target)-parse_kst(donor_time)).total_seconds()
    if age<0: raise ValueError('FUTURE_UNDERLYING_ANCHOR_REJECTED')
    original=deepcopy(fp.get('underlying_price',{}))
    meta['original_future_underlying_anchor']=original
    meta['original_future_underlying_price']=tick.get('underlying_price')
    meta['original_future_underlying_source']=tick.get('underlying_source')
    tick['underlying_price']=float(anchor['underlying_price'])
    tick['underlying_observed_hour']=parse_kst(donor_time).strftime('%H%M%S')
    tick['underlying_source']='SYNTHETIC:KRX_SHOCK_V4_AT_OR_BEFORE_TARGET_SPOT'
    fp['underlying_price']={'method':'nearest_same_day_KRX_derived_scenario_spot_prior_only',
      'donor_timestamp':donor_time,'distance_seconds':age,'source_manifest_sha256':source_manifest_sha256,
      'source_file_sha256':source_file_sha256,'donor_underlying_price':float(anchor['underlying_price'])}
    meta['validation_only_no_lookahead']=True
    return out


def apply_same_time_spread_proxy(row: Mapping[str,Any], donor: Mapping[str,Any], *,
                                 source_manifest_sha256: str, source_file_sha256: str,
                                 tick_size: Decimal = Decimal('0.05')) -> dict[str,Any]:
    out=deepcopy(row); tick=out['tick']; meta=out['scenario_metadata']; fp=meta.setdefault('field_provenance',{})
    target=str(meta['source_observed_at']); donor_time=str(donor['timestamp'])
    if parse_kst(donor_time)!=parse_kst(target): raise ValueError('ASK_SPREAD_DONOR_NOT_SAME_TIME')
    original=deepcopy(fp.get('ask_price',{})); meta['original_future_ask_anchor']=original
    meta['original_future_ask_price']=tick.get('ask_price')
    spread=Decimal(str(donor['ask_price']))-Decimal(str(donor['bid_price']))
    raw_bid=Decimal(str(tick['bid_price'])); proposed=raw_bid+spread
    ask=(proposed/tick_size).to_integral_value(rounding=ROUND_CEILING)*tick_size
    tick['ask_price']=float(ask)
    fp['ask_price']={'method':'same_timestamp_nearest_strike_KRX_derived_scenario_spread_proxy',
      'donor':{'timestamp':donor_time,'expiry':donor['expiry'],'option_type':donor['option_type'],
        'strike_price':donor['strike_price'],'bid_price':donor['bid_price'],'ask_price':donor['ask_price'],
        'spread':float(spread)},'target_strike':tick['strike_price'],'strike_distance':abs(float(donor['strike_price'])-float(tick['strike_price'])),
      'applied_spread':float(spread),'raw_target_bid':float(raw_bid),'synthetic_target_ask':float(ask),
      'source_manifest_sha256':source_manifest_sha256,'source_file_sha256':source_file_sha256}
    meta['validation_only_no_lookahead']=True
    meta['ask_price_is_synthetic_proxy']=True
    return out


def find_future_donors(row: Mapping[str,Any]) -> list[dict[str,Any]]:
    meta=row.get('scenario_metadata') or {}; target=meta.get('source_observed_at'); fp=meta.get('field_provenance') or {}
    if not target: return []
    target_dt=parse_kst(str(target)); future=[]
    for field,info in fp.items():
        if not isinstance(info,Mapping): continue
        donor=info.get('donor') if isinstance(info.get('donor'),Mapping) else {}
        donor_time=donor.get('timestamp') or info.get('donor_timestamp')
        if not donor_time: continue
        donor_dt=parse_kst(str(donor_time))
        if donor_dt>target_dt: future.append({'field':field,'target_timestamp':target,'donor_timestamp':donor_time,'future_seconds':(donor_dt-target_dt).total_seconds()})
    return future


def mark_nonfuture_underlying_anchor(row: Mapping[str,Any], *, source_manifest_sha256: str,
                                      source_file_sha256: str) -> dict[str,Any]:
    out=deepcopy(row); tick=out['tick']; meta=out['scenario_metadata']; fp=meta.get('field_provenance') or {}
    info=fp.get('underlying_price') or {}; donor_time=info.get('donor_timestamp')
    if not donor_time: raise ValueError('UNDERLYING_DONOR_TIMESTAMP_MISSING')
    target=parse_kst(str(meta['source_observed_at'])); donor=parse_kst(str(donor_time))
    if donor>target: raise ValueError('FUTURE_UNDERLYING_ANCHOR_REQUIRES_REPLACEMENT')
    age=(target-donor).total_seconds()
    info=deepcopy(info); info['source_method_before_fresh61']=info.get('method')
    info['method']='same_day_KRX_derived_scenario_spot_at_or_before_target'
    info['distance_seconds']=age; info['source_manifest_sha256']=source_manifest_sha256
    info['source_file_sha256']=source_file_sha256; fp['underlying_price']=info
    meta['field_provenance']=fp
    tick['underlying_source']='SYNTHETIC:KRX_SHOCK_V4_AT_OR_BEFORE_TARGET_SPOT'
    meta['validation_only_no_lookahead']=True
    return out
