from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from contracts.types import OptionInstrumentIdentity
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources, build_synthetic_option_master
from environments.high_speed.validation_only_track7_execution import S7ValidationOnlyRuntimeAdapter
from environments.high_speed.validation_only_trading_calendar import load_validation_only_trading_calendar
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote

DATASET = ROOT / "data/derived_scenario/q25_s05_3_s7_concurrent"
MANIFEST = DATASET / "manifest.json"
PROFILE = ROOT / "config/validation_only/q25_s05_3_s7_concurrent/risk_profile.json"
REPORT = ROOT / "reports/synth/Q25_A5_S06_3_S7_U17_RUNTIME_CANCEL_RACE_20261107.json"
RUN_ID = "Q25-A5-S06-3-S7-U17-RUNTIME-20261107"
EXPIRY = "20261112"
GROUP_ID = "Q25-A5-S06-3-S7-U17-GROUP"

class MutableClock:
    def __init__(self, now):
        self.current = now

    def now(self):
        return self.current

    def monotonic(self):
        return 0.0

    def sleep_policy(self, seconds):
        return None


def build_case(run_id, *, race_fill):
    replay_adapter = SyntheticReplayAdapter(DATASET, manifest_path=MANIFEST)
    master = build_synthetic_option_master(DATASET, validation_only_adapter=replay_adapter)
    ticks = list(HighSpeedReplayRunner(DATASET, synthetic_adapter=replay_adapter).events())
    put_source = next(t for t in ticks if t.expiry == EXPIRY and str(t.option_type).upper() == "PUT")
    call_source = next(t for t in ticks if t.expiry == EXPIRY and t.timestamp == put_source.timestamp
                       and str(t.option_type).upper() == "CALL")
    put_tick = replace(put_source, timestamp="2026-11-05T14:59:00+09:00")
    call_tick = replace(call_source, timestamp="2026-11-05T14:59:00+09:00")

    validation_calendar = load_validation_only_trading_calendar(MANIFEST, DATASET)
    sources = SyntheticRuntimeSources(calendar=validation_calendar)
    validation = S7ValidationOnlyRuntimeAdapter(
        dataset=DATASET, manifest_path=MANIFEST, risk_profile_path=PROFILE
    )
    validation.bind_run_id(run_id)
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=master, initial_capital=250_000_000.0,
        risk_guard_status_source=sources,
    )
    if bootstrap.automated_loop is not None:
        bootstrap.bundle.market.unsubscribe(bootstrap.automated_loop.on_tick)
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(("track7_volatility_skew_weekly_insurance", "1.0"),),
        run_id=run_id,
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
        validation_only_s7_runtime_adapter=validation,
    )
    bootstrap.bundle.market.unsubscribe(loop.on_tick)
    bridge = loop.multi_leg_bridge
    vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
    clock = MutableClock(datetime.fromisoformat("2026-11-05T14:59:00+09:00"))
    vssf.attach_clock(clock)
    registry = loop.strategy_hub._orchestrator._registry
    strategy = registry.get("track7_volatility_skew_weekly_insurance", "1.0")

    for tick in (put_tick, call_tick):
        sources.prime_option_quote(tick)
        _publish_contract_scoped_replay_quote(
            tick, option_master=master, market=bootstrap.bundle.market,
            order_book=vssf.order_book,
        )
    sources.set_tick(call_tick)
    vssf.process_market_data(call_tick)

    strategy._activate_expiry(EXPIRY)
    strategy.state = strategy.state.__class__(
        entry_pending=True, expiry=EXPIRY, put_strike=Decimal(str(put_tick.strike_price)),
        call_strike=Decimal(str(call_tick.strike_price)),
        contract_multiplier=Decimal(str(put_tick.contract_multiplier)),
        entry_stage="PUT_READY",
    )
    put_proposal = StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", side="BUY",
        track_id=strategy.strategy_id, tag_id="WEEKLY_INSURANCE_ENTRY_PUT",
        option_type="PUT", strike=Decimal(str(put_tick.strike_price)),
    )
    put_plan = strategy.build_execution_plan(GROUP_ID, proposal=put_proposal)
    put_master_identity = master.get_contract_identity(put_tick.instrument_id)
    put_identity = OptionInstrumentIdentity(
        instrument_id=put_master_identity.shrn_iscd, symbol=put_master_identity.shrn_iscd,
        expiry=put_master_identity.expiry, option_type=put_master_identity.option_type,
        strike=Decimal(str(put_master_identity.strike)),
        contract_multiplier=Decimal(str(put_master_identity.contract_multiplier)),
        identity_source="OPTION_MASTER",
    )
    put_plan = replace(put_plan, legs=(replace(
        put_plan.legs[0], instrument_identity=put_identity
    ),))
    put_result = bridge.execute(put_plan)
    if put_result.reports[0].status != "FILLED":
        raise RuntimeError(f"U17_PUT_FILL_REQUIRED:{put_result.reports[0].status}")

    call_proposal = StrategyExecutionProposal(
        proposed_quantity=1, asset_type="OPTION", side="BUY",
        track_id=strategy.strategy_id, tag_id="WEEKLY_INSURANCE_ENTRY_CALL",
        option_type="CALL", strike=Decimal(str(call_tick.strike_price)),
    )
    call_plan = strategy.build_execution_plan("ignored-call-group", proposal=call_proposal)
    call_master_identity = master.get_contract_identity(call_tick.instrument_id)
    call_identity = OptionInstrumentIdentity(
        instrument_id=call_master_identity.shrn_iscd, symbol=call_master_identity.shrn_iscd,
        expiry=call_master_identity.expiry, option_type=call_master_identity.option_type,
        strike=Decimal(str(call_master_identity.strike)),
        contract_multiplier=Decimal(str(call_master_identity.contract_multiplier)),
        identity_source="OPTION_MASTER",
    )
    call_plan = replace(call_plan, legs=(replace(
        call_plan.legs[0], requested_price=Decimal("0.01"),
        instrument_identity=call_identity,
    ),))
    call_result = bridge.execute(call_plan)
    if call_result.reports[0].status != "NEW" or call_result.pending_legs != 1:
        raise RuntimeError(f"U17_CALL_PENDING_REQUIRED:{call_result.reports[0].status}")

    client_order_id = call_result.reports[0].client_order_id
    if race_fill:
        # At 14:59:59 the synthetic ask reaches the submitted BUY limit, so the fill wins
        # immediately before the 15:00 cancellation request.
        race_tick = replace(
            call_tick, timestamp="2026-11-05T14:59:59+09:00",
            bid_price=0.005, ask_price=0.01, last_price=0.01,
        )
        clock.current = datetime.fromisoformat("2026-11-05T14:59:59+09:00")
        vssf.process_market_data(race_tick)

    clock.current = datetime.fromisoformat("2026-11-05T15:00:00+09:00")
    vssf._market_time = clock.current
    loop.pending_multi_leg_processor(SimpleNamespace(timestamp="2026-11-05T15:00:00+09:00"))

    final = vssf.query_order(client_order_id)
    lots = bridge.position_lot_store.open_lots()
    return {
        "race_fill": race_fill,
        "put_initial_status": put_result.reports[0].status,
        "call_initial_status": call_result.reports[0].status,
        "client_order_id": client_order_id,
        "broker_final_status": final.status if final else None,
        "broker_final_lifecycle_reason": final.lifecycle_reason if final else None,
        "strategy_stage": strategy.state.entry_stage,
        "strategy_block_reason": strategy.state.entry_block_reason,
        "put_open": strategy.state.put_open,
        "call_open": strategy.state.call_open,
        "insurance_active": strategy.state.insurance_active,
        "entry_pending": strategy.state.entry_pending,
        "open_lots": [{
            "option_type": str(lot.instrument_identity.option_type),
            "quantity": lot.remaining_quantity,
            "execution_id": lot.execution_id,
        } for lot in lots],
        "pending_bridge_orders": len(bridge.pending_legs),
        "account_positions": {
            str(k): v for k, v in vssf.account.positions.items()
            if abs(float(v.get("qty", 0) if isinstance(v, dict) else getattr(v, "qty", 0))) > 0
        },
    }

def main():
    if REPORT.exists():
        raise SystemExit("S06_3_U17_REPORT_ALREADY_EXISTS")
    cancelled = build_case(RUN_ID + "-CANCEL", race_fill=False)
    race_filled = build_case(RUN_ID + "-FILL-RACE", race_fill=True)
    cancelled_ok = (
        cancelled["broker_final_status"] == "CANCELLED"
        and cancelled["broker_final_lifecycle_reason"] == "15:00_CUTOFF"
        and cancelled["strategy_stage"] == "BLOCKED_U17"
        and cancelled["put_open"] and not cancelled["call_open"]
        and len(cancelled["open_lots"]) == 1
        and cancelled["open_lots"][0]["option_type"] == "PUT"
        and cancelled["pending_bridge_orders"] == 0
    )
    race_ok = (
        race_filled["broker_final_status"] == "FILLED"
        and race_filled["strategy_stage"] == "COMPLETE"
        and race_filled["insurance_active"]
        and race_filled["put_open"] and race_filled["call_open"]
        and len(race_filled["open_lots"]) == 2
        and {x["option_type"] for x in race_filled["open_lots"]} == {"PUT", "CALL"}
        and race_filled["pending_bridge_orders"] == 0
    )
    passed = cancelled_ok and race_ok
    report = {
        "report_id": "Q25_A5_S06_3_S7_U17_RUNTIME_CANCEL_RACE_20261107",
        "verdict": "PLUMBING_ONLY_U17_RUNTIME_CANCEL_AND_FILL_RACE" if passed else "BLOCKED_RUNTIME_RECONCILIATION",
        "stage_verdict": "PSB_UNVERIFIED_NATURAL_U17_SIGNAL_E2E_PENDING",
        "cancelled_at_cutoff": cancelled,
        "fill_won_cancel_race": race_filled,
        "assertions": {
            "15_00_cancel_and_final_cancelled_reconciled": cancelled_ok,
            "15_00_cancel_race_final_filled_reconciled": race_ok,
        },
        "natural_strategy_signal_used": False,
        "validation_only": True,
        "runtime_eligible": False,
        "production_runtime_eligible": False,
        "kis_api_called": False,
        "live_orders_or_real_account_used": False,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not passed:
        raise SystemExit("S06_3_U17_RUNTIME_ASSERTIONS_FAILED")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

