from dataclasses import dataclass

@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    reason: str

class LiveRecovery:
    def decide(self, reconciliation_consistent: bool, broker_connected: bool) -> RecoveryDecision:
        if not broker_connected:
            pass
            return RecoveryDecision("SAFE_STOP", "broker disconnected")
        if not reconciliation_consistent:
            pass
            return RecoveryDecision("SAFE_STOP", "broker/internal state mismatch")
        return RecoveryDecision("RESUME_ALLOWED", "state reconciled")
