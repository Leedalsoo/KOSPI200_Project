from __future__ import annotations
import hashlib,json,sys
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner
DATASET=ROOT/'data/synthetic_market_data/1y_5min_v1'; OUT=ROOT/'verification/evidence/synthetic_integrated_e2e_780_20261022.json'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 if OUT.exists(): raise FileExistsError('REFUSE_OVERWRITE_INTEGRATED_E2E_EVIDENCE')
 r=HighSpeedVirtualRuntimeReplayRunner(DATASET,run_id='SYNTHETIC-INTEGRATED-E2E-20261022-780').run(max_events=781)
 result={'schema_version':'synthetic-integrated-e2e-report-v1','created_at':datetime.now().astimezone().isoformat(),'scope':'offline synthetic Virtual Runtime; first 780 events of existing 1y synthetic scenario','source_type':'SYNTHETIC','runtime_eligible':False,'dataset_path':str(DATASET.relative_to(ROOT)),'events':r.events,'exhausted':r.exhausted,'signals':r.signals,'approved':r.approved,'routed':r.routed,'filled':r.filled,'rejected':r.rejected,'multi_leg_decisions':r.multi_leg_decisions,'execution_ids':len(r.execution_ids),'strategy_signal_counts':r.strategy_signal_counts,'strategy_status':[x.__dict__ for x in r.strategy_status],'realized_pnl':r.realized_pnl,'unrealized_pnl':r.unrealized_pnl,'net_pnl':r.net_pnl,'runtime_failures':sum(x.runtime_failures for x in r.strategy_status),'unavailable':sum(x.unavailable for x in r.strategy_status),'kis_api_calls':0,'live_or_account_api_calls':0,'verdict':'PASS_SYNTHETIC_INTEGRATED_LIFECYCLE' if r.events==780 and r.signals>0 and r.approved>0 and r.routed>0 and r.filled>0 and sum(x.runtime_failures for x in r.strategy_status)==0 else 'BLOCKED','limitations':'Synthetic-only integrated lifecycle evidence; not REAL_VTS/production evidence and not full 1-year replay.'}
 OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); result['evidence_sha256']=sha(OUT)
 print(json.dumps({'verdict':result['verdict'],'evidence_path':str(OUT.relative_to(ROOT)),'evidence_sha256':result['evidence_sha256'],'events':r.events,'signals':r.signals,'approved':r.approved,'routed':r.routed,'filled':r.filled,'rejected':r.rejected,'multi_leg_decisions':r.multi_leg_decisions,'execution_ids':len(r.execution_ids),'strategy_signal_counts':r.strategy_signal_counts,'runtime_failures':result['runtime_failures'],'unavailable':result['unavailable'],'realized_pnl':r.realized_pnl,'unrealized_pnl':r.unrealized_pnl,'net_pnl':r.net_pnl},ensure_ascii=False,default=str))
if __name__=='__main__': main()
