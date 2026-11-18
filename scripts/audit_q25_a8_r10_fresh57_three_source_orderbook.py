from __future__ import annotations
from datetime import datetime
import hashlib,json,sys
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from application.composition.validation_only_three_source_orderbook_auditor import ValidationOnlyThreeSourceOrderBookAuditor
DATA=Path(r'C:\Users\white\Desktop\MovingProject\KOSPI200_Project\data\kis_market_data_restart')
DAY='20261001'

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def stamp(value): return datetime.strptime(DAY+value,'%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo('Asia/Seoul')).isoformat()

def main():
 folder=DATA/DAY; rp=folder/'historical_market_observations.jsonl.raw.jsonl'; tp=folder/'kis_vts_websocket_raw.jsonl'; wp=folder/'kis_vts_websocket_orderbook_raw.jsonl'
 paths={'rest_raw':rp,'h0iocnt0_raw':tp,'h0ioasp0_raw':wp,'daily_manifest':folder/'manifest.json'}
 for name,p in paths.items():
  if not p.exists(): raise SystemExit(f'EXPECTED_EXISTING_SOURCE_MISSING:{p}')
 hashes={k:sha(v) for k,v in paths.items()}
 for name in ('Q25_A8_R10_FRESH53_REST_WS_ORDERBOOK_TIME_ALIGNMENT_20261118.json','Q25_A8_R10_FRESH54_H0IOCNT0_TRADE_TO_H0IOASP0_ORDERBOOK_CROSS_20261118.json','Q25_A8_R10_FRESH55_REST_TRADE_PRICE_CROSS_20261118.json','Q25_A8_R10_FRESH56_REST_WS_ORDERBOOK_DEPTH_CROSS_20261118.json'):
  p=ROOT/'reports'/'synth'/name; hashes[name]=sha(p)
 adapter=KISIndexOptionMarketWebSocketAdapter(); rest_by={}; trade_by={}; rest_invalid=0; trade_invalid=0; ws_invalid=0; zero_rest_time=0
 for i,line in enumerate(rp.open(encoding='utf-8')):
  row=json.loads(line); payload=row.get('payload') or {}; book=payload.get('order_book') or {}; b1=book.get('output1') or {}; b2=book.get('output2') or {}; symbol=str(row.get('request_metadata',{}).get('symbol') or b1.get('futs_shrn_iscd') or '')
  raw_time=str(b2.get('aspr_acpt_hour') or '').strip()
  if not(len(raw_time)==6 and raw_time.isdigit() and raw_time!='000000'): zero_rest_time+=1; continue
  try: ts=stamp(raw_time)
  except ValueError: rest_invalid+=1; continue
  def val(k): return b2.get(k)
  rec={'symbol':symbol,'trading_date':DAY,'record_id':row.get('raw_id') or f'REST:{i}','source_timestamp_candidate':ts,'collected_at':row.get('collected_at'),'bid_price':val('futs_bidp1'),'ask_price':val('futs_askp1'),'bid_quantity':val('bidp_rsqn1'),'ask_quantity':val('askp_rsqn1'),'payload_sha256':row.get('content_hash')}
  if symbol: rest_by.setdefault(symbol,[]).append(rec)
  else: rest_invalid+=1
 for i,line in enumerate(tp.open(encoding='utf-8')):
  row=json.loads(line)
  if row.get('tr_id')!='H0IOCNT0': continue
  try: records=adapter.adapt_many(row['payload'],source='KIS:H0IOCNT0')
  except Exception: trade_invalid+=1; continue
  for n,m in enumerate(records):
   try: ts=stamp(m.observed_hour)
   except ValueError: trade_invalid+=1; continue
   trade_by.setdefault(m.shrn_iscd,[]).append({'symbol':m.shrn_iscd,'trading_date':DAY,'record_id':f'TRADE:{row.get("sequence",i)}:{n}','source_timestamp_candidate':ts,'received_at':row.get('received_at'),'bid_price':str(m.bid_price) if m.bid_price is not None else None,'ask_price':str(m.ask_price) if m.ask_price is not None else None,'last_price':str(m.last_price) if m.last_price is not None else None,'payload_sha256':row.get('payload_sha256')})
 for values in list(rest_by.values())+list(trade_by.values()): values.sort(key=lambda x:(x['source_timestamp_candidate'],x['record_id']))
 triples=[]
 for i,line in enumerate(wp.open(encoding='utf-8')):
  row=json.loads(line)
  try: m=adapter.adapt(row['payload'],source='KIS:H0IOASP0')
  except Exception: ws_invalid+=1; continue
  if m.order_book is None: ws_invalid+=1; continue
  try: candidate=stamp(m.observed_hour)
  except ValueError: ws_invalid+=1; continue
  symbol=m.shrn_iscd
  prior_rest=[x for x in rest_by.get(symbol,[]) if x['source_timestamp_candidate']<=candidate]
  prior_trade=[x for x in trade_by.get(symbol,[]) if x['source_timestamp_candidate']<=candidate]
  r=prior_rest[-1] if prior_rest else None; t=prior_trade[-1] if prior_trade else None
  triples.append({'symbol':symbol,'trading_date':DAY,'record_id':f'WSBOOK:{row.get("sequence",i)}','ws_time_candidate':candidate,'ws_received_at':row.get('received_at'),'rest_anchor':r,'trade_anchor':t,'ws_orderbook':{'bid_price':str(m.order_book.bid_levels[0].price),'bid_quantity':str(m.order_book.bid_levels[0].quantity),'ask_price':str(m.order_book.ask_levels[0].price),'ask_quantity':str(m.order_book.ask_levels[0].quantity)},'ws_payload_sha256':row.get('payload_sha256')})
 report=ValidationOnlyThreeSourceOrderBookAuditor(validation_only=True).audit(triples=triples,source_hashes=hashes)
 report['scope']['rest_source_time_missing_or_zero']=zero_rest_time; report['scope']['invalid_rest_rows']=rest_invalid; report['scope']['invalid_trade_frames_or_times']=trade_invalid; report['scope']['invalid_ws_frames_or_times']=ws_invalid; report['scope']['rest_contracts']=len(rest_by); report['scope']['trade_contracts']=len(trade_by); report['scope']['raw_sources_read_only']=True
 report.pop('report_sha256',None); report['report_sha256']=ValidationOnlyThreeSourceOrderBookAuditor._hash(report)
 out=ROOT/'reports'/'synth'; out.mkdir(parents=True,exist_ok=True)
 jp=out/'Q25_A8_R10_FRESH57_THREE_SOURCE_ORDERBOOK_TRIANGULATION_20261118.json'; jp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 md=['# FRESH-57 — REST / H0IOCNT0 / H0IOASP0 three-source triangulation','',f'- WS OrderBook snapshots: {len(triples):,}; report SHA-256: `{report["report_sha256"]}`','', '## Alignment','', '| Metric | Count |','|---|---:|']
 md += [f'| {k} | {v:,} |' for k,v in report['counts'].items()]
 md += ['', '## Pairwise price comparison','']
 for pair, sides in report['pairwise_price_comparison'].items():
  md += [f'### {pair}', '', '| Side | Equal | Different | Both empty | One empty | Missing | Delta median | Delta p90 |', '|---|---:|---:|---:|---:|---:|---:|---:|']
  for side,x in sides.items(): md.append(f'| {side} | {x["price_equal"]} | {x["price_different"]} | {x["price_both_empty"]} | {x["price_one_empty"]} | {x["price_missing"]} | {x["price_delta_stats"]["median"]} | {x["price_delta_stats"]["p90"]} |')
 md += ['', '## Three-source consensus','']
 for side,x in report['three_source_consensus'].items(): md.append(f'- {side}: all-three equal {x["all_three_equal"]}, mixed/different {x["all_three_different_or_mixed"]}, missing/empty {x["missing_or_empty"]}')
 md += ['', '## Time age','',f'- REST anchor age: `{report["rest_anchor_age_seconds"]}`',f'- Trade anchor age: `{report["trade_anchor_age_seconds"]}`','', '## Interpretation and limits','', '- All sources are aligned to the same H0IOASP0 HHMMSS candidate per same-contract row; this candidate is not official event time.', '- REST and H0IOCNT0 anchors use nearest-prior only; no future or cross-day anchor is accepted.', '- Differences are retained with separate anchor ages; no freshness cutoff or automatic error/blocked decision.', '- H0IOCNT0 is public market trade data, not account broker execution/fill. No authority promotion, gate release, mutation, or new collection.','']
 mp=out/'Q25_A8_R10_FRESH57_THREE_SOURCE_ORDERBOOK_TRIANGULATION_20261118.md'; mp.write_text('\n'.join(md),encoding='utf-8')
 print(json.dumps({'triples':len(triples),'counts':report['counts'],'pairwise':report['pairwise_price_comparison'],'quantity':report['rest_vs_ws_quantity_comparison'],'consensus':report['three_source_consensus'],'rest_age':report['rest_anchor_age_seconds'],'trade_age':report['trade_anchor_age_seconds'],'invalid':{'rest':rest_invalid,'trade':trade_invalid,'ws':ws_invalid},'issues':report['issues'][:20],'report_sha256':report['report_sha256']},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
