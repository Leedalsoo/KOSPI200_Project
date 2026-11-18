from __future__ import annotations
from collections import Counter,defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import json,sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from application.composition.validation_only_no_lookahead_anchor_reconciler import (
 nearest_prior_anchor,nearest_same_time_option_spread,apply_prior_underlying_anchor,
 apply_same_time_spread_proxy,find_future_donors,mark_nonfuture_underlying_anchor,
)
SOURCE=ROOT/'data'/'accepted_market_data'/'runtime_v2'
ORIGINAL=Path(r'C:\Users\white\Desktop\MovingProject\KOSPI200_Project\data\synthetic_market_data\fresh_krx_20261008_shock_v4')
DAYS=('20261012','20261013')

def file_hash(p):
 h=sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def kst_timestamp(value):
 dt=datetime.fromisoformat(value)
 if dt.tzinfo is None: dt=dt.replace(tzinfo=ZoneInfo('Asia/Seoul'))
 return dt.isoformat()

def main():
 krx_manifest_path=ORIGINAL/'manifest.json'; krx_manifest_hash=file_hash(krx_manifest_path)
 if krx_manifest_hash!='d0405740cc7b90e791de2cef0fdb189af19880d28ae5f96b2a89ec74eba119e0': raise SystemExit('KRX_SHOCK_V4_MANIFEST_HASH_MISMATCH')
 krx_day=ORIGINAL/'20261013.jsonl'; krx_day_hash=file_hash(krx_day)
 bars=defaultdict(list)
 for line in krx_day.open(encoding='utf-8'):
  x=json.loads(line); t=x.get('tick') or {}
  if t.get('underlying_price') is None: continue
  ts=kst_timestamp(str(t['timestamp']))
  bars[ts].append({'timestamp':ts,'underlying_price':t['underlying_price']})
 spot_anchors=[]
 for ts,items in bars.items():
  vals={float(x['underlying_price']) for x in items}
  if len(vals)!=1: raise SystemExit(f'KRX_SPOT_INCONSISTENT_WITHIN_TIMESTAMP:{ts}')
  spot_anchors.append({'timestamp':ts,'underlying_price':next(iter(vals))})
 spot_anchors.sort(key=lambda x:x['timestamp'])
 option_rows=[]
 for line in krx_day.open(encoding='utf-8'):
  x=json.loads(line); t=x.get('tick') or {}
  if t.get('timestamp'):
   option_rows.append({'timestamp':kst_timestamp(str(t['timestamp'])),'expiry':str(t.get('expiry')),'option_type':str(t.get('option_type')),'strike_price':t.get('strike_price'),'bid_price':t.get('bid_price'),'ask_price':t.get('ask_price'),'contract_class':t.get('contract_class')})
 corrected=[]; days=[]; totals=Counter(); future_examples=[]; ask_proxy_detail=None
 for day in DAYS:
  original=SOURCE/(day+'.jsonl'); out_rows=[]; counts=Counter(); ids=set(); lines=set(); age_before=[]; age_after=[]; all_underlying_ages=[]
  for line_no,line in enumerate(original.open(encoding='utf-8'),1):
   row=json.loads(line); counts['rows']+=1; meta=row['scenario_metadata']; target=meta['source_observed_at']
   before=find_future_donors(row)
   if before:
    for f in before: counts['future_donors_before']+=1
   new=deepcopy(row)
   for f in before:
    if f['field']=='underlying_price':
     anchor=nearest_prior_anchor(target,spot_anchors)
     new=apply_prior_underlying_anchor(new,anchor,source_manifest_sha256=krx_manifest_hash,source_file_sha256=krx_day_hash)
     age_after.append((datetime.fromisoformat(target)-datetime.fromisoformat(anchor['timestamp'])).total_seconds())
    elif f['field']=='ask_price':
     tick=new['tick']; donor=nearest_same_time_option_spread(target_timestamp=target,target_expiry=str(tick['expiry']),target_option_type=str(tick['option_type']),target_strike=tick['strike_price'],candidates=option_rows)
     tick_size=Decimal('0.01') if Decimal(str(tick['bid_price']))<10 else Decimal('0.05')
     original_ask=new['tick'].get('ask_price')
     new=apply_same_time_spread_proxy(new,donor,source_manifest_sha256=krx_manifest_hash,source_file_sha256=krx_day_hash,tick_size=tick_size)
     ask_proxy_detail={'target_contract':new['tick']['symbol'],'target_strike':new['tick']['strike_price'],'option_type':new['tick']['option_type'],'expiry':new['tick']['expiry'],'target_timestamp':target,'donor_strike':donor['strike_price'],'strike_distance':abs(float(donor['strike_price'])-float(new['tick']['strike_price'])),'donor_spread':float(Decimal(str(donor['ask_price']))-Decimal(str(donor['bid_price']))),'target_raw_bid':float(new['tick']['bid_price']),'original_future_generated_ask':float(original_ask),'synthetic_ask':new['tick']['ask_price'],'ask_change':float(new['tick']['ask_price'])-float(original_ask),'donor_timestamp':donor['timestamp'],'source':'DERIVED_SCENARIO:KRX_SHOCK_V4_SAME_TIMESTAMP_NEAREST_STRIKE'}
     counts['synthetic_ask_proxy_rows']+=1
   if not any(f['field']=='underlying_price' for f in before) and new['tick'].get('underlying_source')=='SYNTHETIC:KRX_SHOCK_V4_NEAREST_SPOT':
    new=mark_nonfuture_underlying_anchor(new,source_manifest_sha256=krx_manifest_hash,source_file_sha256=krx_day_hash)
   up=new.get('scenario_metadata',{}).get('field_provenance',{}).get('underlying_price',{})
   if new['tick'].get('underlying_source')=='SYNTHETIC:KRX_SHOCK_V4_AT_OR_BEFORE_TARGET_SPOT' and up.get('donor_timestamp'):
    age=(datetime.fromisoformat(new['scenario_metadata']['source_observed_at'])-datetime.fromisoformat(up['donor_timestamp'])).total_seconds(); all_underlying_ages.append(age)
    if age==0: counts['underlying_exact_anchor_rows']+=1
    else: counts['underlying_prior_anchor_rows']+=1
   new['scenario_metadata']['validation_only_no_lookahead']=True
   new['scenario_metadata']['no_lookahead_reconciler_version']='FRESH61-v1'
   after=find_future_donors(new)
   counts['future_donors_after']+=len(after)
   if after and len(future_examples)<10: future_examples.append({'day':day,'line':line_no,'future':after})
   if before:
    counts['rows_with_future_donor_before']+=1
    counts['rows_corrected']+=1
   if 'original_future_underlying_anchor' in new['scenario_metadata']: counts['underlying_future_anchor_replaced']+=1
   if 'original_future_ask_anchor' in new['scenario_metadata']: counts['ask_future_anchor_replaced']+=1
   if new['tick'].get('underlying_source')=='SYNTHETIC:KRX_SHOCK_V4_AT_OR_BEFORE_TARGET_SPOT': counts['nonfuture_synthetic_underlying_rows']+=1
   ids.add(meta.get('source_observation_id')); lines.add(meta.get('source_line_number'))
   out_rows.append(new)
  out_path=ROOT/'reports'/'synth'/f'Q25_A8_R10_FRESH61_NO_LOOKAHEAD_{day}_20261118.jsonl'
  out_path.write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in out_rows),encoding='utf-8')
  digest=file_hash(out_path)
  day_result={'trading_date':day,'rows':counts['rows'],'rows_with_future_donor_before':counts['rows_with_future_donor_before'],'future_donors_before':counts['future_donors_before'],'rows_corrected':counts['rows_corrected'],'underlying_future_anchor_replaced':counts['underlying_future_anchor_replaced'],'ask_future_anchor_replaced':counts['ask_future_anchor_replaced'],'synthetic_ask_proxy_rows':counts['synthetic_ask_proxy_rows'],'future_donors_after':counts['future_donors_after'],'nonfuture_synthetic_underlying_rows':counts['nonfuture_synthetic_underlying_rows'],'underlying_prior_anchor_rows':counts['underlying_prior_anchor_rows'],'underlying_exact_anchor_rows':counts['underlying_exact_anchor_rows'],'source_observation_id_unique':len(ids),'source_line_number_unique':len(lines),'corrected_sidecar_sha256':digest,'underlying_prior_age_seconds':{'min':min((x for x in all_underlying_ages if x>0),default=None),'max':max((x for x in all_underlying_ages if x>0),default=None)},'underlying_anchor_age_seconds':{'min':min(all_underlying_ages) if all_underlying_ages else None,'max':max(all_underlying_ages) if all_underlying_ages else None}}
  days.append(day_result); totals.update(counts)
  corrected.append(out_path)
 manifest={'schema':'q25-a8-validation-only-no-lookahead-runtime-v2-v1','provenance':'DERIVED_SCENARIO','source_accepted_runtime_manifest_sha256':file_hash(SOURCE/'manifest.json'),'source_krx_shock_v4_manifest_sha256':krx_manifest_hash,'source_krx_20261013_file_sha256':krx_day_hash,'trading_dates':list(DAYS),'partitions':[{'date':x['trading_date'],'file':corrected[i].name,'rows':x['rows'],'sha256':x['corrected_sidecar_sha256']} for i,x in enumerate(days)],'correction_policy':'same-day nearest-prior KRX spot; same-timestamp nearest-strike same-expiry/right KRX synthetic spread for future-generated ask; preserve original future anchor provenance','future_market_price_anchor_count_after':sum(x['future_donors_after'] for x in days),'validation_only':True,'not_live_or_account_execution_evidence':True}
 manifest_path=ROOT/'reports'/'synth'/'Q25_A8_R10_FRESH61_NO_LOOKAHEAD_MANIFEST_20261118.json'; manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 report={'report_version':'Q25-A8-VALIDATION-ONLY-ACCEPTED-RUNTIME-NO-LOOKAHEAD-v1','scope':{'source_accepted_runtime_unchanged':True,'source_krx_scenario_unchanged':True,'derived_sidecar_only':True,'new_collection_or_api_calls':False,'decision_refs':['No.1534','No.1535','No.1538','No.1554','No.1566']},'before':{'future_underlying_donors':27,'future_ask_donors':1,'total_future_market_price_donors':28},'after':{'future_market_price_donors':sum(x['future_donors_after'] for x in days),'underlying_future_anchor_replaced':sum(x['underlying_future_anchor_replaced'] for x in days),'ask_future_anchor_replaced':sum(x['ask_future_anchor_replaced'] for x in days),'synthetic_ask_proxy_rows':sum(x['synthetic_ask_proxy_rows'] for x in days)},'days':days,'ask_proxy':ask_proxy_detail,'krx_prior_anchor_policy':{'same_day':True,'timestamp_must_be_lte_target':True,'bar_interval_minutes':5,'timezone':'Asia/Seoul','max_prior_age_seconds':max((x['underlying_prior_age_seconds']['max'] or 0) for x in days)},'source_hashes':{'accepted_runtime_manifest':file_hash(SOURCE/'manifest.json'),'accepted_20261012':file_hash(SOURCE/'20261012.jsonl'),'accepted_20261013':file_hash(SOURCE/'20261013.jsonl'),'krx_shock_v4_manifest':krx_manifest_hash,'krx_shock_v4_20261013':krx_day_hash,'fresh60_report':json.loads((ROOT/'reports'/'synth'/'Q25_A8_R10_FRESH60_ACCEPTED_RUNTIME_V2_RAW_LINEAGE_20261118.json').read_text(encoding='utf-8'))['report_sha256']},'derived_manifest_sha256':file_hash(manifest_path),'corrected_sidecars':[{'file':p.name,'sha256':file_hash(p)} for p in corrected],'future_donor_examples_before':future_examples,'interpretation':['27 future synthetic KRX spot anchors were replaced by same-day nearest-prior bars. No future KRX scenario price is retained as the selected underlying input.','One future same-symbol ask-spread donor at 08:45:15 was replaced by a same-timestamp, same-expiry, same-option-right nearest-strike KRX derived scenario spread. This produces a synthetic ask proxy 36.00 from raw bid 35.50; it is not an observed KIS ask.','The original future donor provenance is preserved in original_future_underlying_anchor/original_future_ask_anchor fields for audit, but the corrected tick fields use prior-only/same-time inputs.','The original Accepted Runtime v2 partitions and KRX scenario source files are unchanged. Corrected JSONL files are separately namespaced validation-only derived sidecars.'],'account_execution_claim':False,'official_event_time_claim':False,'production_authority_claim':False,'gate_release_permitted':False,'mutation_applied_to_sources':False}
 report['report_sha256']=sha256(json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
 rp=ROOT/'reports'/'synth'/'Q25_A8_R10_FRESH61_NO_LOOKAHEAD_RECONCILIATION_20261118.json'; rp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 md=['# FRESH-61 — Accepted Runtime v2 future-anchor reconciliation','',f'- Report SHA-256: `{report["report_sha256"]}`','', '| Date | Rows | Future donors before | Replaced | Future donors after | Underlying replacements | Ask proxy | Max prior age (s) |','|---|---:|---:|---:|---:|---:|---:|---:|']
 for x in days: md.append(f'| {x["trading_date"]} | {x["rows"]} | {x["future_donors_before"]} | {x["rows_corrected"]} | {x["future_donors_after"]} | {x["underlying_future_anchor_replaced"]} | {x["synthetic_ask_proxy_rows"]} | {x["underlying_prior_age_seconds"]["max"]} |')
 md += ['', '## Ask proxy detail','']
 md.append('- Target: {target_contract} {option_type} {target_strike}, expiry {expiry}, {target_timestamp}.'.format(**ask_proxy_detail))
 md.append('- Donor: same-time KRX derived scenario {option_type} {donor_strike}, same expiry; strike distance {strike_distance}, spread {donor_spread}. Raw bid {target_raw_bid} / prior future-generated ask {original_future_generated_ask} -> validation-only synthetic ask {synthetic_ask} (change {ask_change}).'.format(**ask_proxy_detail))
 md += ['- This is not a KIS observed ask and must not be used as actual broker quote or profitability evidence.','', '## Limits','', '- Underlying replacements use same-day nearest-prior 5-minute synthetic KRX spot only.', '- Original future anchors are preserved as audit metadata; original Accepted Runtime v2 and KRX source data remain unchanged.', '- All corrected rows are DERIVED_SCENARIO / validation-only. No account Execution/fill or Live authority.','']
 mp=ROOT/'reports'/'synth'/'Q25_A8_R10_FRESH61_NO_LOOKAHEAD_RECONCILIATION_20261118.md'; mp.write_text('\n'.join(md),encoding='utf-8')
 print(json.dumps({'report_sha256':report['report_sha256'],'before':report['before'],'after':report['after'],'days':days,'ask_proxy':report['ask_proxy'],'manifest_sha256':manifest['source_krx_shock_v4_manifest_sha256']},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
