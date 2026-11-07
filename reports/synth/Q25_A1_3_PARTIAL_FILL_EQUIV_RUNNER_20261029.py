from __future__ import annotations
import hashlib, json, sys
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent
from core.oms.oms_fsm import OrderStateMachine
from environments.high_speed.replay_trace import ReplayLogMode, ReplayTraceController

DATASET = ROOT / 'data/derived_scenario/p5_run_20261026_trend_up_seed20261026'
MANIFEST = DATASET / 'MANIFEST.json'
RUN_ID = 'Q25-A1-3-VALIDATION-ONLY-MULTI-STAGE-PARTIAL-FILL-FAST-DETAILED-20261029'
TRACE = ROOT / 'reports/synth/Q25_A1_3_PARTIAL_FILL_EQUIV_DETAILED_20261029.jsonl'
SUMMARY = ROOT / 'reports/synth/Q25_A1_3_PARTIAL_FILL_EQUIV_20261029.json'
EXPECTED_MANIFEST_SHA = '47d6746bfd7abfea9d52016434ca06f097ca117e6724f96c522b58eb8e5590f5'


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def input_snapshot(manifest: dict) -> dict:
    result = {}
    for item in manifest['output_files']:
        p = DATASET / item['path']
        if not p.is_file():
            result[item['path']] = {'missing': True}
        else:
            result[item['path']] = {'bytes': p.stat().st_size, 'sha256': sha(p)}
    return result


def state_view(state) -> dict:
    return {
        'client_order_id': state.client_order_id,
        'status': state.status,
        'broker_order_id': state.broker_order_id,
        'order_quantity': state.order_quantity,
        'filled_quantity': state.filled_quantity,
        'average_execution_price': str(state.average_execution_price) if state.average_execution_price is not None else None,
    }


def run(mode: str, base_event: dict) -> dict:
    output = TRACE if mode == 'detailed' else None
    trace = ReplayTraceController(ReplayLogMode(mode), output_path=output)
    captured = []
    original_emit = trace.emit
    def capture_emit(event_type, *, run_id, event_sequence=None, timestamp=None, payload=None):
        captured.append({'event_type': event_type, 'run_id': run_id, 'event_sequence': event_sequence,
                         'timestamp': timestamp, 'payload': payload or {}})
        original_emit(event_type, run_id=run_id, event_sequence=event_sequence, timestamp=timestamp, payload=payload)
    trace.emit = capture_emit

    tick = base_event['tick']
    base_time = datetime.fromisoformat(tick['timestamp'])
    base_price = Decimal(str(tick['ask_price']))
    command = BrokerOrderCommand(
        client_order_id='Q25-PARTIAL-ORDER-001',
        instrument_id=tick['synthetic_contract_id'],
        side='BUY', quantity=5, order_type='LIMIT',
        broker_symbol=tick['synthetic_contract_id'], asset_type='OPTION',
        requested_price=base_price, strategy_id='TRACK1_TAIL_DEFENSE',
        order_purpose='VALIDATION_ONLY_MULTI_STAGE_PARTIAL_FILL',
        track_id='TRACK1_TAIL_DEFENSE', tag_id='VALIDATION_ONLY_PARTIAL_FILL_FIXTURE',
    )
    fsm = OrderStateMachine()
    submitted = fsm.apply_intent(command)
    fsm.register_broker_order_command(command)
    trace.emit('order_command', run_id=RUN_ID, event_sequence=0, timestamp=base_time.isoformat(),
               payload={'adapter':'validation_only_fixture','command':asdict(command)})
    before_ack = state_view(submitted)
    ack = OrderAckEvent(client_order_id=command.client_order_id, accepted=True, broker_order_id='Q25-TEST-BROKER-001')
    acked = fsm.apply_ack(ack)
    trace.emit('order_ack', run_id=RUN_ID, event_sequence=0, timestamp=base_time.isoformat(), payload=asdict(ack))
    trace.emit('oms_state_transition', run_id=RUN_ID, event_sequence=0, timestamp=base_time.isoformat(),
               payload={'before':before_ack,'after':state_view(acked)})

    quantities = [1, 2, 2]
    price_steps = [Decimal('0.00'), Decimal('0.05'), Decimal('0.10')]
    cumulative = 0
    states = [state_view(acked)]
    reports = []
    for i, qty in enumerate(quantities, start=1):
        cumulative += qty
        remaining = command.quantity - cumulative
        status = 'FILLED' if remaining == 0 else 'PARTIALLY_FILLED'
        event_time = base_time + timedelta(minutes=5*i)
        price = base_price + price_steps[i-1]
        report = ExecutionReport(
            client_order_id=command.client_order_id, broker_order_id='Q25-TEST-BROKER-001',
            execution_id=f'Q25-PARTIAL-EXEC-{i:03d}', status=status,
            filled_quantity=qty, remaining_quantity=remaining, execution_price=price,
            execution_timestamp=event_time, fee=Decimal('0.01'),
            rejected_reason=None, group_id='Q25-PARTIAL-GROUP-001', leg_id='Q25-PARTIAL-LEG-001',
        )
        before = fsm.get(command.client_order_id)
        trace.emit('execution_report', run_id=RUN_ID, event_sequence=i, timestamp=event_time.isoformat(),
                   payload={'adapter':'validation_only_fixture','report':asdict(report)})
        trace.emit('fill', run_id=RUN_ID, event_sequence=i, timestamp=event_time.isoformat(), payload={
            'client_order_id':report.client_order_id,'execution_id':report.execution_id,'status':report.status,
            'filled_quantity':report.filled_quantity,'remaining_quantity':report.remaining_quantity,
            'execution_price':str(report.execution_price),'execution_timestamp':report.execution_timestamp.isoformat(),
            'fee':str(report.fee),'group_id':report.group_id,'leg_id':report.leg_id,
        })
        after = fsm.apply_execution(report)
        trace.emit('oms_state_transition', run_id=RUN_ID, event_sequence=i, timestamp=event_time.isoformat(),
                   payload={'before':state_view(before),'after':state_view(after)})
        reports.append({'execution_id':report.execution_id,'status':report.status,'incremental_quantity':qty,
                        'cumulative_quantity':after.filled_quantity,'remaining_quantity':after.order_quantity-after.filled_quantity,
                        'execution_price':str(price),'average_execution_price':str(after.average_execution_price),
                        'timestamp':event_time.isoformat()})
        states.append(state_view(after))
    return {'mode':mode,'command':asdict(command),'ack':asdict(ack),'reports':reports,'states':states,
            'final_state':state_view(fsm.get(command.client_order_id)),'captured_events':captured,
            'trace_status':trace.status,'trace_write_errors':list(trace.write_errors)}


def main():
    if TRACE.exists() or SUMMARY.exists():
        raise FileExistsError('OUTPUT_ALREADY_EXISTS; preserving prior artifacts')
    manifest_bytes = MANIFEST.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_sha != EXPECTED_MANIFEST_SHA:
        raise RuntimeError(f'MANIFEST_SHA_MISMATCH:{manifest_sha}')
    manifest = json.loads(manifest_bytes)
    if manifest.get('provenance') != 'DERIVED_SCENARIO' or manifest.get('synthetic') is not True or manifest.get('validation_only') is not True or manifest.get('production_runtime_eligible') is not False:
        raise RuntimeError('DATASET_GUARDRAIL_MISMATCH')
    before = input_snapshot(manifest)
    if len(before) != 63 or any('missing' in x for x in before.values()):
        raise RuntimeError('MANIFEST_INPUT_COVERAGE_INVALID')
    first_line = (DATASET / '20261008.jsonl').open(encoding='utf-8').readline()
    base_event = json.loads(first_line)
    fast = run('fast', base_event)
    detailed = run('detailed', base_event)
    after = input_snapshot(manifest)
    input_unchanged = before == after
    trace_rows = [json.loads(line) for line in TRACE.read_text(encoding='utf-8').splitlines()]
    detailed_semantics = [{k:row[k] for k in ('event_type','run_id','event_sequence','timestamp','payload')} for row in trace_rows]
    fast_semantics = fast['captured_events']
    detailed_capture = detailed['captured_events']
    flags = {
      'same_command': fast['command'] == detailed['command'],
      'same_ack': fast['ack'] == detailed['ack'],
      'same_incremental_fill_reports': fast['reports'] == detailed['reports'],
      'same_oms_state_sequence': fast['states'] == detailed['states'],
      'same_final_state': fast['final_state'] == detailed['final_state'],
      'fast_detailed_event_semantics_equal': fast_semantics == detailed_capture,
      'detailed_capture_matches_persisted_trace': detailed_capture == detailed_semantics,
      'trace_sequence_contiguous': [r['trace_sequence'] for r in trace_rows] == list(range(len(trace_rows))),
      'three_fill_events': sum(1 for r in trace_rows if r['event_type']=='fill') == 3,
      'trace_write_errors_zero': not detailed['trace_write_errors'] and detailed['trace_status']=='CONNECTED',
      'input_manifest_files_63_unchanged': len(before)==63 and input_unchanged,
    }
    expected_final_avg = str((base_price:=Decimal(str(base_event['tick']['ask_price'])))*Decimal(1)/Decimal(5) + (base_price+Decimal('0.05'))*Decimal(2)/Decimal(5) + (base_price+Decimal('0.10'))*Decimal(2)/Decimal(5))
    summary = {
      'status':'PASS' if all(flags.values()) and detailed['final_state']['status']=='FILLED' and detailed['final_state']['filled_quantity']==5 else 'FAIL',
      'scope':'validation-only multi-stage partial-fill fast/detailed equivalence; actual OrderStateMachine plus deterministic test-only execution reports and ReplayTraceController; not full Virtual runtime',
      'run_id':RUN_ID,'dataset':manifest['dataset'],'seed':manifest['seed'],'manifest_sha256':manifest_sha,
      'provenance':manifest['provenance'],'synthetic':manifest['synthetic'],'validation_only':manifest['validation_only'],
      'production_runtime_eligible':manifest['production_runtime_eligible'],'input_files_checked':len(before),
      'source_event':{'path':'20261008.jsonl','event_id':base_event['event_id'],'timestamp':base_event['tick']['timestamp'],
                      'synthetic_contract_id':base_event['tick']['synthetic_contract_id'],'identity_status':base_event['identity_status']},
      'fill_fixture':{'order_quantity':5,'stages':3,'incremental_quantities':[1,2,2],'prices':[x['execution_price'] for x in fast['reports']],
                      'expected_average_execution_price':expected_final_avg},
      'fast':{k:v for k,v in fast.items() if k!='captured_events'},
      'detailed':{k:v for k,v in detailed.items() if k!='captured_events'},
      'comparison_flags':flags,'comparison_flag_count':len(flags),'comparison_flags_true':sum(flags.values()),
      'trace':{'path':str(TRACE.relative_to(ROOT)),'records':len(trace_rows),'bytes':TRACE.stat().st_size,'sha256':sha(TRACE),
               'event_types':[r['event_type'] for r in trace_rows]},
      'input_unchanged':input_unchanged,'input_files_before_after_match':sum(1 for k in before if before[k]==after[k]),
      'limitations':['Signal and freshness are not exercised; this is a deterministic validation-only fixture.',
                      'The synthetic source event has BLOCKED_IDENTITY_OWNER_UNRESOLVED; no production identity is claimed.',
                      'Partial fill stages are test-only reports, not observed broker events.',
                      'No position store/PnL, cancel/replace, late-fill race, multi-order or full 53,550-event dataset equivalence was tested.']
    }
    SUMMARY.write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'status':summary['status'],'run_id':RUN_ID,'manifest_sha256':manifest_sha,'input_files_checked':len(before),
                      'final_state':detailed['final_state'],'reports':detailed['reports'],'comparison_flags':flags,
                      'trace_path':str(TRACE.relative_to(ROOT)),'trace_sha256':summary['trace']['sha256'],'summary_path':str(SUMMARY.relative_to(ROOT)),
                      'summary_sha256':sha(SUMMARY),'input_unchanged':input_unchanged},ensure_ascii=False,indent=2))
    if summary['status']!='PASS':
        raise SystemExit(1)

if __name__=='__main__':
    main()
