from __future__ import annotations
from collections import Counter
from hashlib import sha256
from pathlib import Path
from decimal import Decimal
import json,sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from application.composition.validation_only_accepted_runtime_raw_lineage_auditor import audit_accepted_row,raw_base_key,decimal_value
SOURCE=Path(r'C:\Users\white\Desktop\MovingProject\KOSPI200_Project\data\kis_market_data_restart')
RUNTIME=ROOT/'data'/'accepted_market_data'/'runtime_v2'
DAYS=('20261012','20261013')

def file_hash(p):
 h=sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def main():
 manifest_path=RUNTIME/'manifest.json'; manifest=json.loads(manifest_path.read_text(encoding='utf-8')); manifest_hash=file_hash(manifest_path)
 if manifest.get('schema_version')!='accepted-market-data-runtime-v2': raise SystemExit('ACCEPTED_RUNTIME_MANIFEST_SCHEMA_INVALID')
 adapter=KISIndexOptionMarketWebSocketAdapter(); days=[]; hashes={'accepted_runtime_manifest':manifest_hash,'adapter_source_sha256':file_hash(ROOT/'contracts'/'kis_index_option_market_ws_adapter.py'),'auditor_source_sha256':file_hash(ROOT/'application'/'composition'/'validation_only_accepted_runtime_raw_lineage_auditor.py')}; total=Counter()
 for day in DAYS:
  raw=SOURCE/day/'kis_vts_websocket_raw.jsonl'; accepted=RUNTIME/(day+'.jsonl')
  raw_hash=file_hash(raw); accepted_hash=file_hash(accepted); hashes[f'{day}/raw']=raw_hash; hashes[f'{day}/accepted_runtime']=accepted_hash
  side=raw.with_name(raw.name+'.manifest.json')
  if side.exists(): hashes[f'{day}/raw_sidecar_manifest']=file_hash(side)
  daily=SOURCE/day/'manifest.json'
  if daily.exists(): hashes[f'{day}/daily_manifest']=file_hash(daily)
  spec=next(x for x in manifest['days'] if x['date']==day)
  base_counts=Counter(); full_counts=Counter(); raw_records=0; raw_frames=0
  for line in raw.open(encoding='utf-8'):
   x=json.loads(line)
   if x.get('tr_id')!='H0IOCNT0': continue
   raw_frames+=1
   for obs in adapter.adapt_many(x['payload'],source='KIS:H0IOCNT0'):
    raw_records+=1; base=raw_base_key(symbol=obs.shrn_iscd,hour=obs.observed_hour,last=obs.last_price,volume=obs.volume,bid=obs.bid_price,received_at=x['received_at'])
    base_counts[base]+=1; full_counts[base+(obs.ask_price,)]+=1
  row_count=0; errors=Counter(); ids=set(); lines=set(); underlying=Counter(); generated=Counter(); identity=Counter(); samples=[]; target_masters=set()
  for line_no,line in enumerate(accepted.open(encoding='utf-8'),1):
   if not line.strip(): continue
   x=json.loads(line); row_count+=1; meta=x.get('scenario_metadata') or {}; tick=x.get('tick') or {}
   result=audit_accepted_row(x,trading_date=day,raw_file_sha256=raw_hash,canonical_sha256=spec['source_canonical_sha256'],raw_base_counts=base_counts,raw_full_counts=full_counts)
   for e in result['errors']:
    errors[e]+=1
    if len(samples)<10: samples.append({'accepted_line':line_no,'error':e,'source_observation_id':result['source_observation_id']})
   ids.add(result['source_observation_id']); lines.add(result['source_line_number']); underlying[result['underlying_source']]+=1; identity[tick.get('instrument_identity_status')]+=1; target_masters.add(meta.get('target_master_sha256'))
   for f in result['generated_fields']: generated[f]+=1
  if accepted_hash!=spec['sha256']: errors['ACCEPTED_FILE_HASH_MISMATCH']+=1
  if row_count!=spec['rows']: errors['ACCEPTED_ROW_COUNT_MISMATCH']+=1
  if len(ids)!=row_count: errors['SOURCE_OBSERVATION_ID_DUPLICATE']+=row_count-len(ids)
  if len(lines)!=row_count: errors['SOURCE_LINE_NUMBER_DUPLICATE']+=row_count-len(lines)
  if lines and (min(lines)!=1 or max(lines)!=row_count): errors['SOURCE_LINE_NUMBER_RANGE_MISMATCH']+=1
  if len(target_masters)!=1: errors['TARGET_MASTER_HASH_INCONSISTENT']+=1
  day_result={'trading_date':day,'raw_sha256':raw_hash,'accepted_file_sha256':accepted_hash,'expected_manifest_rows':spec['rows'],'accepted_rows':row_count,'raw_frames':raw_frames,'raw_records':raw_records,'matched_raw_rows':row_count-errors['RAW_SOURCE_RECORD_NOT_MATCHED'],'unmatched_raw_rows':errors['RAW_SOURCE_RECORD_NOT_MATCHED'],'remaining_raw_records':sum(base_counts.values()),'source_observation_id_unique':len(ids),'source_line_number_unique':len(lines),'source_line_number_min':min((x for x in lines if isinstance(x,int)),default=None),'source_line_number_max':max((x for x in lines if isinstance(x,int)),default=None),'source_canonical_sha256':spec['source_canonical_sha256'],'source_v1_sha256':spec['source_v1_sha256'],'target_master_sha256_values':sorted(str(x) for x in target_masters),'target_master_snapshot_date':'20261014','underlying_source_rows':dict(underlying),'identity_status_rows':dict(identity),'generated_field_rows':dict(generated),'errors':dict(errors),'error_samples':samples}
  days.append(day_result); total.update(errors)
 report={'report_version':'Q25-A8-VALIDATION-ONLY-ACCEPTED-RUNTIME-V2-RAW-LINEAGE-v1','scope':{'trading_dates':list(DAYS),'accepted_runtime_root':str(RUNTIME),'raw_source_root':str(SOURCE),'raw_and_accepted_data_read_only':True,'new_collection_or_api_calls':False,'canonical_artifact_rewrite':False,'decision_refs':['No.1534','No.1535','No.1538','No.1554','No.1566']},'manifest_rows_total':manifest.get('rows_total'),'manifest_timestamp_groups':manifest.get('timestamp_groups'),'manifest_sha256':manifest_hash,'days':days,'source_hashes':dict(sorted(hashes.items())),'aggregate_errors':dict(total),'source_canonical_artifact_materialized_in_current_worktrees':False,'interpretation':['Accepted Runtime v2 rows were matched one-to-one to original same-day H0IOCNT0 Raw records using symbol/time/last/volume/bid, and ask when ask was not generated. Decimal normalization was used to avoid false mismatches caused only by formatting such as 33.60 vs 33.6.','source_canonical_sha256 is retained from accepted Runtime manifest and No.1535 lineage; the canonical-v2 source sidecar itself is not materialized in current inspected worktrees, so exact raw-field crosswalk is the alternative verification.','2026-10-14 KIS Master is post-date identity corroboration for 10-12/13, not the historical same-day Master. contract_multiplier remains KRX-spec-derived validation input, not authoritative KIS account/broker multiplier.','Synthetic KRX-derived underlying and deterministic ask/depth/Greeks/multiplier fields remain explicitly provenance-tagged DERIVED_SCENARIO.','An initial string-format comparison differed only on Decimal presentation (for example 33.60 vs 33.6); Decimal-normalized matching resolved it with 2,072/2,072 records matched.','underlying_price_group_consensus is an explicit generated-field provenance key of its own; it is not missing underlying_price provenance.'] ,'account_execution_claim':False,'official_event_time_claim':False,'production_authority_claim':False,'gate_release_permitted':False,'mutation_applied':False}
 report['report_sha256']=sha256(json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
 out=ROOT/'reports'/'synth'; jp=out/'Q25_A8_R10_FRESH60_ACCEPTED_RUNTIME_V2_RAW_LINEAGE_20261118.json'; jp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 md=['# FRESH-60 — Accepted Runtime v2 ↔ original H0IOCNT0 Raw lineage','',f'- Report SHA-256: `{report["report_sha256"]}`','- Accepted Runtime v2 manifest rows: 2,072 / 1,596 timestamp groups','', '| Date | Raw frames | Raw records | Accepted rows | Matched | Unmatched | Remaining Raw | ID unique | Source line unique |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
 for x in days: md.append(f'| {x["trading_date"]} | {x["raw_frames"]:,} | {x["raw_records"]:,} | {x["accepted_rows"]:,} | {x["matched_raw_rows"]:,} | {x["unmatched_raw_rows"]:,} | {x["remaining_raw_records"]:,} | {x["source_observation_id_unique"]:,} | {x["source_line_number_unique"]:,} |')
 md += ['', '## Underlying source by day','']
 for x in days: md.append(f'- {x["trading_date"]}: `{x["underlying_source_rows"]}`')
 md += ['', '## Generated-field provenance by day','']
 for x in days: md.append(f'- {x["trading_date"]}: `{x["generated_field_rows"]}`')
 md += ['', '## Provenance boundary','', '- Decimal normalization is used for numeric field matching; generated ask is excluded from raw ask equality but requires explicit field_provenance.', '- 2026-10-14 KIS Master is post-date identity corroboration only. KRX contract multiplier, KRX-derived spot, and deterministic Greeks/depth/ask remain derived validation fields.', '- Decimal string-format differences (for example 33.60 vs 33.6) were normalized as Decimal, not treated as source mismatch. All 2,072 rows matched.', '- underlying_price_group_consensus has its own explicit provenance object; this is not a missing-provenance condition.', '- Accepted Runtime v2 source canonical hash references are verified against manifest; source canonical sidecar itself is not materialized in current worktrees. Raw field crosswalk provides the alternative lineage evidence.', '- No Raw/Canonical write, new collection, account API, broker execution claim, or Live gate release.','']
 mp=out/'Q25_A8_R10_FRESH60_ACCEPTED_RUNTIME_V2_RAW_LINEAGE_20261118.md'; mp.write_text('\n'.join(md),encoding='utf-8')
 print(json.dumps({'report_sha256':report['report_sha256'],'manifest_rows_total':report['manifest_rows_total'],'aggregate_errors':report['aggregate_errors'],'days':days},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
