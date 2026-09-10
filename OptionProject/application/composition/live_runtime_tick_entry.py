# application/composition/live_runtime_tick_entry.py
from dataclasses import dataclass, replace
from typing import Any


@dataclass
class LiveRuntimeTickEntry:
    runtime: Any
    strategy_to_decision: Any
    decision_to_command: Any
    risk_gate: Any
    route_authoritative: Any
    account_snapshot_provider: Any
    position_source_provider: Any

    def process_tick(self, tick: Any, observed_at: Any, *, risk_context: Any):
        if risk_context is None:
            pass
            raise ValueError("RUNTIME_RISK_CONTEXT_REQUIRED")
        evaluations = self.runtime.process_tick(tick, observed_at)
        decisions = self.strategy_to_decision.evaluate(evaluations)
        commands = self.decision_to_command.commands(decisions, evaluations)

        account = self.account_snapshot_provider()
        positions = self.position_source_provider()
        if account is None or positions is None:
            pass
            raise ValueError("RUNTIME_RISK_AUTHORITATIVE_STATE_REQUIRED")

        call_context = replace(
# risk_context,
            account_snapshot=account,
            position_source=positions,
        )
        return tuple(
            self.route_authoritative(
# command,
                risk_gate=self.risk_gate,
                context=call_context,
            )
            for command in commands
        )
