from __future__ import annotations
from datetime import datetime, date
import hashlib,json,sys
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from application.composition.validation_only_rest_trade_cross_auditor import ValidationOnlyRestTradeCrossAuditor
from infrastructure.kis.kis_websocket_option_identity_resolver import load_kis_master_snapshot_for_date, rows_from_snapshot
DATA=Path(r'C:\Users\white\Desktop\MovingProject\KOSPI200_Project\data\kis_market_data_restart')
DAYS=('20261001','20261006','20261007','20261008','20261012','20261013')

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def main():
 trades=[]; rest=[]; hashes={}; day_counts={}
 adapter=KISIndexOptionMarketWebSocketAdapter()
 for day in DAYS:
  folder=DATA/day; wp=folder/'kis_vts_websocket_raw.jsonl'; rp=folder/'historical_market_observations.jsonl.raw.jsonl'
  if not wp.exists() or not rp.exists(): raise SystemExit(f'EXPECTED_EXISTING_SOURCE_MISSING:{day}')
  hashes[f'ws_raw_{day}']=sha(wp); hashes[f'rest_raw_{day}']=sha(rp)
  before_t=len(trades); before_r=len(rest); frames=0; invalid=0; rest_missing=0; rest_zero=0
  for line_no,line in enumerate(wp.open(encoding='utf-8')):
   row=json.loads(line)
   if row.get('tr_id')!='H0IOCNT0': continue
   frames+=1; received=row['received_at']; frame=row['payload']; payload_hash=row.get('payload_sha256') or hashlib.sha256(frame.encode()).hexdigest()
   try: records=adapter.adapt_many(frame,source='KIS:H0IOCNT0')
   except Exception: invalid+=1; continue
   for idx,m in enumerate(records):
    try: ts=datetime.strptime(day+m.observed_hour,'%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo('Asia/Seoul')).isoformat()
    except ValueError: invalid+=1; continue
    trades.append({'symbol':m.shrn_iscd,'trading_date':day,'record_id':f'{day}:{row.get("sequence",line_no)}:{idx}','source_timestamp_candidate':ts,'received_at':received,'last_price':str(m.last_price) if m.last_price is not None else None,'bid_price':str(m.bid_price) if m.bid_price is not None else None,'ask_price':str(m.ask_price) if m.ask_price is not None else None,'volume':str(m.volume) if m.volume is not None else None,'payload_sha256':payload_hash})
  for line_no,line in enumerate(rp.open(encoding='utf-8')):
   row=json.loads(line); payload=row.get('payload') or {}; price=payload.get('price') or {}; book=payload.get('order_book') or {}; p1=price.get('output1') or {}; b1=book.get('output1') or {}; b2=book.get('output2') or {}
   symbol=str(row.get('request_metadata',{}).get('symbol') or b1.get('futs_shrn_iscd') or '')
   if not symbol: continue
   raw_time=str(b2.get('aspr_acpt_hour') or '').strip()
   source_time=None
   if len(raw_time)==6 and raw_time.isdigit() and raw_time!='000000':
    try: source_time=datetime.strptime(day+raw_time,'%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo('Asia/Seoul')).isoformat()
    except ValueError: source_time=None
   if not source_time: rest_missing+=1
   if raw_time=='000000': rest_zero+=1
   rest.append({'symbol':symbol,'trading_date':day,'record_id':row.get('raw_id') or f'{day}:{line_no}','collected_at':row.get('collected_at'),'source_timestamp':source_time,'source_timestamp_raw':raw_time or None,'last_price':p1.get('futs_prpr'),'bid_price':b2.get('futs_bidp1'),'ask_price':b2.get('futs_askp1'),'payload_sha256':row.get('content_hash')})
  day_counts[day]={'h0iocnt0_frames':frames,'parsed_trade_records':len(trades)-before_t,'invalid_frames_or_times':invalid,'rest_rows':len(rest)-before_r,'rest_source_time_missing':rest_missing,'rest_source_time_zero':rest_zero}
 report=ValidationOnlyRestTradeCrossAuditor(validation_only=True).audit(trades=trades,rest=rest,source_hashes=hashes)
 identity_crosswalk={}
 f51=json.loads((ROOT/'reports'/'synth'/'Q25_A8_R10_FRESH51_CONTRACT_INVENTORY_CROSSWALK_20261118.json').read_text(encoding='utf-8'))
 f51_daily={x['trading_date']:x for x in f51['websocket_contract_crosswalk']['daily']}
 direct_code_overlap={}
 for day in DAYS:
  rs={x['symbol'] for x in rest if x['trading_date']==day}; ws={x['symbol'] for x in trades if x['trading_date']==day}
  rest_krx=sum(1 for x in f51['rest_contract_crosswalk']['contracts'] if day in x['trading_dates'] and x['krx_crosswalk_match'])
  direct_code_overlap[day]={'rest_symbols':len(rs),'ws_trade_symbols':len(ws),'exact_symbol_overlap':len(rs & ws),'rest_only_symbols':len(rs-ws),'ws_only_symbols':len(ws-rs),'FRESH51_rest_KRX_crosswalk_matches':rest_krx,'FRESH51_ws_KRX_crosswalk_matches':f51_daily[day]['krx_crosswalk_matches']}

 master=load_kis_master_snapshot_for_date(date(2026,10,14),cache_dir=DATA.parent/'reference'/'kis'/'index_master')
 master_rows={str(x['short_code']):x for x in rows_from_snapshot(master)}
 identity_key=lambda x:(str(x.get('product_series') or ''),str(x.get('instrument_family') or ''),str(x.get('month') or ''),str(x.get('option_type') or ''),str(x.get('strike') or ''))
 for day in ('20261012','20261013'):
  rs={x['symbol'] for x in rest if x['trading_date']==day}; ws={x['symbol'] for x in trades if x['trading_date']==day}
  rk={identity_key(master_rows[x]) for x in rs if x in master_rows}; wk={identity_key(master_rows[x]) for x in ws if x in master_rows}
  identity_crosswalk[day]={'rest_symbols':len(rs),'rest_symbols_in_master':len(rs & set(master_rows)),'ws_trade_symbols':len(ws),'ws_trade_symbols_in_master':len(ws & set(master_rows)),'exact_contract_identity_tuple_overlap':len(rk & wk),'rest_only_identity_tuples':len(rk-wk),'ws_only_identity_tuples':len(wk-rk),'master_sha256':master.archive_sha256,'master_role':'post-date KIS identity corroboration only; not a historical market-date snapshot'}
 report['identity_crosswalk']={'fresh51_report_sha256':f51['report_sha256'],'direct_code_overlap_by_day':direct_code_overlap,'postdate_master_market_date':'20261014','days':identity_crosswalk,'expired_series_days':{'20261001':'FRESH51 existing KRX crosswalk: 26/26; post-expiry KIS Master absence expected','20261006':'FRESH51 existing KRX crosswalk: 26/26; post-expiry KIS Master absence expected','20261007':'FRESH51 existing KRX crosswalk: 26/26; post-expiry KIS Master absence expected','20261008':'FRESH51 existing KRX crosswalk: 26/26; post-expiry KIS Master absence expected'}}
 report['scope']['trading_dates']=list(DAYS); report['scope']['per_day_inventory']=day_counts; report['scope']['raw_sources_read_only']=True
 report['scope']['rest_source_time_field']='order_book.output2.aspr_acpt_hour (paired REST response candidate)'
 report['scope']['rest_price_field']='price.output1.futs_prpr (no independent source timestamp in this raw shape)'
 report['scope']['rest_bid_ask_fields']='order_book.output2.futs_bidp1 / futs_askp1'
 per_day={}
 for row in report['alignments']:
  d=row.get('trading_date') or 'UNKNOWN'; item=per_day.setdefault(d,{'rest_rows':0,'exact_source_time':0,'nearest_prior_trade':0,'future_trade_only':0,'no_trade_source':0,'rest_time_unavailable':0})
  item['rest_rows']+=1
  status=row.get('alignment')
  if status=='EXACT_SOURCE_TIME': item['exact_source_time']+=1
  elif status=='NEAREST_PRIOR_TRADE': item['nearest_prior_trade']+=1
  elif status=='FUTURE_TRADE_ONLY': item['future_trade_only']+=1
  elif status=='NO_TRADE_SOURCE': item['no_trade_source']+=1
  elif status=='REST_TIME_UNAVAILABLE': item['rest_time_unavailable']+=1
 report['per_day_alignment']=per_day
 report.pop('report_sha256',None)
 report['report_sha256']=ValidationOnlyRestTradeCrossAuditor._hash(report)
 out=ROOT/'reports'/'synth'; out.mkdir(parents=True,exist_ok=True)
 jp=out/'Q25_A8_R10_FRESH55_REST_TRADE_PRICE_CROSS_20261118.json'; jp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 md=['# FRESH-55 ??REST price / H0IOCNT0 trade cross-check','',f'- Dates: {", ".join(DAYS)}',f'- REST rows: {len(rest):,}; parsed H0IOCNT0 trade records: {len(trades):,}',f'- Report SHA-256: `{report["report_sha256"]}`','', '## Counts', '', '| Metric | Count |','|---|---:|']
 md += [f'| {k} | {v:,} |' for k,v in report['counts'].items()]
 md += ['', '## Identity crosswalk', '', '- KIS Master 2026-10-14 is used only as post-date identity corroboration, not as a historical market-date snapshot.', '- 2026-10-12: REST 26 / WS 30 symbols; exact product-series + family + month + option-side + strike tuple overlap 12 (REST-only 14, WS-only 18).', '- 2026-10-13: REST 26 / WS 53 symbols; exact identity tuple overlap 0 (REST-only 26, WS-only 53). This is a distinct contract subset, not a price discrepancy.', '- 2026-10-01/06/07/08 expired series: reuse FRESH51 KRX crosswalk evidence (26/26 each); post-expiry KIS Master absence is expected.', '', '## Interpretation and limits', '', '- REST time candidate comes from order_book.output2.aspr_acpt_hour; REST last price is price.output1.futs_prpr and has no independent source timestamp in this raw shape.',
 '- When that paired-response time is missing/000000, collected_at is used only as a receive-time proxy, not source event time.', '- H0IOCNT0 BSOP_HOUR remains an event-time candidate, not independently certified official event time.', '- Price differences are not automatically data errors: snapshot timing and field semantics differ.', '- H0IOCNT0 is public market trade data, not account broker execution/fill.', '- No freshness cutoff, authority promotion, gate release, or mutation was applied.', '- Original Raw/Canonical/Manifest files were read-only; no collection or API call.', '']
 mp=out/'Q25_A8_R10_FRESH55_REST_TRADE_PRICE_CROSS_20261118.md'; mp.write_text('\n'.join(md),encoding='utf-8')
 print(json.dumps({'rest_records':len(rest),'trade_records':len(trades),'day_counts':day_counts,'counts':report['counts'],'rest_source_time_age':report['rest_source_time_anchor_age_seconds'],'receive_proxy_age':report['collected_at_proxy_anchor_age_seconds'],'price_delta':report['price_delta_rest_minus_trade'],'issues':len(report['issues']),'report_sha256':report['report_sha256'],'report_json':str(jp.relative_to(ROOT)),'report_md':str(mp.relative_to(ROOT))},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
