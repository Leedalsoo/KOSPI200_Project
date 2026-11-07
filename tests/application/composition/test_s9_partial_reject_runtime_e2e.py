from __future__ import annotations

from pathlib import Path

from contracts.types import ExecutionReport
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from environments.high_speed.virtual_runtime_replay import HighSpeedVirtualRuntimeReplayRunner
from environments.high_speed.replay_trace import ReplayLogMode

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/derived_scenario/q25_s9_independent_overnight_stop_loss_20261108"
MANIFEST = DATA / "manifest.json"
CONTRACT = ROOT / "config/validation_only/track9_independent_synthetic_contract_profile.json"
RISK = ROOT / "config/validation_only/q25_s9_independent_overnight_20261108/risk_profile.json"


class _RejectCallOnlyBroker:
    def __init__(self, delegate):
        self.delegate = delegate

    def submit(self, command):
        if str(getattr(command, "leg_id", "")) == "call":
            return ExecutionReport(
                client_order_id=command.client_order_id,
                broker_order_id=None,
                execution_id=None,
                status="REJECTED",
                filled_quantity=0,
                remaining_quantity=int(command.quantity),
                execution_price=None,
                execution_timestamp=None,
                rejected_reason="SYNTHETIC_FAULT_INJECTION_CALL_LEG_REJECTED",
                group_id=command.group_id,
                leg_id=command.leg_id,
            )
        return self.delegate.submit(command)

    def query(self, client_order_id):
        return self.delegate.query(client_order_id)


def test_s9_natural_signal_one_leg_rejection_keeps_unpaired_position_fail_closed(monkeypatch):
    bridges = []
    original_init = VirtualMultiLegExecutionBridge.__init__

    def patched_init(self, **kwargs):
        original_init(self, **kwargs)
        self.ack.broker = _RejectCallOnlyBroker(self.ack.broker)
        bridges.append(self)

    monkeypatch.setattr(VirtualMultiLegExecutionBridge, "__init__", patched_init)
    runner = HighSpeedVirtualRuntimeReplayRunner(
        DATA,
        run_id="S9-ONE-LEG-REJECT-20261108",
        strategy_keys=(("track9_event_overnight_insurance", "3.0"),),
        validation_only_synthetic=True,
        validation_only_synthetic_manifest=MANIFEST,
        validation_only_s9_contract_profile=CONTRACT,
        validation_only_s9_risk_profile=RISK,
        log_mode=ReplayLogMode.FAST,
    )
    report = runner.run(max_events=2)

    assert len(bridges) >= 2
    bridge = bridges[-1]
    assert runner.s9_strategy is not None
    assert runner.s9_strategy.state.state == "RECONCILIATION_REQUIRED"
    assert report.signals == 1
    assert report.routed == 2
    assert report.filled == 1
    assert report.rejected == 1

    groups = bridge.position_groups.all()
    assert len(groups) == 1
    group = next(iter(groups.values()))
    assert {leg.leg_id: leg.status.value for leg in group.legs} == {
        "put": "FILLED",
        "call": "REJECTED",
    }
    lots = bridge.position_lot_store.open_lots()
    assert len(lots) == 1
    assert lots[0].instrument_identity.option_type == "PUT"
    assert lots[0].remaining_quantity == 1
