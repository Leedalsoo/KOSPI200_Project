from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from environments.high_speed.replay_trace import ReplayLogMode
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner
from environments.high_speed.validation_only_s9_restart import write_restart_snapshot
DATA=ROOT/'data/derived_scenario/q25_s9_independent_overnight_stop_loss_20261108'
MANIFEST=DATA/'manifest.json'
CONTRACT=ROOT/'config/validation_only/track9_independent_synthetic_contract_profile.json'
RISK=ROOT/'config/validation_only/q25_s9_independent_overnight_20261108/risk_profile.json'
SNAPSHOT=ROOT/'reports/synth/S9_INDEPENDENT_ATM_OVERNIGHT_RESTART_SNAPSHOT_V6_20261108.json'
CAPTURE_TRACE=ROOT/'reports/synth/S9_INDEPENDENT_ATM_OVERNIGHT_RESTART_CAPTURE_V6_20261108.jsonl'
RESUME_TRACE=ROOT/'reports/synth/S9_INDEPENDENT_ATM_OVERNIGHT_RESTART_RESUME_V6_20261108.jsonl'
REPORT=ROOT/'reports/synth/S9_INDEPENDENT_ATM_OVERNIGHT_PROCESS_RESTART_E2E_V6_20261108.json'
RUN_ID='S9-STOP-LOSS-PROCESS-RESTART-20261108'

def new_runner(*, phase, restore=False):
    return HighSpeedVirtualRuntimeReplayRunner(
      DATA,run_id=RUN_ID,strategy_keys=(('track9_event_overnight_insurance','3.0'),),
      validation_only_synthetic=True,validation_only_synthetic_manifest=MANIFEST,
      validation_only_s9_contract_profile=CONTRACT,validation_only_s9_risk_profile=RISK,
      validation_only_s9_restart_snapshot_path=SNAPSHOT if restore else None,
      log_mode=ReplayLogMode.DETAILED,
      trace_output=CAPTURE_TRACE if phase=='capture' else RESUME_TRACE)

def capture():
    runner=new_runner(phase='capture')
    report=runner.run(max_events=2)
    snap=runner.s9_runtime_snapshot
    capture_checks={'events':report.events,'signals':report.signals,'filled':report.filled,
      'open_lots':len(snap['open_lots']),'account_positions':len(snap.get('account_positions',{})),
      'strategy_state':snap['strategy_state'],'risk_audits':len(snap['risk_audit_records']),
      'fee_records':len(snap['fee_records']),'execution_sequence':snap.get('execution_sequence'),'position_groups':len(snap.get('position_groups',{})),'execution_reports':len(snap.get('execution_reports',()))}
    if (report.events!=2 or report.signals!=1 or report.filled!=2 or len(snap['open_lots'])!=2
        or len(snap['account_positions'])!=2 or snap['strategy_state']!='OVERNIGHT_INSURANCE_ACTIVE'
        or len(snap['risk_audit_records'])!=1 or len(snap['fee_records'])!=2
        or len(snap.get('position_groups',{}))!=1 or len(snap.get('execution_reports',()))!=2):
        raise RuntimeError('S9_RESTART_CAPTURE_ASSERTION_FAILED:'+json.dumps(capture_checks,default=str))
    saved=write_restart_snapshot(SNAPSHOT,run_id=RUN_ID,adapter=runner.s9_validation_runtime_adapter,
                                 runtime_snapshot=snap,process_id=os.getpid())
    result={'phase':'CAPTURE','process_id':os.getpid(),'events':report.events,'signals':report.signals,
      'filled':report.filled,'strategy_state':snap['strategy_state'],'open_lots':len(snap['open_lots']),
      'account_positions':len(snap['account_positions']),'fee_records':len(snap['fee_records']),
      'risk_audits':len(snap['risk_audit_records']),'position_groups':len(snap.get('position_groups',{})),'execution_reports':len(snap.get('execution_reports',())),'snapshot':saved,'trace':str(CAPTURE_TRACE.relative_to(ROOT))}
    print(json.dumps(result,ensure_ascii=False,default=str))

def resume():
    runner=new_runner(phase='resume',restore=True)
    report=runner.run(max_events=4)
    snap=runner.s9_runtime_snapshot
    if (report.events!=4 or report.signals!=1 or report.approved!=1 or report.routed!=2 or report.filled!=2
        or report.rejected!=0 or abs(float(report.realized_pnl)-(-620000.0))>0.01
        or float(report.unrealized_pnl)!=0.0 or snap['strategy_state']!='OVERNIGHT_INSURANCE_CLOSED'
        or snap['strategy_exit_reason']!='OPENING_MOVE_BELOW_1PCT_STOP_LOSS'
        or len(snap['open_lots'])!=0 or len(snap['account_positions'])!=0
        or len(snap['risk_audit_records'])!=2 or len(snap['fee_records'])!=4
        or len(snap.get('position_groups',{}))!=1 or len(snap.get('position_group_snapshots',{}))!=1
        or len(snap.get('execution_reports',()))!=4
        or runner.s9_restart_restore_status.get('restored_position_groups')!=1
        or runner.s9_restart_restore_status.get('restored_group_snapshots')!=1
        or runner.s9_restart_restore_status.get('restored_execution_reports')!=2
        or runner.s9_restart_restore_status.get('restored_ledger_transactions')!=2):
        raise RuntimeError('S9_RESTART_RESUME_ASSERTION_FAILED')
    if not runner.s9_restart_restore_status or runner.s9_restart_restore_status.get('status')!='RESTORED':
        raise RuntimeError('S9_RESTART_RESTORE_STATUS_MISSING')
    result={'phase':'RESUME','process_id':os.getpid(),'events':report.events,'signals':report.signals,
      'approved':report.approved,'routed':report.routed,'filled':report.filled,'rejected':report.rejected,
      'strategy_state':snap['strategy_state'],'strategy_exit_reason':snap['strategy_exit_reason'],
      'open_lots':len(snap['open_lots']),'account_positions':len(snap['account_positions']),
      'fee_records':len(snap['fee_records']),'risk_audits':len(snap['risk_audit_records']),'position_groups':len(snap.get('position_groups',{})),'execution_reports':len(snap.get('execution_reports',())),
      'realized_pnl_krw':report.realized_pnl,'unrealized_pnl_krw':report.unrealized_pnl,
      'restore':runner.s9_restart_restore_status,'execution_ids':list(report.execution_ids),
      'trace':str(RESUME_TRACE.relative_to(ROOT))}
    print(json.dumps(result,ensure_ascii=False,default=str))

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--phase',choices=('capture','resume','orchestrate'),default='orchestrate')
    phase=parser.parse_args().phase
    if phase=='capture': capture(); return
    if phase=='resume': resume(); return
    for path in (SNAPSHOT,SNAPSHOT.with_suffix(SNAPSHOT.suffix+'.sha256'),CAPTURE_TRACE,RESUME_TRACE,REPORT,REPORT.with_suffix('.json.sha256')):
        if path.exists(): raise RuntimeError(f'REFUSE_OVERWRITE:{path.relative_to(ROOT)}')
    first=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--phase','capture'],cwd=ROOT,text=True,capture_output=True)
    if first.returncode: raise RuntimeError('S9_RESTART_CAPTURE_PROCESS_FAILED:'+first.stderr[-3000:])
    second=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--phase','resume'],cwd=ROOT,text=True,capture_output=True)
    if second.returncode: raise RuntimeError('S9_RESTART_RESUME_PROCESS_FAILED:'+second.stderr[-4000:])
    a=json.loads(first.stdout.strip().splitlines()[-1]); b=json.loads(second.stdout.strip().splitlines()[-1])
    if a['process_id']==b['process_id']: raise RuntimeError('S9_RESTART_DID_NOT_USE_DISTINCT_PROCESSES')
    manifest=json.loads(MANIFEST.read_text(encoding='utf-8'))
    def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
    result={'status':'PSB_PASS','validation_only':True,
      'scope_note':'Manifest-bound synthetic S9 STOP_LOSS Virtual execution resumed in a distinct Python process; not KIS/REAL_VTS/Live validation.',
      'strategy_id':'track9_event_overnight_insurance','scenario_id':manifest['scenario_id'],
      'provenance':'SYNTHETIC','run_id':RUN_ID,'same_logical_run_id_across_restart':True,
      'distinct_processes':True,'capture':a,'resume':b,'combined_events':a['events']+b['events'],
      'combined_signals':a['signals']+b['signals'],'combined_fills':a['filled']+b['filled'],
      'final_strategy_state':b['strategy_state'],'final_open_lots':b['open_lots'],
      'final_account_positions':b['account_positions'],'realized_pnl_krw':b['realized_pnl_krw'],
      'official_data_status':manifest['official_data_status'],'manifest_sha256':digest(MANIFEST),
      'dataset_sha256':digest(DATA/'20261106.jsonl'),'snapshot_sha256':digest(SNAPSHOT),
      'capture_trace_sha256':digest(CAPTURE_TRACE),'resume_trace_sha256':digest(RESUME_TRACE),
      'production_runtime_eligible':False,'kis_real_vts_live_orders_used':False,'real_account_used':False}
    encoded=(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n').encode(); REPORT.write_bytes(encoded)
    REPORT.with_suffix('.json.sha256').write_text(hashlib.sha256(encoded).hexdigest()+f'  {REPORT.name}\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'distinct_processes':True,'combined_events':result['combined_events'],
      'combined_signals':result['combined_signals'],'combined_fills':result['combined_fills'],
      'restored_open_lots':a['open_lots'],'final_open_lots':b['open_lots'],
      'realized_pnl_krw':b['realized_pnl_krw'],'execution_ids':b['execution_ids'],'report':str(REPORT.relative_to(ROOT))},indent=2))
if __name__=='__main__': main()
