from __future__ import annotations
from collections import Counter
from hashlib import sha256
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from application.composition.validation_only_h0iocnt0_adapter_equivalence_auditor import audit_adapter_frame
SOURCE=Path(r'C:\Users\white\Desktop\MovingProject\KOSPI200_Project\data\kis_market_data_restart')
DAYS=('20261001','20261006','20261007','20261008','20261012','20261013')

def file_hash(p):
 h=sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def main():
 adapter=KISIndexOptionMarketWebSocketAdapter(); days=[]; hashes={}; totals=Counter()
 fields=('shrn_iscd','observed_hour','last_price','volume','ask_price','bid_price','implied_volatility')
 for day in DAYS:
  folder=SOURCE/day; raw=folder/'kis_vts_websocket_raw.jsonl'
  if not raw.is_file(): raise SystemExit(f'EXPECTED_RAW_MISSING:{raw}')
  raw_hash=file_hash(raw); hashes[f'{day}/kis_vts_websocket_raw.jsonl']=raw_hash
  daily=folder/'manifest.json'
  if daily.exists(): hashes[f'{day}/manifest.json']=file_hash(daily)
  side=raw.with_name(raw.name+'.manifest.json')
  if side.exists(): hashes[f'{day}/kis_vts_websocket_raw.jsonl.manifest.json']=file_hash(side)
  counts=Counter(); samples=[]; symbols=set()
  for line_no,line in enumerate(raw.open(encoding='utf-8'),1):
   if not line.strip(): continue
   row=json.loads(line)
   if row.get('tr_id')!='H0IOCNT0': continue
   payload=str(row.get('payload') or '')
   digest=sha256(payload.encode('utf-8')).hexdigest()
   if row.get('payload_sha256') and row['payload_sha256']!=digest: counts['payload_hash_mismatches']+=1
   try: adapted=adapter.adapt_many(payload,source='KIS:H0IOCNT0')
   except Exception as exc:
    counts['adapter_errors']+=1
    if len(samples)<10: samples.append({'line_number':line_no,'error':type(exc).__name__,'message':str(exc)[:160]})
    continue
   result=audit_adapter_frame(payload,adapted,source='KIS:H0IOCNT0')
   for k,v in result.items():
    if k!='mismatch_samples': counts[k]+=v if isinstance(v,int) else 0
   for x in adapted: symbols.add(x.shrn_iscd)
   for sample in result['mismatch_samples']:
    if len(samples)<10: samples.append({'line_number':line_no,**sample})
  day_result={'trading_date':day,'raw_sha256':raw_hash,'frames':counts['frames'],'raw_records':counts['raw_records'],'adapter_records':counts['adapter_records'],'adapter_errors':counts['adapter_errors'],'payload_hash_mismatches':counts['payload_hash_mismatches'],'source_mismatches':counts['source_mismatches'],'unique_symbols':len(symbols),'symbols':sorted(symbols),'field_comparisons':{f:counts[f'{f}_comparisons'] for f in fields},'field_mismatches':{f:counts[f'{f}_mismatches'] for f in fields},'mismatch_samples':samples}
  days.append(day_result); totals.update(counts)
 hashes['adapter_source_sha256']=file_hash(ROOT/'contracts'/'kis_index_option_market_ws_adapter.py')
 hashes['fresh58_report_sha256']=json.loads((ROOT/'reports'/'synth'/'Q25_A8_R10_FRESH58_H0IOCNT0_RECORD_IDENTITY_20261118.json').read_text(encoding='utf-8'))['report_sha256']
 report={'report_version':'Q25-A8-VALIDATION-ONLY-H0IOCNT0-ADAPTER-EQUIVALENCE-v1','scope':{'trading_dates':list(DAYS),'raw_source_root':str(SOURCE),'raw_read_only':True,'new_collection_or_api_calls':False,'canonical_write_or_rebuild':False,'comparison_fields':list(fields),'decision_refs':['No.1534','No.1535','No.1538','No.1554','No.1566']},'totals':{'frames':totals['frames'],'raw_records':totals['raw_records'],'adapter_records':totals['adapter_records'],'adapter_errors':totals['adapter_errors'],'payload_hash_mismatches':totals['payload_hash_mismatches'],'source_mismatches':totals['source_mismatches'],'field_comparisons':{f:totals[f'{f}_comparisons'] for f in fields},'field_mismatches':{f:totals[f'{f}_mismatches'] for f in fields}},'days':days,'source_hashes':dict(sorted(hashes.items())),'interpretation':['The existing KIS adapter was replayed against all original H0IOCNT0 frames; output record order/count and seven mapped fields were compared to their exact 58-field raw positions.','This verifies adapter parsing and field-position consistency only; it does not certify official KIS event-time semantics, account Execution/fill, multiplier, tradability, fees, margin, or Live readiness.','Original Raw/Canonical/Manifest were read-only. No synthetic value was needed because the required source fields existed in Raw.'],'market_trade_is_account_execution':False,'official_event_time_certified':False,'authority_claimed':False,'gate_release_permitted':False,'mutation_applied':False}
 body=json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode(); report['report_sha256']=sha256(body).hexdigest()
 out=ROOT/'reports'/'synth'; jp=out/'Q25_A8_R10_FRESH59_H0IOCNT0_ADAPTER_EQUIVALENCE_20261118.json'; jp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 md=['# FRESH-59 — H0IOCNT0 raw 58-field ↔ existing KIS adapter equivalence','',f'- Report SHA-256: `{report["report_sha256"]}`','', '## Aggregate','', '| Metric | Count |','|---|---:|']
 md += [f'| {k} | {v:,} |' for k,v in report['totals'].items() if isinstance(v,int)]
 md += ['', '## Field-by-field','', '| Field | Comparisons | Mismatches |', '|---|---:|---:|']
 for f in fields: md.append(f'| {f} | {report["totals"]["field_comparisons"][f]:,} | {report["totals"]["field_mismatches"][f]:,} |')
 md += ['', '## Per-day','', '| Date | Frames | Raw records | Adapter records | Errors | Symbols |', '|---|---:|---:|---:|---:|---:|']
 for x in days: md.append(f'| {x["trading_date"]} | {x["frames"]:,} | {x["raw_records"]:,} | {x["adapter_records"]:,} | {x["adapter_errors"]:,} | {x["unique_symbols"]} |')
 md += ['', '## Limits','', '- Adapter field mappings were checked against exact raw 58-field positions; no Raw/Canonical mutation or new collection.', '- H0IOCNT0 is public market trade data, not user-account broker Execution/fill. Official event-time, KIS contract/account terms, and Live readiness remain unverified.','']
 mp=out/'Q25_A8_R10_FRESH59_H0IOCNT0_ADAPTER_EQUIVALENCE_20261118.md'; mp.write_text('\n'.join(md),encoding='utf-8')
 print(json.dumps({'report_sha256':report['report_sha256'],'totals':report['totals'],'days':[{k:x[k] for k in ('trading_date','frames','raw_records','adapter_records','adapter_errors','payload_hash_mismatches','source_mismatches','unique_symbols')} for x in days]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
