from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

class U18ExitDecision(str, Enum):
    POLICY_INPUT_BLOCKED = "POLICY_INPUT_BLOCKED"
    EVIDENCE_BLOCKED = "EVIDENCE_BLOCKED"
    HOLD = "HOLD"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_EXIT = "TRAILING_EXIT"

@dataclass(frozen=True)
class U18ExitPolicy:
    stop_loss_ratio: Decimal | None = None
    trailing_activation_ratio: Decimal | None = None
    trailing_pullback_ratio: Decimal | None = None

    def resolved(self) -> bool:
        return bool(
            self.stop_loss_ratio is not None and self.stop_loss_ratio < 0
            and self.trailing_activation_ratio is not None and self.trailing_activation_ratio > 0
            and self.trailing_pullback_ratio is not None
            and Decimal("0") < self.trailing_pullback_ratio <= Decimal("1")
        )

@dataclass(frozen=True)
class U18GroupPnlEvidence:
    complete_four_legs: bool
    all_marks_are_bid_ask_mid: bool
    initial_net_premium_received: Decimal | None
    realized_and_unrealized_fees_present: bool
    realized_and_unrealized_slippage_present: bool
    net_pnl_after_costs: Decimal | None
    quote_freshness_verified: bool

@dataclass(frozen=True)
class U18ExitResult:
    decision: U18ExitDecision
    reason: str
    net_pnl_ratio: Decimal | None = None
    peak_pnl_ratio: Decimal | None = None
    pullback_ratio: Decimal | None = None
    order_submission_enabled: bool = False

def evaluate_u18_exit(*, evidence, policy, peak_pnl_ratio):
    if not policy.resolved():
        return U18ExitResult(U18ExitDecision.POLICY_INPUT_BLOCKED, "U18_EXIT_RATIOS_UNRESOLVED_NULL_DEFAULT")
    if evidence is None or not (
        evidence.complete_four_legs and evidence.all_marks_are_bid_ask_mid
        and evidence.initial_net_premium_received is not None
        and evidence.initial_net_premium_received > 0
        and evidence.realized_and_unrealized_fees_present
        and evidence.realized_and_unrealized_slippage_present
        and evidence.net_pnl_after_costs is not None
        and evidence.quote_freshness_verified
    ):
        return U18ExitResult(U18ExitDecision.EVIDENCE_BLOCKED, "FOUR_LEG_MID_COST_AND_FRESHNESS_EVIDENCE_REQUIRED")
    ratio = evidence.net_pnl_after_costs / evidence.initial_net_premium_received
    peak = max(peak_pnl_ratio if peak_pnl_ratio is not None else ratio, ratio)
    if ratio <= policy.stop_loss_ratio:
        return U18ExitResult(U18ExitDecision.STOP_LOSS, "NET_LOSS_RATIO_AT_OR_BELOW_EXPLICIT_LIMIT", ratio, peak)
    pullback = (peak - ratio) / peak if peak > 0 else Decimal("0")
    if peak >= policy.trailing_activation_ratio and pullback >= policy.trailing_pullback_ratio:
        return U18ExitResult(U18ExitDecision.TRAILING_EXIT, "PEAK_NET_PNL_PULLBACK_AT_OR_ABOVE_EXPLICIT_LIMIT", ratio, peak, pullback)
    return U18ExitResult(U18ExitDecision.HOLD, "NO_EXIT_THRESHOLD_CROSSED", ratio, peak, pullback)
