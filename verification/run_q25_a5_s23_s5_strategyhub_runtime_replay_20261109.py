from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from types import SimpleNamespace
from shared.contracts.canonical import CanonicalMarketTick
from environments.high_speed.validation_only_s5_seed_ingestion import S5ValidationOnlySeedAdapter

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SEED = ROOT / "data/derived_scenario/q25_a5_s23_s5_canonical_runtime_close_e2e_20261109_retry1"
SOURCE_EVENT = SOURCE_SEED / "events.jsonl"
SOURCE_MANIFEST = SOURCE_SEED / "manifest.json"
SYNTHETIC_ID = "SYNTHETIC_CONTRACT:S5:20261112:CALL:887.50"
SOURCE_CODE = "B01611887"
EXPIRY = "20261112"
STRIKE = Decimal("887.50")
MULTIPLIER = Decimal("250000")
IDENTITY_SOURCE = "KIS_OFFICIAL_MASTER|KIS_PRODUCT_SPEC"
SSOT_SHA = "E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return sha(path)


def build_seed(mode: str, run_id: str, group_id: str) -> tuple[Path, Path, str, str]:
    target = ROOT / f"data/derived_scenario/q25_a5_s23_s5_strategyhub_seed_{mode.lower()}_20261109_retry13"
    if target.exists():
        raise FileExistsError(f"REFUSE_OVERWRITE:{target}")
    target.mkdir(parents=True)
    shutil.copy2(SOURCE_SEED / "market_snapshot.json", target / "market_snapshot.json")
    shutil.copy2(SOURCE_SEED / "analytics_snapshot.json", target / "analytics_snapshot.json")
    event = json.loads(SOURCE_EVENT.read_text(encoding="utf-8").splitlines()[0])
    event["run_id"] = run_id
    event["group_id"] = group_id
    event["instrument_id"] = SYNTHETIC_ID
    event["symbol"] = SYNTHETIC_ID
    event["source_instrument_code"] = SOURCE_CODE
    event["client_order_id"] = f"S5-S23-STRATEGYHUB-{mode}-SEED-OPEN"
    event["execution_id"] = f"EXEC-000001"
    event["execution_fills"][0]["execution_id"] = event["execution_id"]
    event["leg_id"] = "S5-CALL-OPEN"
    event["synthetic_identity_mapping"] = {
        "synthetic_instrument_id": SYNTHETIC_ID,
        "source_kis_instrument_code": SOURCE_CODE,
        "source_expiry": EXPIRY,
        "option_type": "CALL",
        "strike": str(STRIKE),
        "contract_multiplier": str(MULTIPLIER),
        "mapping_provenance": "VALIDATION_ONLY_ALIAS_FROM_KIS_ANCHORED_SEED",
    }
    events = target / "events.jsonl"
    events.write_text(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    manifest.update({"run_id": run_id, "group_id": group_id, "instrument_id": SYNTHETIC_ID,
                     "events_file": "events.jsonl", "events_sha256": sha(events)})
    manifest["source_instrument_code"] = SOURCE_CODE
    manifest["synthetic_identity_mapping"] = event["synthetic_identity_mapping"]
    manifest_path = target / "manifest.json"
    write_json(manifest_path, manifest)
    validated = S5ValidationOnlySeedAdapter(manifest_path=manifest_path, dataset_path=events).validate()
    assert validated.event["instrument_id"] == SYNTHETIC_ID
    assert validated.event["source_instrument_code"] == SOURCE_CODE
    return manifest_path, events, validated.manifest_sha256, validated.dataset_sha256


def build_replay(mode: str) -> tuple[Path, str, str]:
    target = ROOT / f"data/derived_scenario/q25_a5_s23_s5_strategyhub_replay_{mode.lower()}_20261109_retry13"
    if target.exists():
        raise FileExistsError(f"REFUSE_OVERWRITE:{target}")
    target.mkdir(parents=True)
    ticks = []
    for seq, timestamp, spot in (
        (1, "2026-10-22T02:15:24.139295+09:00", 891.04),
        (2, "2026-10-22T02:16:00+09:00", 858.78),
    ):
        tick = {
            "timestamp": timestamp, "underlying_price": spot, "underlying_symbol": "KOSPI200",
            "underlying_observed_hour": timestamp[11:16], "underlying_source": "SYNTHETIC:DERIVED_SCENARIO",
            "strike_price": float(STRIKE), "option_type": "CALL", "contract_multiplier": float(MULTIPLIER),
            "bid_price": 42.25, "ask_price": 42.35, "last_price": 42.30, "volume": 100,
            "seq_id": seq, "expiry": EXPIRY, "symbol": SYNTHETIC_ID,
            "option_observed_hour": timestamp[11:16], "option_source": "SYNTHETIC:DERIVED_SCENARIO",
            "underlying_sequence": seq, "instrument_id": SYNTHETIC_ID,
            "synthetic_contract_id": SYNTHETIC_ID, "source_instrument_code": SOURCE_CODE,
            "instrument_identity_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
            "contract_class": "monthly", "contract_month": "202611",
            "theoretical_mid_price": None, "intrinsic_value": None, "time_value": None,
            "time_to_expiry_seconds": None, "implied_volatility": 45.8001,
            "delta": 0.5477, "gamma": 0.0025, "theta": -1.4641, "vega": 0.8662,
        }
        ticks.append({
            "schema": "reference-canonical-market-tick-v1", "provenance": "DERIVED_SCENARIO",
            "synthetic": True, "validation_only": True, "production_runtime_eligible": False,
            "scenario_metadata": {
                "validation_only": True, "scenario_id": "S5-S23-STRATEGYHUB-CLOSE",
                "group_id": f"S5-S23-STRATEGYHUB-{mode}", "regime": "NORMAL",
                "dte_trading_days": 15, "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
                "contract_identity_authority": "SYNTHETIC_ONLY", "instrument_family": "STANDARD",
                "product_series": "KOSPI200_STANDARD", "source_kis_instrument_code": SOURCE_CODE,
            },
            "tick": tick,
        })
    events_path = target / "20261022.jsonl"
    events_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ticks), encoding="utf-8")
    manifest = {
        "schema": "reference-canonical-market-tick-v1", "synthetic": True,
        "provenance": "DERIVED_SCENARIO", "validation_only": True,
        "production_runtime_eligible": False,
        "identity_source_status": "BLOCKED_IDENTITY_OWNER_UNRESOLVED",
        "identity_policy": {"mode": "SYNTHETIC_ONLY", "synthetic_contract_id_namespace": "SYNTHETIC_CONTRACT:",
                            "production_standard_instrument_id_assigned": False},
        "validation_identity_namespace": "SYNTHETIC_CONTRACT:",
        "scenario_ids": ["S5-S23-STRATEGYHUB-CLOSE"], "scenario_count": 1,
        "scenario_regimes": {"S5-S23-STRATEGYHUB-CLOSE": "NORMAL"},
        "events_file": events_path.name, "event_count": len(ticks),
        "events_sha256": sha(events_path),
        "source_instrument_code": SOURCE_CODE,
        "source_kis_expiry": EXPIRY, "source_contract_identity": IDENTITY_SOURCE,
        "source_expiry_file_sha256": "DC100CD8D218A2FDE77406D4761C0ACCE617F3D5088C0D951796CE7F9595234F",
        "source_master_file_sha256": "EFB5B80BE190971EEA41A73F20573E7F4A4B33CAEABF1FC47CA8298A315E43EB",
        "contract_multiplier": str(MULTIPLIER),
        "note": "Validation-only synthetic alias; no Standard instrument ID is assigned to runtime routing.",
    }
    manifest_path = target / "manifest.json"
    write_json(manifest_path, manifest)
    return target, manifest_path, sha(events_path), sha(manifest_path)


def run_mode(mode: str) -> dict:
    from environments.high_speed import virtual_runtime_replay as replay_module
    from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner

    run_id = f"Q25-A5-S23-S5-STRATEGYHUB-{mode}-20261109"
    group_id = f"S5-S23-STRATEGYHUB-{mode}"
    seed_manifest, seed_events, seed_manifest_sha, seed_events_sha = build_seed(mode, run_id, group_id)
    replay_dir, replay_manifest, replay_events_sha, replay_manifest_sha = build_replay(mode)
    seed_holder: dict[str, object] = {}
    original_attach = replay_module.attach_standard_automated_loop

    def attach_and_restore(bootstrap, **kwargs):
        loop = original_attach(bootstrap, **kwargs)
        if kwargs.get("strategy_keys") != (("track5_gap_divergence", "2.0"),):
            raise AssertionError("S5_STRATEGY_MUST_BE_SOLE_STRATEGYHUB_MEMBER")
        orchestrator = loop.strategy_hub._orchestrator
        strategy = orchestrator._registry.get("track5_gap_divergence", "2.0")
        bridge = loop.multi_leg_bridge
        seed = S5ValidationOnlySeedAdapter(manifest_path=seed_manifest, dataset_path=seed_events).validate()
        identity = OptionInstrumentIdentity(
            SYNTHETIC_ID, SYNTHETIC_ID, EXPIRY, "CALL", STRIKE, MULTIPLIER, IDENTITY_SOURCE,
        )
        event = seed.event
        vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
        seed_tick = CanonicalMarketTick(
            timestamp=str(event["execution_timestamp"]), underlying_price=891.04,
            strike_price=float(STRIKE), option_type="CALL", bid_price=42.25,
            ask_price=42.35, last_price=42.30, expiry=EXPIRY, symbol=SYNTHETIC_ID,
        )
        vssf_runtime.process_market_data(seed_tick)
        open_command = BrokerOrderCommand(
            client_order_id=event["client_order_id"], instrument_id=SYNTHETIC_ID, side="BUY",
            quantity=int(event["opened_quantity"]), order_type="LIMIT", broker_symbol=SYNTHETIC_ID,
            instrument_identity=identity, asset_type="OPTION", requested_price=Decimal(str(event["execution_price"])),
            strategy_id="track5_gap_divergence", order_purpose="VALIDATION_ONLY_PREEXISTING_POSITION",
            track_id="track5_gap_divergence", tag_id="S23_SYNTHETIC_SEED_OPEN",
            group_id=group_id, leg_id=event["leg_id"],
        )
        open_report = bootstrap.bundle.execution.execute(open_command)
        if (open_report.status != "FILLED" or open_report.execution_id != event["execution_id"]
                or open_report.execution_price != Decimal(str(event["execution_price"]))
                or open_report.filled_quantity != int(event["opened_quantity"])):
            raise AssertionError(f"S5_VSSF_SEED_FILL_MISMATCH:{open_report}")
        restored_report = seed.restore_existing_position(
            strategy=strategy, position_lot_store=bridge.position_lot_store, identity=identity,
        )
        key = ("track5_gap_divergence", "2.0")
        orchestrator._initialized.add(key)
        if strategy.state.is_active is not True or strategy.CURRENT_EXECUTION_POLICY_APPROVED is not False:
            raise AssertionError("S5_ACTIVE_SEED_OR_ENTRY_GATE_INVALID")
        if len(bridge.position_lot_store.open_lots()) != 1:
            raise AssertionError("S5_SEED_OPEN_LOT_COUNT_INVALID")
        account_position = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions.get(SYNTHETIC_ID)
        if account_position is None or int(account_position.get("qty", 0) if isinstance(account_position, dict) else getattr(account_position, "quantity", getattr(account_position, "qty", 0))) != 1:
            raise AssertionError(f"S5_VSSF_POSITION_RESTORE_INVALID:{account_position}")
        class SeedOnlyTrack5ContractSource:
            validation_only_max_quote_age_seconds = 5
            def select(self, *, expiry, current_price, option_type, as_of, max_quote_age_seconds):
                if (str(expiry).replace("-", "") != EXPIRY
                        or int(max_quote_age_seconds or 0) != 5 or not getattr(strategy.state, "is_active", False)):
                    raise ValueError("S5_VALIDATION_ACTIVE_POSITION_CONTRACT_CONTEXT_MISMATCH")
                return SimpleNamespace(expiry=EXPIRY, atm_strike=STRIKE, selected_strike=STRIKE,
                                       option_type=strategy.state.option_type, strike_rank=2, liquidity_score=Decimal("1"))
        loop.standard_runtime_input_provider.track5_option_contract_source = SeedOnlyTrack5ContractSource()
        def synthetic_freshness(plan, leg, resolved_identity, command):
            observed = datetime.fromisoformat("2026-10-22T02:16:00+09:00")
            return FreshnessVerdict(
                FreshnessStatus.FRESH, "SYNTHETIC_VALIDATION_ONLY_QUOTE", "s23-synthetic-validation-v1",
                source="SYNTHETIC:DERIVED_SCENARIO", tr_id="S23-SIM", environment="VIRTUAL",
                instrument_id=resolved_identity.instrument_id, symbol=resolved_identity.symbol,
                source_instant=observed, received_at=observed, evidence_sha256=seed.dataset_sha256,
            )
        bridge.freshness_verdict_provider = synthetic_freshness
        context_debug = []
        original_context_builder = loop.context_builder
        def capture_context(tick, state):
            contexts = original_context_builder(tick, state)
            ctx = contexts.get("track5_gap_divergence")
            if ctx is not None and ctx.analytics is not None:
                metric = ctx.analytics.get("price.last")
                expected_underlying = Decimal(str(tick.underlying_price))
                if metric is None or metric.value != expected_underlying:
                    raise AssertionError(f"TRACK5_PRICE_LAST_NOT_UNDERLYING:{metric!r}:{expected_underlying}")
                if ctx.input is None or ctx.input.common is None or ctx.input.common.current_price != expected_underlying:
                    raise AssertionError(f"TRACK5_COMMON_CURRENT_PRICE_NOT_UNDERLYING:{ctx.input!r}:{expected_underlying}")
            if ctx is not None:
                context_debug.append({"input": repr(ctx.input), "analytics": repr(ctx.analytics), "data_status": repr(getattr(ctx.input, "data_status", None))})
            return contexts
        loop.context_builder = capture_context
        original_hub_run = loop.strategy_hub.run
        def capture_hub_run(contexts, selected=None):
            result = original_hub_run(contexts, selected=selected)
            seed_holder.setdefault("strategy_failures", []).append([repr(item) for item in result.failures])
            return result
        loop.strategy_hub.run = capture_hub_run
        seed_holder.update({"loop": loop, "strategy": strategy, "bridge": bridge,
                            "seed_report": restored_report, "open_report": open_report,
                            "seed_sha256": seed.dataset_sha256, "context_debug": context_debug})
        return loop

    replay_module.attach_standard_automated_loop = attach_and_restore
    try:
        trace_path = ROOT / f"reports/synth/traces/Q25_A5_S23_S5_STRATEGYHUB_{mode}_TRACE_20261109_RETRY13.jsonl"
        if mode == "DETAILED" and trace_path.exists():
            raise FileExistsError(f"REFUSE_OVERWRITE:{trace_path}")
        runner = HighSpeedVirtualRuntimeReplayRunner(
            replay_dir, run_id=run_id, strategy_keys=(("track5_gap_divergence", "2.0"),),
            validation_only_synthetic=True, log_mode=mode.lower(),
            trace_output=trace_path if mode == "DETAILED" else None,
        )
        report = runner.run()
    finally:
        replay_module.attach_standard_automated_loop = original_attach

    loop = seed_holder["loop"]
    strategy = seed_holder["strategy"]
    bridge = seed_holder["bridge"]
    vssf = loop.bundle.execution._authoritative_execute.__self__.vssf_runtime
    observer = report.execution_observer_summary
    ack_report = bridge.ack.last_report
    if ack_report is None or ack_report.group_id != group_id or not str(ack_report.leg_id or "").startswith("OPTION_EXIT-"):
        raise AssertionError(f"VSSF_GROUP_LEG_METADATA_MISSING:{ack_report!r}")
    trace_report_metadata = None
    if mode == "DETAILED":
        trace_rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        order_row = next(row for row in trace_rows if row.get("event_type") == "order_command")
        report_row = next(row for row in trace_rows if row.get("event_type") == "execution_report")
        command_data = order_row["payload"]["command"]
        report_data = report_row["payload"]["report"]
        if report_data.get("group_id") != command_data.get("group_id") or report_data.get("leg_id") != command_data.get("leg_id"):
            raise AssertionError(f"TRACE_GROUP_LEG_METADATA_MISMATCH:{command_data!r}:{report_data!r}")
        trace_report_metadata = {"group_id": report_data["group_id"], "leg_id": report_data["leg_id"]}
    result = {
        "mode": mode, "run_id": report.run_id, "events": report.events,
        "signals": report.signals, "approved": report.approved, "routed": report.routed,
        "filled": report.filled, "rejected": report.rejected,
        "execution_ids": list(report.execution_ids), "exhausted": report.exhausted,
        "strategy_signal_counts": dict(report.strategy_signal_counts),
        "strategy_status": [item.__dict__ for item in report.strategy_status],
        "trace_status": report.trace_status, "observer": observer,
        "raw_execution_report_group_id": ack_report.group_id, "raw_execution_report_leg_id": ack_report.leg_id,
        "trace_report_metadata": trace_report_metadata,
        "open_lots_after": len(bridge.position_lot_store.open_lots()),
        "strategy_active_after": strategy.state.is_active,
        "entry_policy_approved": strategy.CURRENT_EXECUTION_POLICY_APPROVED,
        "group_metadata_preserved": ack_report.group_id == group_id,
        "leg_metadata_preserved": str(ack_report.leg_id or "").startswith("OPTION_EXIT-"),
        "runtime_config_verified": strategy.runtime_config_verified,
        "risk_limits_available": strategy.risk_limits_available,
        "vssf_positions_after": {key: getattr(value, "quantity", getattr(value, "qty", value))
                                  for key, value in vssf.account.positions.items()},
        "seed_manifest_sha256": seed_manifest_sha,
        "seed_events_sha256": seed_events_sha,
        "replay_manifest_sha256": replay_manifest_sha,
        "replay_events_sha256": replay_events_sha,
        "trace_sha256": sha(trace_path) if mode == "DETAILED" else None,
    }
    assert report.events == 2 and report.exhausted is True
    if any(seed_holder.get("strategy_failures", [])):
        raise AssertionError(f"STRATEGYHUB_RUNTIME_FAILURES:{seed_holder.get("strategy_failures")!r}")
    if not (report.signals == 1 and report.approved == 1 and report.routed == 1 and report.filled == 1):
        raise AssertionError(f"INTEGRATED_RUNTIME_NO_CLOSE report={report!r} status={report.strategy_status!r} state={strategy.state!r} quote_only={loop.quote_only_events!r} context_debug={seed_holder.get("context_debug")!r} failures={seed_holder.get("strategy_failures")!r}")
    assert report.rejected == 0 and len(report.execution_ids) == 1
    track5_status = next(item for item in report.strategy_status if item.strategy_id == "track5_gap_divergence")
    assert track5_status.unavailable == 0 and track5_status.runtime_failures == 0
    assert result["open_lots_after"] == 0 and result["strategy_active_after"] is False
    assert result["entry_policy_approved"] is False
    assert result["runtime_config_verified"] is False and result["risk_limits_available"] is False
    assert not result["vssf_positions_after"]
    if mode == "DETAILED":
        assert observer.get("order_commands_observed") == 1
        assert observer.get("execution_reports_observed") == 1
        assert observer.get("fills_observed") == 1
    else:
        assert observer.get("status") == "DISABLED_FAST_MODE"
    return result


def main() -> dict:
    fast = run_mode("FAST")
    detailed = run_mode("DETAILED")
    parity_keys = ("events", "signals", "approved", "routed", "filled", "rejected", "execution_ids",
                   "exhausted", "strategy_signal_counts", "open_lots_after", "strategy_active_after",
                   "entry_policy_approved", "runtime_config_verified", "risk_limits_available", "vssf_positions_after", "group_metadata_preserved", "leg_metadata_preserved")
    assert {key: fast[key] for key in parity_keys} == {key: detailed[key] for key in parity_keys}
    result = {
        "status": "PSB_PASS_VALIDATION_ONLY_SYNTHETIC_STRATEGYHUB_RUNTIME_FAST_DETAILED_PARITY",
        "ssot_sha256": SSOT_SHA,
        "applied_ssot_ids": ["CB2-01", "CB2-02", "CB2-03", "CB2-04", "CB2-05", "CB2-06", "CB2-09"],
        "fast": fast, "detailed": detailed, "semantic_parity": True,
        "boundaries": {
            "source_fill_is_historical": False, "track5_state_is_historical": False,
            "replay_ticks_are_actual_kis_ticks": False, "quotes_are_actual_kis_quotes": False,
            "fee_is_actual_kis_fee": False, "risk_guard_green_is_operational_health": False,
            "production_runtime_eligible": False, "kis_api_called": False,
            "real_vts_api_called": False, "live_api_called": False,
            "account_api_called": False, "external_order_submitted": False,
        },
    }
    output = ROOT / "reports/synth/Q25_A5_S23_S5_STRATEGYHUB_RUNTIME_REPLAY_20261109_RETRY13.json"
    if output.exists():
        raise FileExistsError(f"REFUSE_OVERWRITE:{output}")
    write_json(output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return result


if __name__ == "__main__":
    main()