from __future__ import annotations
import hashlib, json, sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent
from core.oms.oms_fsm import OrderStateMachine
from environments.high_speed.replay_trace import ReplayLogMode, ReplayTraceController, _trace_value
DATASET=ROOT/'data/derived_scenario/p5_run_20261026_trend_up_seed20261026'
MANIFEST=DATASET/'MANIFEST.json'
RUN_ID='Q25-A1-3-VALIDATION-ONLY-CANCEL-REPLACE-FAST-DETAILED-20261029'
TRACE=ROOT/'reports/synth/Q25_A1_3_CANCEL_REPLACE_EQUIV_V1_DETAILED_20261029.jsonl'
SUMMARY=ROOT/'reports/synth/Q25_A1_3_CANCEL_REPLACE_EQUIV_V1_20261029.json'
EXPECTED_MANIFEST_SHA='47d6746bfd7abfea9d52016434ca06f097ca117e6724f96c522b58eb8e5590f5'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def input_snapshot(m):
 out={}
 for x in m['output_files']:
  p=DATASET/x['path']; out[x['path']]={'bytes':p.stat().st_size,'sha256':sha(p)} if p.is_file() else {'missing':True}
 return out
def state_view(s):
 return {'client_order_id':s.client_order_id,'status':s.status,'broker_order_id':s.broker_order_id,'order_quantity':s.order_quantity,'filled_quantity':s.filled_quantity,'average_execution_price':str(s.average_execution_price) if s.average_execution_price is not None else None}
def run(mode, event):
 trace=ReplayTraceController(ReplayLogMode(mode),output_path=TRACE if mode=='detailed' else None)
 captured=[]; emit=trace.emit
 def capture(event_type,*,run_id,event_sequence=None,timestamp=None,payload=None):
  captured.append({'event_type':event_type,'run_id':run_id,'event_sequence':event_sequence,'timestamp':timestamp,'payload':payload or {}})
  emit(event_type,run_id=run_id,event_sequence=event_sequence,timestamp=timestamp,payload=payload)
 trace.emit=capture
 tick=event['tick']; t0=datetime.fromisoformat(tick['timestamp']); px=Decimal(str(tick['ask_price']))
 fsm=OrderStateMachine(); timeline=[]; commands=[]; reports=[]
 def record_transition(order_id,before,after,seq,when):
  payload={'client_order_id':order_id,'before':state_view(before),'after':state_view(after)}
  trace.emit('oms_state_transition',run_id=RUN_ID,event_sequence=seq,timestamp=when.isoformat(),payload=payload)
  timeline.append({'event':'oms_state_transition','client_order_id':order_id,'before':state_view(before),'after':state_view(after)})
 def register(command,broker_id,seq,when):
  before=fsm.apply_intent(command); fsm.register_broker_order_command(command)
  trace.emit('order_command',run_id=RUN_ID,event_sequence=seq,timestamp=when.isoformat(),payload={'adapter':'validation_only_fixture','command':_trace_value(command)})
  ack=OrderAckEvent(client_order_id=command.client_order_id,accepted=True,broker_order_id=broker_id)
  acked=fsm.apply_ack(ack)
  trace.emit('order_ack',run_id=RUN_ID,event_sequence=seq,timestamp=when.isoformat(),payload=_trace_value(ack))
  record_transition(command.client_order_id,before,acked,seq,when)
  commands.append(_trace_value(command))
  return acked
 def report_event(report,seq,when,kind):
  trace.emit('execution_report' if kind=='fill' else 'cancel_report',run_id=RUN_ID,event_sequence=seq,timestamp=when.isoformat(),payload={'adapter':'validation_only_fixture','report':_trace_value(report)})
  if kind=='fill':
   trace.emit('fill',run_id=RUN_ID,event_sequence=seq,timestamp=when.isoformat(),payload={'client_order_id':report.client_order_id,'execution_id':report.execution_id,'status':report.status,'filled_quantity':report.filled_quantity,'remaining_quantity':report.remaining_quantity,'execution_price':str(report.execution_price),'execution_timestamp':report.execution_timestamp.isoformat() if report.execution_timestamp else None,'fee':str(report.fee) if report.fee is not None else None,'group_id':report.group_id,'leg_id':report.leg_id})
  before=fsm.get(report.client_order_id)
  after=fsm.apply_execution(report) if kind=='fill' else fsm.apply_cancel(report)
  record_transition(report.client_order_id,before,after,seq,when)
  reports.append({'kind':kind,'report':_trace_value(report),'state_after':state_view(after)})
  return after
 old=BrokerOrderCommand(client_order_id='Q25-CANCEL-OLD-001',instrument_id=tick['synthetic_contract_id'],side='BUY',quantity=3,order_type='LIMIT',broker_symbol=tick['synthetic_contract_id'],asset_type='OPTION',requested_price=px,strategy_id='TRACK1_TAIL_DEFENSE',order_purpose='VALIDATION_ONLY_CANCEL_REPLACE',track_id='TRACK1_TAIL_DEFENSE',tag_id='VALIDATION_ONLY_CANCEL_REPLACE_FIXTURE',group_id='Q25-CANCEL-REPLACE-GROUP')
 register(old,'Q25-TEST-BROKER-OLD',0,t0)
 partial_time=t0+timedelta(minutes=5)
 partial=ExecutionReport(client_order_id=old.client_order_id,broker_order_id='Q25-TEST-BROKER-OLD',execution_id='Q25-CANCEL-OLD-EXEC-001',status='PARTIALLY_FILLED',filled_quantity=1,remaining_quantity=2,execution_price=px,execution_timestamp=partial_time,fee=Decimal('0.01'),group_id='Q25-CANCEL-REPLACE-GROUP',leg_id='Q25-CANCEL-OLD-LEG')
 report_event(partial,1,partial_time,'fill')
 cancel_time=t0+timedelta(minutes=10)
 cancel=ExecutionReport(client_order_id=old.client_order_id,broker_order_id='Q25-TEST-BROKER-OLD',execution_id='Q25-CANCEL-OLD-CANCEL-001',status='CANCELLED',filled_quantity=0,remaining_quantity=2,execution_price=None,execution_timestamp=cancel_time,fee=None,group_id='Q25-CANCEL-REPLACE-GROUP',leg_id='Q25-CANCEL-OLD-LEG')
 old_final=report_event(cancel,2,cancel_time,'cancel')
 replacement=BrokerOrderCommand(client_order_id='Q25-CANCEL-NEW-001',instrument_id=tick['synthetic_contract_id'],side='BUY',quantity=2,order_type='LIMIT',broker_symbol=tick['synthetic_contract_id'],asset_type='OPTION',requested_price=px+Decimal('0.05'),strategy_id='TRACK1_TAIL_DEFENSE',order_purpose='VALIDATION_ONLY_CANCEL_REPLACEMENT',track_id='TRACK1_TAIL_DEFENSE',tag_id='VALIDATION_ONLY_REPLACEMENT_FIXTURE',group_id='Q25-CANCEL-REPLACE-GROUP')
 register(replacement,'Q25-TEST-BROKER-NEW',3,cancel_time+timedelta(minutes=1))
 fill_time=t0+timedelta(minutes=15)
 replacement_fill=ExecutionReport(client_order_id=replacement.client_order_id,broker_order_id='Q25-TEST-BROKER-NEW',execution_id='Q25-CANCEL-NEW-EXEC-001',status='FILLED',filled_quantity=2,remaining_quantity=0,execution_price=px+Decimal('0.05'),execution_timestamp=fill_time,fee=Decimal('0.02'),group_id='Q25-CANCEL-REPLACE-GROUP',leg_id='Q25-CANCEL-NEW-LEG')
 replacement_final=report_event(replacement_fill,4,fill_time,'fill')
 return {'mode':mode,'commands':commands,'reports':reports,'timeline':timeline,'final_states':{'old':state_view(old_final),'replacement':state_view(replacement_final)},'trace_status':trace.status,'trace_write_errors':list(trace.write_errors),'captured_events':captured}
def main():
 if TRACE.exists() or SUMMARY.exists(): raise FileExistsError('OUTPUT_ALREADY_EXISTS; preserving prior artifacts')
 mb=MANIFEST.read_bytes(); mh=hashlib.sha256(mb).hexdigest()
 if mh!=EXPECTED_MANIFEST_SHA: raise RuntimeError('MANIFEST_SHA_MISMATCH:'+mh)
 m=json.loads(mb)
 if m.get('provenance')!='DERIVED_SCENARIO' or m.get('synthetic') is not True or m.get('validation_only') is not True or m.get('production_runtime_eligible') is not False: raise RuntimeError('DATASET_GUARDRAIL_MISMATCH')
 before=input_snapshot(m)
 if len(before)!=63 or any('missing' in v for v in before.values()): raise RuntimeError('MANIFEST_INPUT_COVERAGE_INVALID')
 event=json.loads((DATASET/'20261008.jsonl').open(encoding='utf-8').readline())
 fast=run('fast',event); detailed=run('detailed',event)
 if detailed['trace_status']!='CONNECTED' or detailed['trace_write_errors']: raise RuntimeError('DETAILED_TRACE_WRITE_FAILED')
 after=input_snapshot(m); rows=[json.loads(x) for x in TRACE.read_text(encoding='utf-8').splitlines()]
 persisted=[{k:r[k] for k in ('event_type','run_id','event_sequence','timestamp','payload')} for r in rows]
 flags={'same_order_commands':fast['commands']==detailed['commands'],'same_execution_and_cancel_reports':fast['reports']==detailed['reports'],'same_state_transition_timeline':fast['timeline']==detailed['timeline'],'same_final_states':fast['final_states']==detailed['final_states'],'fast_detailed_event_semantics_equal':fast['captured_events']==detailed['captured_events'],'detailed_capture_matches_persisted_trace':detailed['captured_events']==persisted,'trace_sequence_contiguous':[r['trace_sequence'] for r in rows]==list(range(len(rows))),'one_cancel_event':sum(r['event_type']=='cancel_report' for r in rows)==1,'two_fill_events':sum(r['event_type']=='fill' for r in rows)==2,'trace_write_errors_zero':detailed['trace_status']=='CONNECTED' and not detailed['trace_write_errors'],'input_manifest_files_63_unchanged':len(before)==63 and before==after}
 final_ok=fast['final_states']==detailed['final_states'] and fast['final_states']['old']['status']=='CANCELLED' and fast['final_states']['old']['filled_quantity']==1 and fast['final_states']['replacement']['status']=='FILLED' and fast['final_states']['replacement']['filled_quantity']==2
 summary={'status':'PASS' if all(flags.values()) and final_ok else 'FAIL','scope':'validation-only cancel after partial fill + separate replacement order fast/detailed equivalence using actual OrderStateMachine and deterministic test-only reports; no native amend API or production replacement orchestrator claimed','run_id':RUN_ID,'dataset':m['dataset'],'seed':m['seed'],'manifest_sha256':mh,'provenance':m['provenance'],'synthetic':m['synthetic'],'validation_only':m['validation_only'],'production_runtime_eligible':m['production_runtime_eligible'],'input_files_checked':len(before),'source_event':{'path':'20261008.jsonl','event_id':event['event_id'],'timestamp':event['tick']['timestamp'],'synthetic_contract_id':event['tick']['synthetic_contract_id'],'identity_status':event['identity_status']},'scenario':{'old_order_quantity':3,'old_order_partial_fill':1,'cancelled_old_order_filled_quantity':1,'old_order_status':'CANCELLED','replacement_quantity':2,'replacement_requested_price':str(Decimal(str(event['tick']['ask_price']))+Decimal('0.05')),'replacement_final_status':'FILLED','replacement_filled_quantity':2},'fast':{k:v for k,v in fast.items() if k!='captured_events'},'detailed':{k:v for k,v in detailed.items() if k!='captured_events'},'comparison_flags':flags,'comparison_flag_count':len(flags),'comparison_flags_true':sum(flags.values()),'trace':{'path':str(TRACE.relative_to(ROOT)),'records':len(rows),'bytes':TRACE.stat().st_size,'sha256':sha(TRACE),'event_types':[r['event_type'] for r in rows]},'input_unchanged':before==after,'input_files_before_after_match':sum(before[k]==after[k] for k in before),'limitations':['Test-only reports; no real broker cancel/replace acknowledgement or observed execution.','Current OrderStateMachine supports apply_cancel but no native amend/replace method; replacement is modeled as a distinct order after cancellation.','No late-fill race, multi-order concurrency, position store/PnL, full Virtual runtime, production call path or full-dataset equivalence was tested.','Source event identity is BLOCKED_IDENTITY_OWNER_UNRESOLVED; fixture identity only.']}
 SUMMARY.write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 print(json.dumps({'status':summary['status'],'run_id':RUN_ID,'manifest_sha256':mh,'input_files_checked':len(before),'scenario':summary['scenario'],'comparison_flags':flags,'trace_path':str(TRACE.relative_to(ROOT)),'trace_sha256':summary['trace']['sha256'],'trace_records':len(rows),'summary_path':str(SUMMARY.relative_to(ROOT)),'summary_sha256':sha(SUMMARY),'input_unchanged':before==after},ensure_ascii=False,indent=2))
 if summary['status']!='PASS': raise SystemExit(1)
if __name__=='__main__': main()
