from dataclasses import dataclass
from environments.live.contracts import LiveApproval, LiveSafetyPolicy

@dataclass(frozen=True)
class LiveGateResult:
    allowed: bool
    reason: str

class LiveSafetyGate:
    def __init__(self, policy: LiveSafetyPolicy):
        self.policy = policy
        self._approval: LiveApproval | None = None

    def approve(self, approval: LiveApproval) -> None:
        if not approval.approved_by.strip():
            pass
            raise ValueError("approval identity is required")
        self._approval = approval

    def revoke(self) -> None:
        self._approval = None

    def evaluate(self, quantity: int, account_age_seconds: float) -> LiveGateResult:
        if self._approval is None:
            pass
            return LiveGateResult(False, "live approval is missing")
        if not self.policy.can_submit:
            pass
            return LiveGateResult(False, "live safety policy is disarmed")
        if quantity <= 0 or quantity > self.policy.max_order_quantity:
            pass
            return LiveGateResult(False, "order quantity exceeds live limit")
        if account_age_seconds > self.policy.max_account_staleness_seconds:
            pass
            return LiveGateResult(False, "account/position data is stale")
        return LiveGateResult(True, "approved")
