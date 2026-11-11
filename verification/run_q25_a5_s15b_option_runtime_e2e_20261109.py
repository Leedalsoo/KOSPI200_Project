from __future__ import annotations
import hashlib, json, sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from application.run_hub.contracts import RunContextFactory
from application.run_hub.virtual_session_factory import create_virtual_run_session
from application.strategy_hub.hub import StrategyHub
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from core.strategy.registry import StrategyRegistry
from core.strategy.track1_tail_defense import Track1TailDefense
from environments.high_speed.replay_trace import ReplayExecutionObserver, ReplayLogMode, ReplayTraceController, _trace_value
from environments.high_speed.validation_only_s15b_observed_option_adapter import S15BObservedOptionMarketAdapter
from environments.high_speed.validation_only_s15b_option_proposal_resolver import S15BOptionProposalResolver
MANIFEST=ROOT/'config/validation_only/q25_a5_s15b_observed_s1_call_alignment/manifest.json'
REPORT=ROOT/'reports/synth/Q25_A5_S15B_OPTION_RUNTIME_E2E_FAST_DETAILED_20261109.json'
TRACE=ROOT/'reports/synth/Q25_A5_S15B_OPTION_RUNTIME_E2E_DETAILED_TRACE_20261109.jsonl'
RUN_ID='Q25-A5-S15B-OBSERVED-OPTION-RUNTIME-E2E-20261109'; GROUP_ID='Q25-A5-S15B-OBSERVED-S1-CALL-8875'; CONTRACT_KEY='S1_SHORT_CALL_887_5'
def sha256(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def run_mode(mode: ReplayLogMode, trace_output: Path|None=None)->dict:
    adapter=S15BObservedOptionMarketAdapter(MANIFEST,project_root=ROOT); identity=adapter.identity(CONTRACT_KEY); quote=adapter.quote(CONTRACT_KEY)
    option_master=InMemoryOptionContractMaster(auto_load_kis_source=False)
    option_master.register_contract_identity(KisOptionContractIdentity(shrn_iscd=identity.instrument_id,stnd_iscd=None,expiry=identity.expiry,option_type=identity.option_type,strike=identity.strike,contract_multiplier=identity.contract_multiplier,instrument_family='STANDARD',product_series='MONTHLY',expiry_source='MANIFEST_BOUND_KIS_VTS_EXPIRY_EVIDENCE',expiry_master_sha256=adapter.manifest['target_kis_master_sha256'],master_sha256=adapter.manifest['target_kis_master_sha256']))
    context=adapter.build_strategy_context(); strategy=Track1TailDefense(); adapter.apply_to_strategy(strategy); registry=StrategyRegistry(); registry.register(strategy); hub=StrategyHub(registry,(('TRACK1_TAIL_DEFENSE','1.2.0'),))
    run_context=RunContextFactory().create(run_id=RUN_ID,environment='VIRTUAL_VALIDATION_ONLY',strategy_keys=(),initial_capital=250_000_000.0)
    session=create_virtual_run_session(run_context,option_master); trace=ReplayTraceController(mode,output_path=trace_output); observer=None
    try:
        loop=session.runtime_hub.loop; bridge=loop.multi_leg_bridge; vssf=session.bundle.execution._authoritative_execute.__self__.vssf_runtime
        session.bundle.market.register_replay_option_quote(symbol=identity.symbol,option_type='CALL',strike=float(identity.strike),expiry='2026-11-12',bid=float(quote.bid),ask=float(quote.ask),last=float(quote.last),timestamp=quote.received_at.isoformat(),contract_multiplier=float(identity.contract_multiplier),source='OBSERVED_KIS_VTS:H0IOASP0:VALIDATION_ONLY')
        loop.strategy_hub=hub; loop.context_builder=lambda _tick,_state:{'TRACK1_TAIL_DEFENSE':context}; loop.identity_provider=lambda _evaluation,_tick:adapter.identity(CONTRACT_KEY)
        resolver=S15BOptionProposalResolver(adapter)
        loop.multi_leg_plan_resolver=lambda evaluation,_canonical:resolver.resolve(evaluation.result.execution_proposal,scenario_contract_key=CONTRACT_KEY,group_id=GROUP_ID)
        loop.multi_leg_executor=bridge.execute; bridge.freshness_verdict_provider=lambda _plan,_leg,_identity,_command:adapter.freshness(CONTRACT_KEY)
        vssf.clock=None; vssf._market_time=quote.received_at; timestamp=quote.received_at.isoformat(); timestamp_kst=quote.received_at.astimezone(ZoneInfo('Asia/Seoul')).isoformat()
        tick=SimpleNamespace(timestamp=timestamp,seq_id=1,underlying_price=Decimal('876.54'),volume=Decimal('1'),ask_price=quote.ask)
        trace.emit('replay_started',run_id=RUN_ID,event_sequence=1,timestamp=timestamp,payload={'mode':mode.value,'validation_only':True,'manifest_sha256':sha256(MANIFEST)})
        trace.emit('market_event',run_id=RUN_ID,event_sequence=1,timestamp=timestamp,payload={'underlying_price':'876.54','instrument_id':identity.instrument_id,'symbol':identity.symbol,'bid':str(quote.bid),'ask':str(quote.ask),'mark_midpoint':str(quote.last),'source':'OBSERVED_KIS_VTS:H0IOASP0:VALIDATION_ONLY'})
        observer=ReplayExecutionObserver(trace,run_id=RUN_ID); observer.event_sequence=1; observer.attach(bridge.ack,adapter_name='S15B_VALIDATION_ONLY_VIRTUAL_BROKER')
        runtime_result=loop.on_tick(tick); reports=bridge.group_reports(GROUP_ID)
        vssf.process_market_data(SimpleNamespace(timestamp=timestamp,instrument_id=identity.instrument_id,symbol=identity.symbol,bid_price=float(quote.bid),ask_price=float(quote.ask),last_price=float(quote.last)))
        bridge.refresh_position_group_marks(); group=bridge.position_groups.snapshot(GROUP_ID); account=session.bundle.account.snapshot(); open_lots=bridge.position_lot_store.open_lots(); risk_approvals=bridge.risk_approvals(GROUP_ID); freshness=adapter.freshness(CONTRACT_KEY); observer_summary=observer.summary()
        trace.emit('runtime_result',run_id=RUN_ID,event_sequence=1,timestamp=timestamp,payload={'result':_trace_value(runtime_result),'risk_approvals':_trace_value(risk_approvals)})
        trace.emit('position_marked',run_id=RUN_ID,event_sequence=1,timestamp=timestamp,payload={'position_group':_trace_value(group),'account':_trace_value(account),'open_lots':_trace_value(open_lots)})
        trace.emit('replay_finished',run_id=RUN_ID,event_sequence=1,timestamp=timestamp,payload={'execution_ids':list(runtime_result.execution_ids),'observer':observer_summary})
        report_rows=[{'client_order_id':x.client_order_id,'execution_id':x.execution_id,'status':str(getattr(x.status,'value',x.status)),'filled_quantity':x.filled_quantity,'execution_price':str(x.execution_price) if x.execution_price is not None else None,'execution_timestamp':x.execution_timestamp.isoformat() if x.execution_timestamp else None,'fee':str(x.fee) if x.fee is not None else None,'leg_id':x.leg_id} for x in reports]
        group_row=None if group is None else {'complete':group.complete,'leg_count':len(group.legs),'legs':[{'leg_id':x.leg_id,'instrument_id':x.instrument_id,'quantity':x.quantity,'average_price':str(x.avg_price),'current_mark':str(x.current_price),'unrealized_pnl_krw':str(x.unrealized_pnl),'contract_multiplier':str(x.contract_multiplier)} for x in group.legs],'realized_pnl_krw':str(group.realized_pnl),'unrealized_pnl_krw':str(group.unrealized_pnl),'total_pnl_krw':str(group.total_pnl)}
        balances=account.balances; account_balances={key:str(balances[key]) for key in ('cash','margin_used','available_cash','realized_pnl','unrealized_pnl')}
        semantic={'manifest_sha256':sha256(MANIFEST),'dataset_sha256':sha256(ROOT/adapter.manifest['dataset_path']),'natural_signals':runtime_result.signals,'decision_approved':runtime_result.approved,'risk_approved':len(risk_approvals),'routed':runtime_result.routed,'filled':runtime_result.filled,'rejected':runtime_result.rejected,'execution_ids':list(runtime_result.execution_ids),'reports':report_rows,'position_group':group_row,'account_balances':account_balances,'open_lot_count':len(open_lots),'open_lot_remaining_quantity':sum(x.remaining_quantity for x in open_lots),'freshness_status':freshness.status.value,'freshness_policy_version':freshness.policy_version,'freshness_evidence_sha256':freshness.evidence_sha256,'execution_timestamp_kst':timestamp_kst,'runtime_failures':sum(x.runtime_failures for x in runtime_result.strategy_status),'risk_rejections':sum(x.risk_rejected for x in runtime_result.strategy_status)}
        return {'mode':mode.value,'trace_status':trace.status,'trace_write_errors':list(trace.write_errors),'observer_summary':observer_summary,'semantic':semantic,'validation_only':True,'kis_api_called':False,'live_or_real_account_used':False,'orders_sent_to_external_broker':False,'execution_price_basis':'OBSERVED_BEST_BID_USED_AS_VALIDATION_ONLY_VIRTUAL_FILL; NOT_AN_OBSERVED_HISTORICAL_FILL','mark_price_basis':'DERIVED_BEST_BID_ASK_MIDPOINT; NOT_AN_OBSERVED_TRADE','fee_model_status':'VSSF_DEFAULT_ZERO_FEE; NO_APPROVED_FEE_SCHEDULE','fee_inclusive_pnl_verified':False}
    finally:
        if observer is not None: observer.detach()
        session.close()
def adapter_hash(key): return str(S15BObservedOptionMarketAdapter(MANIFEST,project_root=ROOT).manifest[key])
def main():
    if REPORT.exists() or TRACE.exists(): raise FileExistsError('REFUSING_TO_OVERWRITE_EXISTING_S15B_RUNTIME_ARTIFACT')
    fast=run_mode(ReplayLogMode.FAST); detailed=run_mode(ReplayLogMode.DETAILED,TRACE); equal=fast['semantic']==detailed['semantic']
    observer_ok=detailed['observer_summary']['status']=='CONNECTED' and detailed['observer_summary']['order_commands_observed']==1 and detailed['observer_summary']['execution_reports_observed']==1 and detailed['observer_summary']['fills_observed']==1 and detailed['observer_summary']['trace_write_errors']==[]
    records=[json.loads(x) for x in TRACE.read_text(encoding='utf-8').splitlines() if x.strip()]; seq=[x['trace_sequence'] for x in records]; sem=fast['semantic']; group=sem['position_group'] or {}
    assertions={'fast_detailed_semantics_equal':equal,'same_dataset_and_manifest_hashes':sem['dataset_sha256']==detailed['semantic']['dataset_sha256'] and sem['manifest_sha256']==detailed['semantic']['manifest_sha256'],'one_natural_signal_decision_risk_oms_virtual_fill':sem['natural_signals']==sem['decision_approved']==sem['risk_approved']==sem['routed']==sem['filled']==1 and sem['rejected']==0,'exact_observed_option_contract':bool(group.get('legs')) and group['legs'][0]['instrument_id']=='B01611887' and group['legs'][0]['quantity']==1,'position_and_account_mtm_reconcile':Decimal(group.get('unrealized_pnl_krw'))==Decimal(sem['account_balances']['unrealized_pnl']) and Decimal(group.get('realized_pnl_krw'))==Decimal(sem['account_balances']['realized_pnl']),'execution_timestamp_matches_observed_orderbook_receive_time':sem['reports'][0]['execution_timestamp']==datetime.fromisoformat(sem['execution_timestamp_kst']).astimezone(ZoneInfo('UTC')).isoformat(),'detailed_trace_and_observer_valid':observer_ok and seq==list(range(len(records))) and len(records)>=7,'no_runtime_or_risk_failures':sem['runtime_failures']==sem['risk_rejections']==0,'validation_only_no_external_api_or_orders':all(x['validation_only'] and not x['kis_api_called'] and not x['live_or_real_account_used'] and not x['orders_sent_to_external_broker'] for x in (fast,detailed))}
    passed=all(assertions.values())
    report={'schema':'q25-a5-s15b-option-runtime-e2e-fast-detailed-v1','report_id':'Q25_A5_S15B_OPTION_RUNTIME_E2E_FAST_DETAILED_20261109','verdict':'PSB_PASS_VALIDATION_ONLY_SINGLE_LEG_OPTION_RUNTIME_E2E' if passed else 'PSB_UNVERIFIED','overall_s15b_status':'PLUMBING_ONLY','run_id':RUN_ID,'scope':'S1 natural short CALL 887.5 only; StrategyHub -> Decision -> Risk -> OMS/Router -> VSSF Virtual Execution -> Position/PnL; FAST/DETAILED observation parity','input_hashes':{'manifest_sha256':sem['manifest_sha256'],'dataset_sha256':sem['dataset_sha256'],'target_kis_master_sha256':adapter_hash('target_kis_master_sha256'),'observed_orderbook_payload_sha256':sem['freshness_evidence_sha256']},'fast':fast,'detailed':detailed,'detailed_trace':{'path':TRACE.relative_to(ROOT).as_posix(),'sha256':sha256(TRACE),'records':len(records),'sequence_contiguous':seq==list(range(len(records)))},'assertions':assertions,'limitations':['Only the observed S1 short CALL 887.5 single-leg path is exercised; base strangle PUT/CALL and other contracts are not covered.','The virtual fill at observed best bid 35.00 is a validation-only simulated fill, not an observed historical execution.','The 36.325 midpoint mark is derived from observed best bid/ask and is not an observed trade.','VSSF default fee is zero; no approved fee schedule exists, so fee-inclusive/net PnL is not verified.','No exit/close event or realized PnL is tested; the short position remains open in the isolated run.','The OPTION resolver is still a validation-only injection; Production Runtime Factory OPTION routing remains unchanged and unconnected.','KRX STANDARD multiplier is used only in the manifest-bound validation-only profile.'],'safety':{'validation_only':True,'production_runtime_modified':False,'kis_api_called':False,'real_vts_or_live_called':False,'external_broker_or_real_account_used':False,'original_raw_data_modified':False,'s15a_original_modified':False}}
    REPORT.write_bytes(json.dumps(report,ensure_ascii=False,indent=2).encode('utf-8')+bytes([10])); print(json.dumps({'verdict':report['verdict'],'assertions':assertions,'report':REPORT.as_posix(),'trace':TRACE.as_posix()},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
