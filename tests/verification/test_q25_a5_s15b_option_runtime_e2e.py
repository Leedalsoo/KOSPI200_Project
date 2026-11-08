from pathlib import Path
import json
from environments.high_speed.replay_trace import ReplayLogMode
from verification.run_q25_a5_s15b_option_runtime_e2e_20261109 import run_mode

def test_s15b_observed_option_runtime_fast_detailed_equivalence(tmp_path: Path) -> None:
    fast=run_mode(ReplayLogMode.FAST)
    trace_path=tmp_path/'s15b_detailed_trace.jsonl'
    detailed=run_mode(ReplayLogMode.DETAILED,trace_path)
    assert fast['semantic']==detailed['semantic']
    sem=fast['semantic']
    assert sem['natural_signals']==sem['decision_approved']==sem['risk_approved']==sem['routed']==sem['filled']==1
    assert sem['rejected']==0
    assert sem['reports'][0]['status']=='FILLED'
    assert sem['reports'][0]['execution_price']=='35.0'
    assert sem['reports'][0]['execution_timestamp']=='2026-10-21T00:01:16.106074+00:00'
    assert sem['position_group']['unrealized_pnl_krw']=='-331250.0'
    assert sem['account_balances']['unrealized_pnl']=='-331250.0000'
    assert sem['open_lot_count']==sem['open_lot_remaining_quantity']==1
    assert fast['fee_inclusive_pnl_verified'] is False
    assert detailed['observer_summary']['order_commands_observed']==1
    assert detailed['observer_summary']['execution_reports_observed']==1
    assert detailed['observer_summary']['fills_observed']==1
    records=[json.loads(line) for line in trace_path.read_text(encoding='utf-8').splitlines()]
    assert [x['trace_sequence'] for x in records]==list(range(len(records)))
    assert {x['event_type'] for x in records}>={'market_event','order_command','execution_report','fill','position_marked'}
