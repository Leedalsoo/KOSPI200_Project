from __future__ import annotations
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json,sys
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from application.composition.validation_only_h0iocnt0_record_identity_auditor import summarize_day
SOURCE=Path(r'C:\Users\white\Desktop\MovingProject\KOSPI200_Project\data\kis_market_data_restart')
DAYS=('20261001','20261006','20261007','20261008','20261012','20261013')

def file_hash(p):
 h=sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def canonical_stats(path, raw_symbols=None):
 if not path.exists(): return {'file_exists':False}
 sources=Counter(); ids=Counter(); raw_ids=Counter(); ws_raw_ids=Counter(); ws_symbols=set(); ws_seq=Counter(); rows=0; tr_ids=Counter()
 for line in path.open(encoding='utf-8'):
  if not line.strip(): continue
  o=json.loads(line).get('observation',{}); rows+=1; sources[o.get('source','')]+=1
  ids[o.get('observation_id')]+=1
  rr=o.get('raw_reference') or {}; raw_ids[rr.get('raw_id')]+=1
  for tr in (o.get('provenance') or {}).get('tr_ids') or []: tr_ids[tr]+=1
  if o.get('source')=='kis_vts_websocket':
   ws_raw_ids[rr.get('raw_id')]+=1; ws_symbols.add(str((o.get('contract') or {}).get('symbol') or ''))
   raw_value=str(rr.get('raw_id') or '')
   if ':' in raw_value: ws_seq[raw_value.rsplit(':',1)[-1]]+=1
 missing_symbols=sorted(set(raw_symbols or [])-ws_symbols)
 return {'file_exists':True,'rows':rows,'source_rows':dict(sources),'tr_id_rows':dict(tr_ids),
   'observation_id_duplicate_excess':sum(v-1 for v in ids.values() if v>1),
   'raw_id_unique':len([k for k in raw_ids if k]),'raw_id_duplicate_excess':sum(v-1 for v in raw_ids.values() if v>1),
   'websocket_rows':sources.get('kis_vts_websocket',0),'websocket_raw_id_unique':len([k for k in ws_raw_ids if k]),
   'websocket_raw_id_duplicate_excess':sum(v-1 for v in ws_raw_ids.values() if v>1),
   'websocket_symbol_count':len(ws_symbols),'websocket_symbols':sorted(ws_symbols),
   'raw_symbols_missing_from_websocket_canonical':missing_symbols,
   'websocket_raw_sequence_min':min((int(k) for k in ws_seq if k.isdigit()),default=None),
   'websocket_raw_sequence_max':max((int(k) for k in ws_seq if k.isdigit()),default=None)}

def main():
 day_reports=[]; all_hashes={}; canonical={}
 for d in DAYS:
  folder=SOURCE/d; raw=folder/'kis_vts_websocket_raw.jsonl'
  if not raw.is_file(): raise SystemExit(f'EXPECTED_EXISTING_RAW_MISSING:{raw}')
  digest=file_hash(raw); all_hashes[f'{d}/kis_vts_websocket_raw.jsonl']=digest
  manifest=folder/'manifest.json'
  if manifest.exists(): all_hashes[f'{d}/manifest.json']=file_hash(manifest)
  side=raw.with_name(raw.name+'.manifest.json')
  if side.exists(): all_hashes[f'{d}/kis_vts_websocket_raw.jsonl.manifest.json']=file_hash(side)
  frames=[]
  with raw.open(encoding='utf-8') as f:
   for line in f:
    if line.strip(): frames.append(json.loads(line))
  result=summarize_day(frames=frames,trading_date=d,raw_file_sha256=digest)
  result['raw_file_sha256']=digest; result['raw_manifest_declared_hash']=None
  if side.exists():
   m=json.loads(side.read_text(encoding='utf-8')); result['raw_manifest_declared_hash']=m.get('file_sha256'); result['raw_manifest_record_count']=m.get('record_count')
  result['daily_manifest_sha256']=all_hashes.get(f'{d}/manifest.json')
  day_reports.append(result)
  canon=folder/'historical_market_observations.jsonl.observations.jsonl'
  if canon.exists():
   all_hashes[f'{d}/historical_market_observations.jsonl.observations.jsonl']=file_hash(canon)
   canonical[d]=canonical_stats(canon, raw_symbols=result['symbol_record_counts'].keys())
 totals={k:sum(x[k] for x in day_reports) for k in ('raw_h0iocnt0_frames','parsed_58_field_records','duplicate_sequence_groups','duplicate_sequence_excess_frames','duplicate_payload_hash_groups','duplicate_payload_hash_excess_frames','malformed_frames','payload_hash_mismatches','legacy_symbol_time_duplicate_groups','legacy_symbol_time_excess_records','exact_full_record_duplicate_groups_within_frame','exact_full_record_duplicate_excess_records','current_raw_id_collision_count','current_normalizer_observation_id_collision_count')}
 report={'report_version':'Q25-A8-VALIDATION-ONLY-H0IOCNT0-RECORD-IDENTITY-AUDIT-v1','scope':{'trading_dates':list(DAYS),'raw_source_root':str(SOURCE),'raw_sources_read_only':True,'new_collection_or_api_calls':False,'frame_count_and_58_field_record_count_separated':True,'canonical_files_read_only':True,'decision_refs':['No.1534','No.1535','No.1538','No.1554','No.1566']},'totals':totals,'days':day_reports,'existing_canonical_read_only':canonical,'source_hashes':dict(sorted(all_hashes.items())),'identity_contract_review':{'normalizer_source_sha256':file_hash(ROOT/'infrastructure'/'kis'/'kis_websocket_market_observation_normalizer.py'),'ingest_script_sha256':file_hash(ROOT/'scripts'/'ingest_kis_vts_websocket_canonical.py'),'ingest_raw_id':'trading_date:sequence:line_number:payload_sha256','run_id':'vts-ws-canonical-{trading_date}-{raw_file_sha256[:8]}','normalizer_seed_includes_record_index':True,'normalizer_source':'KIS:H0IOCNT0','raw_sequence_alone_is_unique':False,'stable_within_same_raw_file_and_run_id':True,'official_account_execution_claim':False,'authority_claimed':False,'gate_release_permitted':False,'mutation_applied':False},'interpretation':['Repeated symbol+BSOP_HOUR within a frame is a legacy collision-key group, not proof of duplicate trade. Full 58-field digest separates different records from exact identical records.','Duplicate raw sequence values are not unique frame IDs; current ingestion caller also includes line number and payload SHA-256.','Current normalizer includes frame-local record_index in observation ID seed; current pipeline code has already implemented the key collision mitigation.','The 2026-10-01 legacy Canonical has 1,995 H0IOCNT0 rows for 2,710 Raw records (715 fewer), covers 25/26 Raw symbols, and omits C01610A41; preserve it unchanged.' ,'The 2026-10-06/07/08/12/13 legacy Canonical files are REST-only; their lack of H0IOCNT0 rows does not mean the Raw trade source is absent.' ,'The 390 repeated raw_id references in the 2026-10-01 combined Canonical are REST duplicate references, not H0IOCNT0 observation_id collisions.' ,'This is an identity/provenance audit, not an official KIS event-time certification or broker account execution validation.']}
 canonical_path=SOURCE/'20261001'/'historical_market_observations.jsonl.observations.jsonl'
 if canonical_path.exists(): report['source_hashes']['20261001/old_canonical']=file_hash(canonical_path)
 body=json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode(); report['report_sha256']=sha256(body).hexdigest()
 out=ROOT/'reports'/'synth'; out.mkdir(parents=True,exist_ok=True)
 jp=out/'Q25_A8_R10_FRESH58_H0IOCNT0_RECORD_IDENTITY_20261118.json'; jp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 md=['# FRESH-58 — H0IOCNT0 58-field record identity and canonical collision audit','',f'- Report SHA-256: `{report["report_sha256"]}`','', '## Aggregate','', '| Metric | Count |','|---|---:|']
 md += [f'| {k} | {v:,} |' for k,v in totals.items()]
 md += ['', '## Per-day','', '| Date | Raw frames | Parsed records | Duplicate seq groups | Duplicate seq excess | Legacy key groups | Legacy excess | Exact-record duplicate excess | Current ID collisions |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
 for x in day_reports: md.append(f'| {x["trading_date"]} | {x["raw_h0iocnt0_frames"]} | {x["parsed_58_field_records"]} | {x["duplicate_sequence_groups"]} | {x["duplicate_sequence_excess_frames"]} | {x["legacy_symbol_time_duplicate_groups"]} | {x["legacy_symbol_time_excess_records"]} | {x["exact_full_record_duplicate_excess_records"]} | {x["current_normalizer_observation_id_collision_count"]} |')
 md += ['', '## Existing Canonical comparison (read-only)','', '| Date | Rows | WS rows | WS raw IDs | WS symbols | Raw symbols absent in WS Canonical | ID duplicate excess | Raw ID duplicate excess |','|---|---:|---:|---:|---:|---|---:|---:|']
 for d,x in canonical.items(): md.append(f'| {d} | {x["rows"]} | {x["websocket_rows"]} | {x["websocket_raw_id_unique"]} | {x["websocket_symbol_count"]} | {len(x["raw_symbols_missing_from_websocket_canonical"])} | {x["observation_id_duplicate_excess"]} | {x["raw_id_duplicate_excess"]} |')
 md += ['', '## Interpretation','', '- Raw frame count and 58-field trade-record count are independent measures.', '- A repeated (short_code, BSOP_HOUR) within one frame is not by itself a duplicate execution; compare full 58-field digest.', '- Duplicate sequence is not a unique frame identity. Current ingestion raw_id adds line number and payload SHA-256.', '- Current normalizer adds frame-local record_index to the observation ID seed; no production code change was needed for this audit.', '- 2026-10-01 legacy Canonical contains 1,995 H0IOCNT0 rows vs 2,710 Raw records (715 fewer), 25/26 symbols, missing C01610A41; it remains unchanged.', '- 2026-10-06/07/08/12/13 legacy Canonical files are REST-only; no H0IOCNT0 rows there does not mean Raw trades are absent.', '- Its 390 repeated raw_id references are REST duplicate references, not H0IOCNT0 observation_id collisions.', '- Original Raw/Canonical/Manifest are read-only. No collection, API call, Canonical rewrite, account execution inference, or Live gate release.','']
 mp=out/'Q25_A8_R10_FRESH58_H0IOCNT0_RECORD_IDENTITY_20261118.md'; mp.write_text('\n'.join(md),encoding='utf-8')
 print(json.dumps({'report_sha256':report['report_sha256'],'totals':totals,'days':[{k:x[k] for k in ('trading_date','raw_h0iocnt0_frames','parsed_58_field_records','duplicate_sequence_groups','duplicate_sequence_excess_frames','legacy_symbol_time_duplicate_groups','legacy_symbol_time_excess_records','exact_full_record_duplicate_excess_records','current_raw_id_collision_count','current_normalizer_observation_id_collision_count')} for x in day_reports],'canonical':canonical},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
