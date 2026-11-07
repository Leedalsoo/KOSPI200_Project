from __future__ import annotations
import hashlib, json, sys, traceback
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.strategy.standard_registry import STANDARD_STRATEGY_KEYS
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner
DATASET=ROOT/'data/synthetic_market_data/20261022_strategy_e2e'
DATA_MANIFEST=DATASET/'manifest.json'
OUT=ROOT/'verification/evidence/synthetic_strategy_e2e_20261022.json'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    if OUT.exists(): raise FileExistsError('REFUSE_OVERWRITE_E2E_EVIDENCE')
    m=json.loads(DATA_MANIFEST.read_text(encoding='utf-8'))
    if m.get('source_type')!='SYNTHETIC' or m.get('runtime_eligible') is not False: raise RuntimeError('SYNTHETIC_ONLY_GUARD_FAILED')
    reports=[]
    for idx,(sid,ver) in enumerate(STANDARD_STRATEGY_KEYS,1):
        runner=HighSpeedVirtualRuntimeReplayRunner(DATASET,run_id=f'SYNTHETIC-E2E-20261022-{idx:02d}-{sid}',strategy_keys=((sid,ver),))
        r=runner.run(max_events=156)
        reports.append({'scope':'strategy_independent','strategy_id':sid,'version':ver,'events':r.events,'exhausted':r.exhausted,
          'signals':r.signals,'approved':r.approved,'routed':r.routed,'filled':r.filled,'rejected':r.rejected,
          'multi_leg_decisions':r.multi_leg_decisions,'strategy_signal_counts':r.strategy_signal_counts,
          'strategy_status':[x.__dict__ for x in r.strategy_status],'realized_pnl':r.realized_pnl,
          'unrealized_pnl':r.unrealized_pnl,'net_pnl':r.net_pnl,
          'runtime_failures':sum(x.runtime_failures for x in r.strategy_status),
          'unavailable':sum(x.unavailable for x in r.strategy_status),
          'verdict':'PASS_SYNTHETIC_RUNTIME_PATH' if r.events==155 and r.exhausted and sum(x.runtime_failures for x in r.strategy_status)==0 else 'BLOCKED'})
    r=HighSpeedVirtualRuntimeReplayRunner(DATASET,run_id='SYNTHETIC-E2E-20261022-INTEGRATED').run(max_events=156)
    integrated={'scope':'integrated','events':r.events,'exhausted':r.exhausted,'signals':r.signals,'approved':r.approved,
      'routed':r.routed,'filled':r.filled,'rejected':r.rejected,'multi_leg_decisions':r.multi_leg_decisions,
      'strategy_signal_counts':r.strategy_signal_counts,'strategy_status':[x.__dict__ for x in r.strategy_status],
      'realized_pnl':r.realized_pnl,'unrealized_pnl':r.unrealized_pnl,'net_pnl':r.net_pnl,
      'runtime_failures':sum(x.runtime_failures for x in r.strategy_status),
      'unavailable':sum(x.unavailable for x in r.strategy_status),
      'verdict':'PASS_SYNTHETIC_RUNTIME_PATH' if r.events==155 and r.exhausted and sum(x.runtime_failures for x in r.strategy_status)==0 else 'BLOCKED'}
    result={'schema_version':'synthetic-strategy-e2e-report-v1','created_at':datetime.now().astimezone().isoformat(),
      'source_type':'SYNTHETIC','runtime_eligible':False,'validation_only':True,
      'dataset_path':str((DATASET/'20261020.jsonl').relative_to(ROOT)),
      'dataset_sha256':sha(DATASET/'20261020.jsonl'),'manifest_sha256':sha(DATA_MANIFEST),
      'synthetic_rows':155,'strategies_expected':9,'strategies_completed':len(reports),
      'order_routing_is_virtual_only':True,'kis_api_calls':0,'strategies':reports,'integrated':integrated,
      'overall_verdict':'PASS_SYNTHETIC_RUNTIME_PATH' if len(reports)==9 and all(x['verdict']=='PASS_SYNTHETIC_RUNTIME_PATH' for x in reports) and integrated['verdict']=='PASS_SYNTHETIC_RUNTIME_PATH' else 'BLOCKED',
      'limitation':'PASS_SYNTHETIC_RUNTIME_PATH confirms isolated Virtual Runtime path only; it is not REAL_VTS or production evidence. Signal/route/fill counts are reported separately and no signal is fabricated to force a PASS.'}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    result['evidence_sha256']=sha(OUT)
    print(json.dumps({'status':result['overall_verdict'],'evidence_path':str(OUT.relative_to(ROOT)),'evidence_sha256':result['evidence_sha256'],
      'per_strategy':[{k:x[k] for k in ('strategy_id','events','signals','approved','routed','filled','runtime_failures','unavailable','verdict')} for x in reports],
      'integrated':{k:integrated[k] for k in ('events','signals','approved','routed','filled','runtime_failures','unavailable','verdict')}},ensure_ascii=False))
if __name__=='__main__': main()
