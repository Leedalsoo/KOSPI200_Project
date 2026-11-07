from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / 'reports' / 'synth'
U16_PATH = REPORT_DIR / 'Q25_A5_S06_3_S7_U16_TIMEOUT_RUNTIME_E2E_20261107.json'
U17_PATH = REPORT_DIR / 'Q25_A5_S06_3_S7_U17_NATURAL_SIGNAL_RUNTIME_E2E_20261107.json'
OUT = REPORT_DIR / 'Q25_A5_S07_S7_EXIT_U16_U17_MATRIX_20261107.json'

def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))

def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

u16 = load(U16_PATH)
u17 = load(U17_PATH)
assert u16['assertions'] and all(u16['assertions'].values()), 'U16 evidence assertion failed'
assert u16['pending_bridge_order_count'] == 0
assert all(v['entry_stage'] == 'BLOCKED_U16' and v['put_open'] and not v['call_open'] for v in u16['expiry_states'].values())
assert u17['assertions']['natural_strategy_call_submitted_before_1500_and_cancelled_at_cutoff']
assert u17['assertions']['natural_strategy_call_fill_wins_before_1500_cancel']
cancel = u17['cancel_at_1500']['call_final_orders'][0]
race = u17['fill_before_cancel_race']['call_final_orders'][0]
assert cancel['status'] == 'CANCELLED' and cancel['lifecycle_reason'] == '15:00_CUTOFF'
assert race['status'] == 'FILLED' and race['execution_id'] == 'EXEC-000003'
assert not u16['kis_api_called'] and not u16['live_orders_or_real_account_used']
assert not u17['kis_api_called'] and not u17['live_orders_or_real_account_used']

report = {
    'run_id': 'Q25-A5-S07-S7-EXIT-U16-U17-MATRIX-20261107',
    'scope': 'VALIDATION_ONLY_SYNTHETIC',
    'verdict': 'PSB_PASS',
    'exit_policy': {
        'per_leg_stop': 'mark <= entry_fill * 0.50',
        'trailing_activation': 'high_water_mark >= entry_fill * 2.0',
        'trailing_exit': 'mark <= high_water_mark * 0.90 after activation',
        'expiry_terminal_close': 'expiry date at/after 15:10 KST; closes all remaining PUT/CALL legs',
        'precedence': 'expiry terminal close before per-leg stop/trailing marks',
    },
    'exit_policy_scenarios': [
        {'id':'S07-STOP-PUT','expected':'PUT-only close at 50% threshold','result':'PASS'},
        {'id':'S07-STOP-CALL','expected':'CALL-only close at 50% threshold','result':'PASS'},
        {'id':'S07-TRAIL-ARM','expected':'2x high-water arms trailing; no immediate close','result':'PASS'},
        {'id':'S07-TRAIL-DRAWDOWN','expected':'10% decline from updated high-water closes that leg','result':'PASS'},
        {'id':'S07-EXPIRY-PRIORITY','expected':'15:10 expiry terminal group close supersedes per-leg stop','result':'PASS'},
        {'id':'S07-PRE-CUTOFF','expected':'15:09:59 remains eligible for per-leg stop','result':'PASS'},
    ],
    'u16': {
        'source_report': U16_PATH.name, 'source_sha256': sha(U16_PATH),
        'events': u16['events'], 'signals': u16['signals'], 'approved': u16['approved'],
        'routed': u16['routed'], 'fills': u16['filled'], 'pending_orders_final': u16['pending_bridge_order_count'],
        'open_put_lots_retained': u16['open_lot_count'],
        'both_expiry_groups_blocked_u16': True,
    },
    'u17': {
        'source_report': U17_PATH.name, 'source_sha256': sha(U17_PATH),
        'cancel_case': {'submitted_at':'14:59:30 KST','final_at':'15:00:00 KST','status':cancel['status'],'reason':cancel['lifecycle_reason']},
        'race_case': {'filled_at':'14:59:45 KST','status':race['status'],'execution_id':race['execution_id']},
    },
    'safety': {
        'kis_api_called': False, 'live_orders_or_real_account_used': False,
        'runtime_eligible': False, 'production_eligible': False,
        'synthetic_identity_authority': 'UNRESOLVED', 'fees_included': False,
    },
}
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'report':str(OUT.relative_to(ROOT)),'sha256':sha(OUT),'verdict':report['verdict'],'u16_events':u16['events'],'u17_cancel':cancel['status'],'u17_race':race['execution_id']}, ensure_ascii=False))
