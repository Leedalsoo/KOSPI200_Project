from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.types import ExecutionReport
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner
from environments.high_speed.replay_trace import ReplayLogMode

DATA = ROOT / "data/derived_scenario/q25_s9_independent_overnight_stop_loss_20261108"
MANIFEST = DATA / "manifest.json"
CONTRACT = ROOT / "config/validation_only/track9_independent_synthetic_contract_profile.json"
RISK = ROOT / "config/validation_only/q25_s9_independent_overnight_20261108/risk_profile.json"
REPORT = ROOT / "reports/synth/S9_INDEPENDENT_ATM_OVERNIGHT_ONE_LEG_REJECT_E2E_20261108.json"


class RejectCallOnlyBroker:
    def __init__(self, delegate):
        self.delegate = delegate

    def submit(self, command):
        if str(getattr(command, "leg_id", "")) == "call":
            return ExecutionReport(
                client_order_id=command.client_order_id, broker_order_id=None,
                execution_id=None, status="REJECTED", filled_quantity=0,
                remaining_quantity=int(command.quantity), execution_price=None,
                execution_timestamp=None,
                rejected_reason="SYNTHETIC_FAULT_INJECTION_CALL_LEG_REJECTED",
                group_id=command.group_id, leg_id=command.leg_id,
            )
        return self.delegate.submit(command)

    def query(self, client_order_id):
        return self.delegate.query(client_order_id)


def main() -> None:
    if REPORT.exists() or REPORT.with_suffix(".json.sha256").exists():
        raise RuntimeError("REFUSE_OVERWRITE_EXISTING_S9_REJECT_ARTIFACT")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if any(value != "MISSING" for value in manifest["official_data_status"].values()):
        raise RuntimeError("OFFICIAL_DATA_MUST_REMAIN_MISSING")
    bridges = []
    original_init = VirtualMultiLegExecutionBridge.__init__

    def patched_init(self, **kwargs):
        original_init(self, **kwargs)
        self.ack.broker = RejectCallOnlyBroker(self.ack.broker)
        bridges.append(self)

    VirtualMultiLegExecutionBridge.__init__ = patched_init
    try:
        runner = HighSpeedVirtualRuntimeReplayRunner(
            DATA, run_id="S9-ONE-LEG-REJECT-20261108",
            strategy_keys=(("track9_event_overnight_insurance", "3.0"),),
            validation_only_synthetic=True,
            validation_only_synthetic_manifest=MANIFEST,
            validation_only_s9_contract_profile=CONTRACT,
            validation_only_s9_risk_profile=RISK,
            log_mode=ReplayLogMode.FAST,
        )
        replay = runner.run(max_events=2)
    finally:
        VirtualMultiLegExecutionBridge.__init__ = original_init

    if len(bridges) < 2 or runner.s9_strategy is None:
        raise RuntimeError("S9_RUNTIME_BRIDGE_OR_STRATEGY_MISSING")
    bridge = bridges[-1]
    groups = bridge.position_groups.all()
    if len(groups) != 1:
        raise RuntimeError("S9_ONE_LEG_REJECT_GROUP_COUNT_INVALID")
    group = next(iter(groups.values()))
    leg_statuses = {leg.leg_id: leg.status.value for leg in group.legs}
    lots = bridge.position_lot_store.open_lots()
    checks = {
        "natural_signal": replay.signals == 1,
        "route_attempts": replay.routed == 2,
        "one_filled_leg": replay.filled == 1,
        "one_rejected_leg": replay.rejected == 1,
        "put_filled_call_rejected": leg_statuses == {"put": "FILLED", "call": "REJECTED"},
        "single_open_put_lot": len(lots) == 1 and lots[0].instrument_identity.option_type == "PUT" and lots[0].remaining_quantity == 1,
        "strategy_fail_closed": runner.s9_strategy.state.state == "RECONCILIATION_REQUIRED",
    }
    if not all(checks.values()):
        raise RuntimeError(f"S9_ONE_LEG_REJECT_ASSERTION_FAILED:{checks}")
    risk = json.loads(RISK.read_text(encoding="utf-8"))
    result = {
        "status": "PSB_PASS",
        "scope": "S9 natural-signal Virtual runtime with deterministic synthetic CALL-leg rejection after PUT-leg fill",
        "interpretation": "PASS only for detecting and fail-closing an unpaired position; automatic hedge/unwind policy remains unresolved and is not claimed",
        "scenario_id": manifest["scenario_id"],
        "run_id": runner.run_id,
        "provenance": "SYNTHETIC/DERIVED_SCENARIO",
        "events": replay.events,
        "natural_signals": replay.signals,
        "route_attempts": replay.routed,
        "filled_quantity": replay.filled,
        "rejected_orders": replay.rejected,
        "position_group_leg_status": leg_statuses,
        "strategy_state": runner.s9_strategy.state.state,
        "open_lots": [{
            "instrument_id": lot.instrument_id,
            "option_type": lot.instrument_identity.option_type,
            "remaining_quantity": lot.remaining_quantity,
            "execution_id": lot.execution_id,
            "identity_source": lot.instrument_identity.identity_source,
        } for lot in lots],
        "position_flat": False,
        "checks": checks,
        "quantity_constraint": {
            "max_quantity_per_leg": risk["limits"]["max_quantity_per_leg"],
            "partial_fill_note": "Current approved synthetic validation profile limits each leg to one indivisible contract; multi-fill partial quantity is not representable without changing the unresolved P1 quantity policy.",
        },
        "official_data_status": manifest["official_data_status"],
        "synthetic_contract_multiplier": 100000,
        "synthetic_tradeable": True,
        "production_runtime_eligible": False,
        "orders_allowed": False,
        "kis_real_vts_live_or_real_account_used": False,
        "fault_injection": "Reject CALL leg only; PUT leg delegated to the actual Virtual Broker",
        "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "dataset_sha256": hashlib.sha256((DATA / "20261106.jsonl").read_bytes()).hexdigest(),
        "contract_profile_sha256": hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
        "risk_profile_sha256": hashlib.sha256(RISK.read_bytes()).hexdigest(),
    }
    payload = (json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    REPORT.with_suffix(".json.sha256").write_text(f"{digest}  {REPORT.name}\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "strategy_state": result["strategy_state"],
                      "leg_statuses": leg_statuses, "open_lots": len(lots),
                      "position_flat": result["position_flat"], "checks": checks,
                      "report": REPORT.relative_to(ROOT).as_posix(), "sha256": digest},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
