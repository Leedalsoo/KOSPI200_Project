from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner
from environments.virtual.validation_only_option_expiry_settlement import (
    ValidationOnlyExpirySettlementProfile,
    ValidationOnlyOptionExpiryCashSettlementAdapter,
)

STRATEGY = "track8_macro_regime_monthly_strangle"
PROFILE_PATH = ROOT / "config/validation_only/q25_s8_v3/expiry_settlement_profile_v1.json"
OUTPUT = ROOT / "reports/synth/Q25_S8_VALIDATION_ONLY_EXPIRY_SETTLEMENT_V3_20261105.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_scenario(regime: str, profile_payload: dict[str, Any], profile) -> dict[str, Any]:
    folder = ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly" / regime
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    risk_profile = ROOT / "config/validation_only/q25_s8_v3" / regime / "risk_profile.json"
    run_id = f"Q25-S8-EXPIRY-VALIDATION-{regime.upper()}-20261105"
    captured: list[VirtualMultiLegExecutionBridge] = []
    original_init = VirtualMultiLegExecutionBridge.__init__

    def capture_init(bridge, *args, **kwargs):
        original_init(bridge, *args, **kwargs)
        captured.append(bridge)

    runner = HighSpeedVirtualRuntimeReplayRunner(
        folder,
        run_id=run_id,
        strategy_keys=((STRATEGY, "2.0"),),
        validation_only_synthetic=True,
        validation_only_synthetic_manifest=manifest_path,
        validation_only_s8_risk_profile=risk_profile,
    )
    with patch.object(VirtualMultiLegExecutionBridge, "__init__", capture_init):
        replay_report = runner.run()
    if not captured or replay_report.filled < 2:
        raise AssertionError("S8_EXPIRY_NATURAL_ENTRY_REQUIRED")
    bridge = captured[-1]
    groups = bridge.position_groups.all()
    if len(groups) != 1:
        raise AssertionError(f"S8_EXPIRY_SINGLE_GROUP_REQUIRED:{len(groups)}")
    group_id, group = next(iter(groups.items()))
    if not group.is_complete or len(group.legs) != 2:
        raise AssertionError("S8_EXPIRY_ENTRY_GROUP_INCOMPLETE")
    lots = tuple(bridge.position_lot_store.open_lots())
    if len(lots) != 2 or sum(lot.remaining_quantity for lot in lots) != 2:
        raise AssertionError("S8_EXPIRY_ENTRY_LOTS_INVALID")

    expiry = str(lots[0].instrument_identity.expiry)
    if any(str(lot.instrument_identity.expiry) != expiry for lot in lots):
        raise AssertionError("S8_EXPIRY_LEG_EXPIRY_MISMATCH")
    scenario_id = str(manifest["scenario_id"])
    settlement_price = profile.settlement_price_by_scenario[scenario_id]
    fixture = {
        "scenario_id": scenario_id,
        "expiry": expiry,
        "underlying_settlement_price": settlement_price,
        "source": profile.settlement_price_source,
        "profile_sha256": profile.profile_sha256,
    }
    fixture_hash = hashlib.sha256(
        json.dumps(fixture, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    adapter = ValidationOnlyOptionExpiryCashSettlementAdapter(
        manifest=manifest, profile=profile,
    )
    result = adapter.settle_group(
        bridge=bridge,
        group_id=group_id,
        settlement_id=f"{run_id}:{group_id}:{expiry}",
        settlement_date=expiry,
        underlying_settlement_price=settlement_price,
        settlement_source_payload=fixture,
        settlement_source_sha256=fixture_hash,
    )
    if result["flat_state_reconciliation"] != "PASS":
        raise AssertionError("S8_EXPIRY_FLAT_RECONCILIATION_FAILED")
    if result["realized_pnl_reconciliation"] != "PASS":
        raise AssertionError("S8_EXPIRY_PNL_RECONCILIATION_FAILED")
    if bridge.position_lot_store.open_lots():
        raise AssertionError("S8_EXPIRY_POSITION_LOTS_NOT_FLAT")
    account = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account
    if account.positions or account.unrealized_pnl != 0:
        raise AssertionError("S8_EXPIRY_ACCOUNT_NOT_FLAT")
    snapshot = bridge.position_groups.snapshot(group_id)
    if snapshot is None or any(leg.quantity != 0 for leg in snapshot.legs):
        raise AssertionError("S8_EXPIRY_GROUP_NOT_FLAT")
    return {
        "scenario": regime.upper(),
        "run_id": run_id,
        "natural_replay": {
            "events": replay_report.events,
            "signals": replay_report.signals,
            "approved": replay_report.approved,
            "routed": replay_report.routed,
            "filled": replay_report.filled,
            "rejected": replay_report.rejected,
        },
        "entry_lots": [{
            "instrument_id": lot.instrument_id,
            "leg_id": lot.leg_id,
            "side": lot.side,
            "quantity": lot.remaining_quantity,
            "entry_execution_id": lot.execution_id,
            "entry_price": str(next(
                record.executed_price
                for record in bridge.fee_ledger.snapshot(run_id=run_id)
                if record.execution_id == lot.execution_id
            )),
            "contract_multiplier": str(lot.contract_multiplier),
        } for lot in lots],
        "settlement": result,
        "final_group_snapshot": {
            "realized_pnl_krw": str(snapshot.realized_pnl),
            "unrealized_pnl_krw": str(snapshot.unrealized_pnl),
            "total_pnl_krw": str(snapshot.total_pnl),
            "leg_quantities": [leg.quantity for leg in snapshot.legs],
        },
        "final_account": {
            "realized_pnl_krw": str(account.realized_pnl),
            "unrealized_pnl_krw": str(account.unrealized_pnl),
            "balance_krw": str(account.balance),
            "positions": account.positions,
        },
        "profile_sha256": profile.profile_sha256,
        "manifest_sha256": sha256(manifest_path),
        "dataset_sha256": sha256(folder / manifest["output_path"].split("/")[-1]),
        "risk_profile_sha256": sha256(risk_profile),
    }


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"REFUSING_TO_OVERWRITE_RESULT:{OUTPUT.name}")
    payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profile = ValidationOnlyExpirySettlementProfile.from_mapping(payload)
    results = [
        run_scenario("normal", payload, profile),
        run_scenario("high_vol", payload, profile),
    ]
    document = {
        "scope": "VALIDATION_ONLY_DERIVED_SCENARIO_VIRTUAL_S8",
        "production_authority": "NOT_GRANTED",
        "expiry_settlement": results,
        "profile": payload,
        "result_status": "PASS_VALIDATION_ONLY",
        "limitations": [
            "Synthetic expiry prices are test fixtures, not exchange final settlement prices.",
            "The 250000 multiplier is a standard-option validation benchmark, not a KIS identity field assertion.",
            "3000 KRW per contract per side is a validation fee benchmark, not an actual broker fee schedule.",
            "No KIS API, REAL_VTS, Live or real-account API was called.",
        ],
    }
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({
        "result_path": str(OUTPUT.relative_to(ROOT)),
        "result_sha256": sha256(OUTPUT),
        "profile_sha256": profile.profile_sha256,
        "scenarios": [{
            "scenario": item["scenario"],
            "signals": item["natural_replay"]["signals"],
            "fills": item["natural_replay"]["filled"],
            "settlement_status": item["settlement"]["status"],
            "gross_pnl_krw": item["settlement"]["gross_realized_pnl_krw"],
            "fees_krw": item["settlement"]["total_commission_krw"],
            "net_pnl_krw": item["settlement"]["net_realized_pnl_krw"],
            "flat": item["settlement"]["flat_state_reconciliation"],
            "pnl_reconciliation": item["settlement"]["realized_pnl_reconciliation"],
        } for item in results],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
