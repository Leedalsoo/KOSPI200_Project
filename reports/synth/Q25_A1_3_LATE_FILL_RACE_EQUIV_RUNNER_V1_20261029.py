from __future__ import annotations
import hashlib, json, sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from environments.high_speed.replay_trace import ReplayLogMode, ReplayTraceController, _trace_value
DATASET = ROOT / 'data/derived_scenario/p5_run_20261026_trend_up_seed20261026'
MANIFEST = DATASET / 'MANIFEST.json'
RUN_ID = 'Q25-A1-3-VALIDATION-ONLY-LATE-FILL-RACE-FAST-DETAILED-20261029'
TRACE = ROOT / 'reports/synth/Q25_A1_3_LATE_FILL_RACE_EQUIV_V1_DETAILED_20261029.jsonl'
SUMMARY = ROOT / 'reports/synth/Q25_A1_3_LATE_FILL_RACE_EQUIV_V1_20261029.json'
EXPECTED_MANIFEST_SHA = '47d6746bfd7abfea9d52016434ca06f097ca117e6724f96c522b58eb8e5590f5'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def input_snapshot(manifest):
    result = {}
    for item in manifest['output_files']:
        path = DATASET / item['path']
        result[item['path']] = {'bytes': path.stat().st_size, 'sha256': sha(path)} if path.is_file() else {'missing': True}
    return result
def state_view(state):
    return {'client_order_id': state.client_order_id, 'status': state.status, 'broker_order_id': state.broker_order_id, 'order_quantity': state.order_quantity, 'filled_quantity': state.filled_quantity, 'average_execution_price': str(state.average_execution_price) if state.average_execution_price is not None else None}
def run(mode, event):
    trace = ReplayTraceController(ReplayLogMode(mode), output_path=TRACE if mode == 'detailed' else None)
    captured = []
    emit = trace.emit
    def capture(event_type, *, run_id, event_sequence=None, timestamp=None, payload=None):
        row = {'event_type': event_type, 'run_id': run_id, 'event_sequence': event_sequence, 'timestamp': timestamp, 'payload': payload or {}}
        captured.append(row)
        emit(event_type, run_id=run_id, event_sequence=event_sequence, timestamp=timestamp, payload=payload)
    trace.emit = capture
    tick = event['tick']; t0 = datetime.fromisoformat(tick['timestamp']); px = Decimal(str(tick['ask_price']))
    fsm = OrderStateMachine(); commands = []; reports = []; transitions = []; rejections = []
    def record(event_type, seq, when, payload):
        trace.emit(event_type, run_id=RUN_ID, event_sequence=seq, timestamp=when.isoformat(), payload=payload)
    def transition(order_id, before, after, seq, when):
        row = {'client_order_id': order_id, 'before': state_view(before), 'after': state_view(after)}
        record('oms_state_transition', seq, when, row); transitions.append(row)
    command = BrokerOrderCommand(client_order_id='Q25-LATE-FILL-OLD-001', instrument_id=tick['synthetic_contract_id'], side='BUY', quantity=3, order_type='LIMIT', broker_symbol=tick['synthetic_contract_id'], asset_type='OPTION', requested_price=px, strategy_id='TRACK1_TAIL_DEFENSE', order_purpose='VALIDATION_ONLY_LATE_FILL_RACE', track_id='TRACK1_TAIL_DEFENSE', tag_id='VALIDATION_ONLY_LATE_FILL_RACE_FIXTURE', group_id='Q25-LATE-FILL-RACE-GROUP')
    before = fsm.apply_intent(command); fsm.register_broker_order_command(command)
    record('order_command', 0, t0, {'adapter':'validation_only_fixture', 'command':_trace_value(command)}); commands.append(_trace_value(command))
    ack = OrderAckEvent(client_order_id=command.client_order_id, accepted=True, broker_order_id='Q25-TEST-BROKER-LATE-001')
    after = fsm.apply_ack(ack); record('order_ack', 0, t0, _trace_value(ack)); transition(command.client_order_id, before, after, 0, t0)
    partial_time = t0 + timedelta(minutes=5)
    partial = ExecutionReport(client_order_id=command.client_order_id, broker_order_id='Q25-TEST-BROKER-LATE-001', execution_id='Q25-LATE-FILL-EXEC-001', status='PARTIALLY_FILLED', filled_quantity=1, remaining_quantity=2, execution_price=px, execution_timestamp=partial_time, fee=Decimal('0.01'), group_id='Q25-LATE-FILL-RACE-GROUP', leg_id='Q25-LATE-FILL-LEG')
    before = fsm.get(command.client_order_id)
    record('execution_report', 1, partial_time, {'adapter':'validation_only_fixture','classification':'accepted_partial_fill','report':_trace_value(partial)})
    after = fsm.apply_execution(partial)
    record('fill', 1, partial_time, {'client_order_id':partial.client_order_id,'execution_id':partial.execution_id,'filled_quantity':partial.filled_quantity,'remaining_quantity':partial.remaining_quantity,'execution_price':str(partial.execution_price)})
    transition(command.client_order_id, before, after, 1, partial_time); reports.append({'kind':'accepted_partial_fill','report':_trace_value(partial),'state_after':state_view(after)})
    cancel_time = t0 + timedelta(minutes=10)
    cancel = ExecutionReport(client_order_id=command.client_order_id, broker_order_id='Q25-TEST-BROKER-LATE-001', execution_id='Q25-LATE-FILL-CANCEL-001', status='CANCELLED', filled_quantity=0, remaining_quantity=2, execution_price=None, execution_timestamp=cancel_time, fee=None, group_id='Q25-LATE-FILL-RACE-GROUP', leg_id='Q25-LATE-FILL-LEG')
    before = fsm.get(command.client_order_id)
    record('cancel_report', 2, cancel_time, {'adapter':'validation_only_fixture','report':_trace_value(cancel)})
    after = fsm.apply_cancel(cancel)
    transition(command.client_order_id, before, after, 2, cancel_time); reports.append({'kind':'cancel_acknowledged','report':_trace_value(cancel),'state_after':state_view(after)})
    late_time = t0 + timedelta(minutes=12)
    late = ExecutionReport(client_order_id=command.client_order_id, broker_order_id='Q25-TEST-BROKER-LATE-001', execution_id='Q25-LATE-FILL-EXEC-LATE-002', status='PARTIALLY_FILLED', filled_quantity=1, remaining_quantity=1, execution_price=px + Decimal('0.05'), execution_timestamp=t0 + timedelta(minutes=9), fee=Decimal('0.01'), group_id='Q25-LATE-FILL-RACE-GROUP', leg_id='Q25-LATE-FILL-LEG')
    record('execution_report', 3, late_time, {'adapter':'validation_only_fixture','classification':'late_fill_report_received_after_cancel_ack','report':_trace_value(late)})
    try:
        fsm.apply_execution(late)
        rejected = False; error_code = None
    except OrderStateTransitionError as exc:
        rejected = True; error_code = str(exc)
    if rejected:
        row = {'client_order_id':late.client_order_id,'execution_id':late.execution_id,'accepted':False,'error_code':error_code,'state_after':state_view(fsm.get(command.client_order_id))}
        record('oms_transition_rejected', 3, late_time, row); rejections.append(row)
    else:
        row = {'client_order_id':late.client_order_id,'execution_id':late.execution_id,'accepted':True,'state_after':state_view(fsm.get(command.client_order_id))}
        record('oms_transition_applied', 3, late_time, row)
    reports.append({'kind':'late_fill_report_after_cancel_ack','report':_trace_value(late),'accepted_by_current_fsm':not rejected,'error_code':error_code,'state_after':state_view(fsm.get(command.client_order_id))})
    return {'mode':mode,'commands':commands,'reports':reports,'transitions':transitions,'rejections':rejections,'final_state':state_view(fsm.get(command.client_order_id)),'pending_ids':list(fsm.pending_client_order_ids('TRACK1_TAIL_DEFENSE')),'trace_status':trace.status,'trace_write_errors':list(trace.write_errors),'captured_events':captured}
def main():
    if TRACE.exists() or SUMMARY.exists(): raise FileExistsError('OUTPUT_ALREADY_EXISTS; preserve prior artifacts')
    mb = MANIFEST.read_bytes(); manifest_sha = hashlib.sha256(mb).hexdigest()
    if manifest_sha != EXPECTED_MANIFEST_SHA: raise RuntimeError('MANIFEST_SHA_MISMATCH:' + manifest_sha)
    manifest = json.loads(mb)
    if manifest.get('provenance') != 'DERIVED_SCENARIO' or manifest.get('synthetic') is not True or manifest.get('validation_only') is not True or manifest.get('production_runtime_eligible') is not False: raise RuntimeError('DATASET_GUARDRAIL_MISMATCH')
    before = input_snapshot(manifest)
    if len(before) != 63 or any('missing' in value for value in before.values()): raise RuntimeError('MANIFEST_INPUT_COVERAGE_INVALID')
    with (DATASET / '20261008.jsonl').open(encoding='utf-8') as handle: event = json.loads(next(handle))
    fast = run('fast', event); detailed = run('detailed', event)
    after = input_snapshot(manifest)
    if detailed['trace_status'] != 'CONNECTED' or detailed['trace_write_errors']: raise RuntimeError('DETAILED_TRACE_WRITE_FAILED')
    rows = [json.loads(line) for line in TRACE.read_text(encoding='utf-8').splitlines()]
    persisted = [{key: row[key] for key in ('event_type','run_id','event_sequence','timestamp','payload')} for row in rows]
    flags = {
      'same_order_commands': fast['commands'] == detailed['commands'],
      'same_execution_cancel_and_late_reports': fast['reports'] == detailed['reports'],
      'same_applied_state_transitions': fast['transitions'] == detailed['transitions'],
      'same_rejected_late_fill_decision': fast['rejections'] == detailed['rejections'],
      'same_final_oms_state': fast['final_state'] == detailed['final_state'],
      'same_pending_order_ids': fast['pending_ids'] == detailed['pending_ids'],
      'fast_detailed_event_semantics_equal': fast['captured_events'] == detailed['captured_events'],
      'detailed_capture_matches_persisted_trace': detailed['captured_events'] == persisted,
      'trace_sequence_contiguous': [row['trace_sequence'] for row in rows] == list(range(len(rows))),
      'late_report_not_counted_as_fill_event': sum(row['event_type'] == 'fill' for row in rows) == 1 and sum(row['event_type'] == 'oms_transition_rejected' for row in rows) == 1,
      'trace_write_errors_zero': detailed['trace_status'] == 'CONNECTED' and not detailed['trace_write_errors'],
      'manifest_63_inputs_unchanged': len(before) == 63 and before == after,
    }
    expected_state = fast['final_state']['status'] == 'CANCELLED' and fast['final_state']['filled_quantity'] == 1 and fast['rejections'] and fast['rejections'][-1]['error_code'] == 'EXECUTION_BEFORE_ACK' and fast['pending_ids'] == []
    summary = {'status':'PASS' if all(flags.values()) and expected_state else 'FAIL','scope':'validation-only fast/detailed equivalence for a deterministic late ExecutionReport received after cancel acknowledgement; actual OrderStateMachine and ReplayTraceController used, test-only reports only','run_id':RUN_ID,'dataset':manifest['dataset'],'seed':manifest['seed'],'manifest_sha256':manifest_sha,'provenance':manifest['provenance'],'synthetic':manifest['synthetic'],'validation_only':manifest['validation_only'],'production_runtime_eligible':manifest['production_runtime_eligible'],'input_files_checked':len(before),'source_event':{'path':'20261008.jsonl','event_id':event.get('event_id'),'timestamp':event['tick']['timestamp'],'synthetic_contract_id':event['tick']['synthetic_contract_id'],'identity_status':event.get('identity_status')},'scenario':{'order_quantity':3,'first_partial_fill':1,'cancel_acknowledged_after_partial_fill':True,'late_report_arrival_after_cancel_minutes':12,'late_report_execution_timestamp_minutes_after_start':9,'late_report_incremental_quantity':1,'current_fsm_late_report_result':'rejected','current_fsm_error_code':fast['rejections'][-1]['error_code'] if fast['rejections'] else None,'final_order_status':fast['final_state']['status'],'final_filled_quantity':fast['final_state']['filled_quantity'],'accepted_fill_events':sum(row['event_type']=='fill' for row in rows),'pending_order_ids':fast['pending_ids']},'fast':{key:value for key,value in fast.items() if key != 'captured_events'},'detailed':{key:value for key,value in detailed.items() if key != 'captured_events'},'comparison_flags':flags,'comparison_flag_count':len(flags),'comparison_flags_true':sum(flags.values()),'trace':{'path':str(TRACE.relative_to(ROOT)),'records':len(rows),'bytes':TRACE.stat().st_size,'sha256':sha(TRACE),'event_types':[row['event_type'] for row in rows]},'input_unchanged':before == after,'input_files_before_after_match':sum(before[key] == after[key] for key in before),'correctness_boundary':'Equivalence PASS only establishes both modes match current FSM behavior. Whether a late report represents a fill executed before cancellation acknowledgement and must be reconciled into positions is NOT PROVEN; current FSM rejects it and no position-store reconciliation was exercised.','limitations':['Deterministic test-only reports; no real broker or KIS API contacted.','No production runtime, broker order/fill correlation recovery, position store, PnL, or account reconciliation path tested.','Source event identity is fixture-only and BLOCKED_IDENTITY_OWNER_UNRESOLVED; no authoritative contract identity is claimed.','One late report after cancel acknowledgement only; duplicate reports, report permutations, restart recovery, concurrent multiple orders, and full 53,550-event dataset equivalence not tested.']}
    SUMMARY.write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'status':summary['status'],'run_id':RUN_ID,'manifest_sha256':manifest_sha,'input_files_checked':len(before),'scenario':summary['scenario'],'comparison_flags':flags,'trace_path':str(TRACE.relative_to(ROOT)),'trace_sha256':sha(TRACE),'trace_records':len(rows),'summary_path':str(SUMMARY.relative_to(ROOT)),'summary_sha256':sha(SUMMARY),'input_unchanged':before == after,'correctness_boundary':summary['correctness_boundary']},ensure_ascii=False,indent=2))
    if summary['status'] != 'PASS': raise SystemExit(1)
if __name__ == '__main__': main()
