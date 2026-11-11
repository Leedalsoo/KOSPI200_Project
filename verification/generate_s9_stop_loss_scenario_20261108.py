from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCENARIO_ID='S9_INDEPENDENT_ATM_OVERNIGHT_STOP_LOSS_001'
DATA_DIR=ROOT/'data/derived_scenario/q25_s9_independent_overnight_stop_loss_20261108'
DATA_FILE=DATA_DIR/'20261106.jsonl'
MANIFEST=DATA_DIR/'manifest.json'
RISK=ROOT/'config/validation_only/q25_s9_independent_overnight_20261108/risk_profile.json'
CONTRACT=ROOT/'config/validation_only/track9_independent_synthetic_contract_profile.json'
def sha(b): return hashlib.sha256(b).hexdigest()
def write_new(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists(): raise RuntimeError(f'REFUSE_OVERWRITE:{path.relative_to(ROOT)}')
    path.write_bytes(data)
def tick(seq,ts,typ,bid,ask,last,underlying,dte):
    strike=500.0; expiry='20261112'; code=f'S9-{typ}-{expiry}-500'
    return {'schema':'reference-canonical-market-tick-v1','provenance':'DERIVED_SCENARIO','synthetic':True,'tick':{
      'timestamp':ts,'underlying_price':underlying,'underlying_symbol':'KOSPI200','underlying_observed_hour':ts[11:19],
      'underlying_source':'SYNTHETIC:DERIVED_SCENARIO','strike_price':strike,'option_type':typ,'contract_multiplier':100000.0,
      'bid_price':bid,'ask_price':ask,'last_price':last,'volume':100,'seq_id':seq,'expiry':expiry,'symbol':code,
      'option_observed_hour':ts[11:19],'option_source':'SYNTHETIC:DERIVED_SCENARIO','instrument_id':None,
      'synthetic_contract_id':f'SYNTHETIC_CONTRACT:S9-{expiry}-{typ}-500','source_instrument_code':code,
      'instrument_identity_status':'BLOCKED_IDENTITY_OWNER_UNRESOLVED','contract_class':'monthly','contract_month':'202611',
      'theoretical_mid_price':last,'intrinsic_value':0.0,'time_value':last,'time_to_expiry_seconds':dte*86400,
      'implied_volatility':0.20,'delta':-0.50 if typ=='PUT' else 0.50,'gamma':0.01,'theta':-0.01,'vega':0.10},
      'scenario_metadata':{'scenario_id':SCENARIO_ID,'validation_only':True,'regime':'NORMAL','dte_trading_days':dte,
      'identity_source_status':'BLOCKED_IDENTITY_OWNER_UNRESOLVED','contract_identity_authority':'SYNTHETIC_ONLY',
      'instrument_family':'STANDARD','product_series':'MONTHLY','group_id':'S9-OVERNIGHT-STOP-LOSS-001'}}
def main():
    contract_hash=sha(CONTRACT.read_bytes()); risk_hash=sha(RISK.read_bytes())
    records=[
      tick(1,'2026-11-06T15:00:00+09:00','PUT',4.8,5.0,4.9,500.4,4),
      tick(2,'2026-11-06T15:00:00+09:00','CALL',5.2,5.4,5.3,500.4,4),
      tick(3,'2026-11-09T09:00:00+09:00','PUT',2.0,2.2,2.1,502.5,3),
      tick(4,'2026-11-09T09:00:00+09:00','CALL',2.2,2.4,2.3,502.5,3),
    ]
    db=b''.join((json.dumps(x,sort_keys=True,separators=(',',':'))+'\n').encode() for x in records)
    dh=sha(db)
    policy={'entry_evaluation_time':'15:00:00','entry_evaluation_timezone':'Asia/Seoul',
      'entry_instrument_selection':'NEAREST_EXPIRY_SAME_STRIKE_ATM_PUT_CALL','pair_quantity_per_leg':1,
      'opening_move_threshold':'0.01','opening_move_metric':'ABS((next_session_open-previous_close)/previous_close)',
      'at_or_above_threshold_action':'CLOSE_INSURANCE','below_threshold_action':'STOP_LOSS','trailing_profit_exit':'NOT_USED'}
    missing={k:'MISSING' for k in ('official_contract_multiplier','official_tradability','official_previous_close',
      'official_next_session_open','official_option_quotes','official_trading_calendar','official_virtual_account','kis_live_order_access')}
    manifest={'schema_version':'q25-a2-1-s6-syn-evt-manifest-v1','dataset_id':'Q25_S9_INDEPENDENT_ATM_OVERNIGHT_STOP_LOSS_20261108',
      'scenario_id':SCENARIO_ID,'scenario_ids':[SCENARIO_ID],'scenario_count':1,'scenario_regimes':{SCENARIO_ID:'NORMAL'},
      'source_type':'DERIVED_SCENARIO','provenance':'DERIVED_SCENARIO','synthetic':True,'validation_only':True,
      'runtime_eligible':False,'production_runtime_eligible':False,'identity_source_status':'BLOCKED_IDENTITY_OWNER_UNRESOLVED',
      'expiry_is_authoritative':False,'official_data_status':missing,'strategy_id':'track9_event_overnight_insurance',
      'strategy_code_version':'3.0','strategy_policy':policy,'orders_allowed':False,
      'validation_identity_namespace':'SYNTHETIC_CONTRACT:S9-','dataset_file':DATA_FILE.name,
      'output_path':DATA_FILE.relative_to(ROOT).as_posix(),'output_sha256':dh,'dataset_sha256':dh,'output_bytes':len(db),'rows':4,
      'entry_date':'2026-11-06','next_session_date':'2026-11-09','expiry':'20261112',
      'synthetic_reference_inputs':{'previous_official_close':'500','next_session_official_open':'502.5',
        'previous_official_close_provenance':'SYNTHETIC','next_session_official_open_provenance':'SYNTHETIC'},
      'contract_profile_path':CONTRACT.relative_to(ROOT).as_posix(),'contract_profile_sha256':contract_hash,
      'risk_profile_path':RISK.relative_to(ROOT).as_posix(),'risk_profile_sha256':risk_hash,
      'trading_calendar':{'calendar_id':'S9_SYNTHETIC_CALENDAR_20261108','source_type':'SYNTHETIC','authoritative':False,
        'timezone':'Asia/Seoul','trading_days':['2026-11-06','2026-11-09','2026-11-10','2026-11-11','2026-11-12']},
      'notes':['Independent S9 synthetic scenario; no S1 strategy code or linked position is used.',
        'The 0.5% opening move exercises the approved below-1% STOP_LOSS branch.',
        'Synthetic option marks decline to 2.0/2.2 bid; this is a fixed scenario assumption, not calibrated market data.',
        'All official data remains MISSING; KIS/REAL_VTS/Live/real account/order routes are disabled.']}
    mb=(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
    write_new(DATA_FILE,db); write_new(DATA_DIR/'manifest.json',mb)
    write_new(DATA_DIR/'20261106.jsonl.sha256',(dh+'  20261106.jsonl\n').encode())
    write_new(DATA_DIR/'manifest.json.sha256',(sha(mb)+'  manifest.json\n').encode())
    print(json.dumps({'scenario_id':SCENARIO_ID,'rows':4,'dataset_sha256':dh,'manifest_sha256':sha(mb),'data_path':str(DATA_FILE.relative_to(ROOT))},indent=2))
if __name__=='__main__': main()
