from __future__ import annotations
import hashlib, json, math
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/'data/synthetic_market_data/20261020/synthetic_quote_repairs_20261020.jsonl'
INPUT_MANIFEST=INPUT.with_suffix('.manifest.json')
OUTDIR=ROOT/'data/synthetic_market_data/20261022_strategy_e2e'
OUT=OUTDIR/'20261020.jsonl'
MANIFEST=OUTDIR/'manifest.json'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    if OUT.exists() or MANIFEST.exists(): raise FileExistsError('REFUSE_OVERWRITE_SYNTHETIC_E2E_DATASET')
    im=json.loads(INPUT_MANIFEST.read_text(encoding='utf-8'))
    if im.get('source_type')!='SYNTHETIC' or im.get('runtime_eligible') is not False or sha(INPUT)!=im.get('output_sha256'):
        raise RuntimeError('SYNTHETIC_QUOTE_REPAIR_INPUT_GUARD_FAILED')
    rows=[json.loads(line)['observation'] for line in INPUT.read_text(encoding='utf-8').splitlines() if line.strip()]
    if len(rows)!=155: raise RuntimeError(f'EXPECTED_155_REPAIRED_ROWS:{len(rows)}')
    events=[]
    for i,o in enumerate(rows,1):
        c=o.get('contract') or {}; q=o.get('quote') or {}
        if not (q.get('bid') and q.get('ask') and float(q['bid'])>0 and float(q['ask'])>=float(q['bid'])): raise RuntimeError(f'INVALID_REPAIRED_QUOTE:{i}')
        if not c.get('expiry') or not c.get('option_type') or c.get('strike') is None: raise RuntimeError(f'CONTRACT_IDENTITY_MISSING:{i}')
        stamp=o.get('observed_at') or o.get('collected_at')
        if not stamp: raise RuntimeError(f'TIMESTAMP_MISSING:{i}')
        strike=float(c['strike']); opt=str(c['option_type']).upper()
        # Explicit deterministic scenario model; not reconstructed market truth.
        spot=900.0 + 1.75*math.sin(i/7.0) + 0.025*i
        intrinsic=max(0.0, spot-strike) if opt=='CALL' else max(0.0,strike-spot)
        time_value=2.0 + (i%13)*0.17 + abs(math.sin(i/5.0))*0.8
        last=round(max(0.05,intrinsic*0.12+time_value),2)
        volume=100 + (i*37)%1900
        bid=float(q['bid']); ask=float(q['ask'])
        if ask<bid: raise RuntimeError(f'CROSSED_BOOK:{i}')
        tick={
          'timestamp':stamp,'underlying_price':round(spot,4),'underlying_symbol':'SYNTHETIC-KOSPI200',
          'underlying_observed_hour':datetime.fromisoformat(stamp.replace('Z','+00:00')).strftime('%Y%m%d%H'),
          'underlying_source':'SYNTHETIC:scenario-underlying-v1','strike_price':strike,'option_type':opt,
          'contract_multiplier':250000.0,'bid_price':bid,'ask_price':ask,'last_price':last,'volume':volume,
          'seq_id':i,'expiry':str(c['expiry']),'symbol':str(c.get('symbol') or c.get('instrument_id')),
          'option_source':'SYNTHETIC','instrument_id':str(c.get('instrument_id') or c.get('symbol')),
          'implied_volatility':round(0.18+abs(strike-spot)/max(spot,1)*0.015,6),
          'delta':round((0.5 if opt=='CALL' else -0.5)+max(-0.4,min(0.4,(spot-strike)/max(spot,1))),6),
          'gamma':0.01,'theta':-0.01,'vega':0.2
        }
        events.append({'schema':'reference-canonical-market-tick-v1','provenance':'SYNTHETIC','tick':tick,
          'scenario_metadata':{'source_type':'SYNTHETIC','runtime_eligible':False,'validation_only':True,
            'source_repaired_observation_id':o.get('observation_id'),'source_canonical_sha256':im['source_canonical_sha256'],
            'quote_repair_method':'nearest_same_symbol_valid_two_sided_kis_vts_canonical_order_book',
            'synthetic_fields':['underlying_price','underlying_symbol','last_price','volume','contract_multiplier','implied_volatility','delta','gamma','theta','vega'],
            'scenario_model':'deterministic-option-scenario-v1'}})
    events.sort(key=lambda r:(datetime.fromisoformat(r['tick']['timestamp'].replace('Z','+00:00')),r['tick']['seq_id']))
    for seq,e in enumerate(events,1): e['tick']['seq_id']=seq
    OUTDIR.mkdir(parents=True,exist_ok=False)
    with OUT.open('x',encoding='utf-8',newline='\n') as f:
      for e in events: f.write(json.dumps(e,separators=(',',':'),ensure_ascii=False)+'\n')
    manifest={'schema_version':'synthetic-strategy-e2e-manifest-v1','source_type':'SYNTHETIC','runtime_eligible':False,'validation_only':True,
      'purpose':'offline virtual-runtime strategy E2E and integrated E2E only; never REAL_VTS or production input',
      'source_quote_repairs_path':str(INPUT.relative_to(ROOT)),'source_quote_repairs_sha256':sha(INPUT),
      'source_canonical_sha256':im['source_canonical_sha256'],'rows':len(events),'output_path':str(OUT.relative_to(ROOT)),
      'output_sha256':sha(OUT),'synthetic_model':'deterministic-option-scenario-v1',
      'assumptions':{'underlying':'900 + deterministic bounded trend/oscillation','last':'intrinsic-derived scenario premium plus deterministic time value; not bid/ask midpoint',
       'volume':'deterministic scenario-only integer','contract_multiplier':250000.0,'analytics':'deterministic scenario values'},
      'guardrails':['Original KIS canonical and quote-repair files are read-only and unchanged.','Every row is explicitly SYNTHETIC and runtime_eligible=false.','Dataset is used only in isolated offline Virtual Runtime replay.','No KIS API, Live, order, account, or collector calls.','Synthetic assumptions are test fixtures, not strategy production configuration or historical truth.']}
    MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'PASS_SYNTHETIC_E2E_DATASET_CREATED','rows':len(events),'dataset':str(OUT.relative_to(ROOT)),'sha256':sha(OUT),'manifest':str(MANIFEST.relative_to(ROOT)),'manifest_sha256':sha(MANIFEST),'runtime_eligible':False},ensure_ascii=False))
if __name__=='__main__': main()
