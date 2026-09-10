from dataclasses import dataclass
from enum import Enum

class LiveApprovalState(str, Enum):
    DISARMED = "DISARMED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"

@dataclass(frozen=True)
class LiveSafetyPolicy:
    approval_state: LiveApprovalState = LiveApprovalState.DISARMED
    kill_switch: bool = True
    max_order_quantity: int = 0
    max_daily_loss: float = 0.0
    max_position_quantity: int = 0
    max_account_staleness_seconds: float = 5.0

    @property
    def can_submit(self) -> bool:
        return (
            not self.kill_switch
            and self.max_order_quantity > 0
            and self.max_daily_loss > 0
            and self.max_position_quantity > 0
        )

@dataclass(frozen=True)
class LiveCredentialRef:
    app_key_env: str = "KIS_REAL_APP_KEY"
    app_secret_env: str = "KIS_REAL_APP_SECRET"
    account_env: str = "KIS_REAL_ACCOUNT_NO"
    base_url_env: str = "KIS_REAL_BASE_URL"

@dataclass(frozen=True)
class LiveApproval:
    approved_by: str
    approved_at: str
    reason: str
