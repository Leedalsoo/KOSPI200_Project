from __future__ import annotations
from dataclasses import asdict, is_dataclass
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from environments.high_speed.replay_trace import ReplayLogMode
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner
DATA=ROOT/'data/derived_scenario/q25_s9_independent_overnight_stop_loss_20261108'
MANIFEST=DATA/'manifest.json'
CONTRACT=ROOT/'config/validation_only/track9_independent_synthetic_contract_profile.json'
RISK=ROOT/'config/validation_only/q25_s9_independent_overnight_20261108/risk_profile.json'
TRACE=ROOT/'reports/synth/S9_INDEPENDENT_ATM_OVERNIGHT_STOP_LOSS_DETAILED_20261108.jsonl'
REPORT=ROOT/'reports/synth/S9_INDEPENDENT_ATM_OVERNIGHT_STOP_LOSS_E2E_20261108.json'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def summary(r): return {k:getattr(r,k) for k in ('events','signals','approved','routed','filled','rejected','realized_pnl','unrealized_pnl','net_pnl','pnl_status','trace_status')}
def run(mode,suffix,trace=None):
    runner=HighSpeedVirtualRuntimeReplayRunner(DATA,run_id=f'S9-STOP-LOSS-20261108-{suffix}',
      strategy_keys=(('track9_event_overnight_insurance','3.0'),),validation_only_synthetic=True,
      validation_only_synthetic_manifest=MANIFEST,validation_only_s9_contract_profile=CONTRACT,
      validation_only_s9_risk_profile=RISK,log_mode=mode,trace_output=trace)
    report=runner.run(); return runner,report

def main():
    for p in (TRACE,REPORT,REPORT.with_suffix('.json.sha256')):
        if p.exists(): raise RuntimeError(f'REFUSE_OVERWRITE:{p.relative_to(ROOT)}')
    m=json.loads(MANIFEST.read_text(encoding='utf-8'))
    if any(v!='MISSING' for v in m['official_data_status'].values()): raise RuntimeError('OFFICIAL_DATA_MUST_REMAIN_MISSING')
    fast,fr=run(ReplayLogMode.FAST,'FAST'); det,dr=run(ReplayLogMode.DETAILED,'DETAILED',TRACE)
    fs,ds=fast.s9_runtime_snapshot,det.s9_runtime_snapshot
    f,d=summary(fr),summary(dr)
    fields=('events','signals','approved','routed','filled','rejected','realized_pnl','unrealized_pnl','net_pnl','pnl_status')
    equivalent=all(f[k]==d[k] for k in fields) and fs['strategy_state']==ds['strategy_state']=='OVERNIGHT_INSURANCE_CLOSED' and fs['strategy_exit_reason']==ds['strategy_exit_reason']=='OPENING_MOVE_BELOW_1PCT_STOP_LOSS' and len(fs['open_lots'])==len(ds['open_lots'])==0
    if not equivalent: raise RuntimeError('S9_STOP_LOSS_FAST_DETAILED_MISMATCH')
    for label,snap,rep in (('FAST',fs,f),('DETAILED',ds,d)):
      if (rep['events']!=4 or rep['signals']!=2 or rep['approved']!=2 or rep['routed']!=4 or rep['filled']!=4 or rep['rejected']!=0
          or abs(float(rep['realized_pnl'])-(-620000.0))>0.01 or float(rep['unrealized_pnl'])!=0.0
          or snap['strategy_state']!='OVERNIGHT_INSURANCE_CLOSED' or snap['strategy_exit_reason']!='OPENING_MOVE_BELOW_1PCT_STOP_LOSS' or len(snap['open_lots'])!=0
          or len(snap['risk_audit_records'])!=2 or any(x['status']!='ALLOW_VIRTUAL_ONLY' for x in snap['risk_audit_records'])):
        raise RuntimeError(f'S9_STOP_LOSS_ASSERTION_FAILED:{label}')
    if not TRACE.is_file() or TRACE.stat().st_size==0: raise RuntimeError('S9_STOP_LOSS_TRACE_MISSING')
    result={'status':'PSB_PASS','validation_only':True,'scope_note':'Only the manifest-bound synthetic S9 below-1% STOP_LOSS branch; not KIS/REAL_VTS/Live validation.',
      'strategy_id':m['strategy_id'],'scenario_id':m['scenario_id'],'provenance':'SYNTHETIC','opening_move_ratio':'0.005',
      'opening_move_action':'STOP_LOSS','official_data_status':m['official_data_status'],'synthetic_contract_multiplier':100000,
      'synthetic_tradeable':True,'manifest_sha256':sha(MANIFEST),'dataset_sha256':sha(DATA/'20261106.jsonl'),
      'contract_profile_sha256':sha(CONTRACT),'risk_profile_sha256':sha(RISK),'fast':f,'detailed':d,
      'strategy_state':fs['strategy_state'],'strategy_exit_reason':fs['strategy_exit_reason'],'open_lot_count':len(fs['open_lots']),
      'risk_audit_records':list(fs['risk_audit_records']),'fast_detailed_equivalent':equivalent,
      'detailed_trace_path':TRACE.relative_to(ROOT).as_posix(),'detailed_trace_sha256':sha(TRACE),
      'synthetic_option_exit_bid':{'PUT':'2.0','CALL':'2.2'},'realized_pnl_krw':f['realized_pnl'],
      'fees_assumed_krw':0,'production_runtime_eligible':False,'kis_real_vts_live_orders_used':False,'real_account_used':False}
    rb=(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n').encode(); REPORT.write_bytes(rb)
    REPORT.with_suffix('.json.sha256').write_text(hashlib.sha256(rb).hexdigest()+f'  {REPORT.name}\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'opening_move_action':result['opening_move_action'],'events':f['events'],'signals':f['signals'],'fills':f['filled'],'realized_pnl_krw':f['realized_pnl'],'open_lots':result['open_lot_count'],'fast_detailed_equivalent':equivalent,'report':REPORT.relative_to(ROOT).as_posix(),'trace':TRACE.relative_to(ROOT).as_posix()},indent=2))
if __name__=='__main__': main()
