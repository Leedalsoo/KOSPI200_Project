from __future__ import annotations
from datetime import datetime
import hashlib,json,sys
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from application.composition.validation_only_rest_ws_orderbook_depth_auditor import ValidationOnlyRestWsOrderBookDepthAuditor
DATA=Path(r'C:\Users\white\Desktop\MovingProject\KOSPI200_Project\data\kis_market_data_restart')
DAY='20261001'

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def main():
 folder=DATA/DAY; wp=folder/'kis_vts_websocket_orderbook_raw.jsonl'; rp=folder/'historical_market_observations.jsonl.raw.jsonl'
 if not wp.exists() or not rp.exists(): raise SystemExit('EXPECTED_EXISTING_SOURCE_MISSING:20261001')
 hashes={'rest_raw':sha(rp),'ws_h0ioasp0_raw':sha(wp),'daily_manifest':sha(folder/'manifest.json'),'fresh53_report':sha(ROOT/'reports'/'synth'/'Q25_A8_R10_FRESH53_REST_WS_ORDERBOOK_TIME_ALIGNMENT_20261118.json')}
 adapter=KISIndexOptionMarketWebSocketAdapter(); rest=[]; ws=[]; invalid_rest=0; invalid_ws=0; zero_time=0
 for i,line in enumerate(rp.open(encoding='utf-8')):
  row=json.loads(line); payload=row.get('payload') or {}; book=payload.get('order_book') or {}; b1=book.get('output1') or {}; b2=book.get('output2') or {}; symbol=str(row.get('request_metadata',{}).get('symbol') or b1.get('futs_shrn_iscd') or '')
  raw_time=str(b2.get('aspr_acpt_hour') or '').strip(); ts=None
  if len(raw_time)==6 and raw_time.isdigit() and raw_time!='000000':
   try: ts=datetime.strptime(DAY+raw_time,'%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo('Asia/Seoul')).isoformat()
   except ValueError: invalid_rest+=1
  else: zero_time+=1
  if not symbol: invalid_rest+=1; continue
  def levels(side):
   return [{'price':b2.get(f'futs_{side}p{n}'),'quantity':b2.get(f'{side}p_rsqn{n}')} for n in range(1,6)]
  rest.append({'symbol':symbol,'trading_date':DAY,'record_id':row.get('raw_id') or f'REST:{i}','source_timestamp_candidate':ts,'source_timestamp_raw':raw_time or None,'collected_at':row.get('collected_at'),'bids':levels('bid'),'asks':levels('ask'),'payload_sha256':row.get('content_hash')})
 for i,line in enumerate(wp.open(encoding='utf-8')):
  row=json.loads(line)
  try: m=adapter.adapt(row['payload'],source='KIS:H0IOASP0')
  except Exception: invalid_ws+=1; continue
  if m.order_book is None: invalid_ws+=1; continue
  try: ts=datetime.strptime(DAY+m.observed_hour,'%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo('Asia/Seoul')).isoformat()
  except ValueError: invalid_ws+=1; continue
  ws.append({'symbol':m.shrn_iscd,'trading_date':DAY,'record_id':f'WS:{row.get("sequence",i)}','source_timestamp_candidate':ts,'received_at':row.get('received_at'),'bids':[{'price':str(x.price),'quantity':str(x.quantity)} for x in m.order_book.bid_levels],'asks':[{'price':str(x.price),'quantity':str(x.quantity)} for x in m.order_book.ask_levels],'payload_sha256':row.get('payload_sha256')})
 report=ValidationOnlyRestWsOrderBookDepthAuditor(validation_only=True).audit(rest_records=rest,ws_records=ws,source_hashes=hashes)
 report['scope']['rest_source_time_missing_or_zero']=zero_time; report['scope']['invalid_rest_rows']=invalid_rest; report['scope']['invalid_ws_frames']=invalid_ws; report['scope']['raw_sources_read_only']=True
 per_alignment={}
 for status in ('EXACT_SOURCE_TIME','NEAREST_PRIOR'):
  matched=[x for x in report['alignments'] if x.get('alignment')==status]
  levels=[v for row in matched for v in (row.get('levels') or {}).values()]
  per_alignment[status]={'snapshots':len(matched),'price_equal':sum(v['price_status']=='EQUAL' for v in levels),'price_different':sum(v['price_status']=='DIFFERENT' for v in levels),'price_both_empty':sum(v['price_status']=='BOTH_EMPTY' for v in levels),'price_one_empty':sum(v['price_status']=='ONE_EMPTY' for v in levels),'price_missing':sum(v['price_status']=='MISSING' for v in levels),'quantity_equal':sum(v['quantity_status']=='EQUAL' for v in levels),'quantity_different':sum(v['quantity_status']=='DIFFERENT' for v in levels),'quantity_missing':sum(v['quantity_status']=='MISSING' for v in levels)}
 report['per_alignment_summary']=per_alignment
 report.pop('report_sha256',None); report['report_sha256']=ValidationOnlyRestWsOrderBookDepthAuditor._hash(report)
 out=ROOT/'reports'/'synth'; out.mkdir(parents=True,exist_ok=True)
 jp=out/'Q25_A8_R10_FRESH56_REST_WS_ORDERBOOK_DEPTH_CROSS_20261118.json'; jp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 md=['# FRESH-56 — REST / H0IOASP0 OrderBook price and depth cross-check','',f'- REST rows: {len(rest):,}; H0IOASP0 frames: {len(ws):,}; contracts: {report["scope"]["contracts"]}',f'- Report SHA-256: `{report["report_sha256"]}`','', '## Alignment counts','', '| Metric | Count |','|---|---:|']
 md += [f'| {k} | {v:,} |' for k,v in report['counts'].items()]
 md += ['', '## Exact vs nearest-prior summary', '', '| Alignment | Snapshots | Price equal | Different | Both empty | One empty | Missing | Qty equal | Qty different |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
 for status,x in report['per_alignment_summary'].items():
  md.append(f'| {status} | {x["snapshots"]} | {x["price_equal"]} | {x["price_different"]} | {x["price_both_empty"]} | {x["price_one_empty"]} | {x["price_missing"]} | {x["quantity_equal"]} | {x["quantity_different"]} |')
 md += ['', '## Per-level comparisons','']
 for side in ('bid','ask'):
  md += [f'### {side.upper()}', '', '| Level | Price equal | Different | Both empty | One empty | Missing | Qty equal | Qty different |', '|---:|---:|---:|---:|---:|---:|---:|']
  for level,x in report['per_level'][side].items(): md.append(f'| {level} | {x["price_equal"]} | {x["price_different"]} | {x["price_both_empty"]} | {x["price_one_empty"]} | {x["price_missing"]} | {x["quantity_equal"]} | {x["quantity_different"]} |')
 md += ['', '## Interpretation and limits','', '- Same-contract nearest-prior REST source-time candidate is compared to H0IOASP0 HHMMSS candidate; the latter is not promoted to official event time.', '- Price and quantity differences are preserved as observed; no arbitrary freshness cutoff or error classification is applied.', '- Empty/zero depth is counted separately from equal nonzero depth.', '- This is market-data cross-validation, not broker execution/fill evidence or proof of authoritative KIS depth semantics.', '- Original Raw/Canonical/Manifest files were read-only; no new collection/API call, authority promotion, gate release or mutation.','']
 mp=out/'Q25_A8_R10_FRESH56_REST_WS_ORDERBOOK_DEPTH_CROSS_20261118.md'; mp.write_text('\n'.join(md),encoding='utf-8')
 print(json.dumps({'rest_records':len(rest),'ws_records':len(ws),'contracts':report['scope']['contracts'],'counts':report['counts'],'per_level':report['per_level'],'rest_source_missing_or_zero':zero_time,'invalid_rest':invalid_rest,'invalid_ws':invalid_ws,'rest_lag':report['rest_source_to_collected_lag_seconds'],'ws_lag':report['ws_candidate_to_received_lag_seconds'],'anchor_age':report['rest_anchor_age_seconds'],'issues':len(report['issues']),'report_sha256':report['report_sha256']},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
