from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Iterable
from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyEvaluation
from contracts.cancel_order import CancelPendingOrdersRequest
from contracts.types import MultiLegDecision, MultiLegExecutionPlan, OptionInstrumentIdentity
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from core.decision.decision_arbiter import ArbitrationResult, DecisionArbiter
from core.strategy.canonical_signal_adapter import RuntimeSignalContext, signal_to_canonical
from core.strategy.contracts import SignalKind
from shared.contracts.canonical import CanonicalStrategySignal

InstrumentIdentityProvider = Callable[[RuntimeStrategyEvaluation, Any], OptionInstrumentIdentity | FuturesInstrumentIdentity | None]
MultiLegPlanResolver = Callable[[RuntimeStrategyEvaluation, CanonicalStrategySignal], MultiLegExecutionPlan | None]
PendingOrderIdsProvider = Callable[[str], tuple[str, ...]]

@dataclass(frozen=True)
class RuntimeDecisionResult:
    canonical_signals: tuple[CanonicalStrategySignal, ...]
    arbitration: ArbitrationResult
    multi_leg_decisions: tuple[MultiLegDecision, ...] = ()
    cancel_requests: tuple[CancelPendingOrdersRequest, ...] = ()

class RuntimeStrategyToDecisionAdapter:
    def __init__(self, arbiter: DecisionArbiter) -> None:
        self._arbiter = arbiter

    def arbitrate(self, evaluations: Iterable[RuntimeStrategyEvaluation], *, price: float, timestamp: str, account: Any, instrument_identity_provider: InstrumentIdentityProvider | None = None, market_tick: Any | None = None, multi_leg_plan_resolver: MultiLegPlanResolver | None = None, pending_order_ids_provider: PendingOrderIdsProvider | None = None) -> RuntimeDecisionResult:
        evaluations = tuple(evaluations)
        canonical_signals: list[CanonicalStrategySignal] = []
        evaluation_by_signal_id: dict[str, RuntimeStrategyEvaluation] = {}
        seen_signal_ids: set[str] = set()
        cancel_requests: list[CancelPendingOrdersRequest] = []
        for evaluation in evaluations:
            signal = evaluation.result
            kind = SignalKind(getattr(signal, "kind", SignalKind.EXECUTION))
            if kind is SignalKind.NON_EXECUTION:
                continue
            track_id = str(getattr(evaluation.context, "strategy_id", "") or "").strip()
            if not track_id:
                raise ValueError("RUNTIME_TRACK_ID_REQUIRED")
            signal_id = evaluation.runtime_context.signal_id(track_id)
            if signal_id in seen_signal_ids:
                raise ValueError("RUNTIME_DUPLICATE_SIGNAL_ID")
            seen_signal_ids.add(signal_id)
            direction = str(getattr(signal, "direction", "") or "")
            if direction in {"CANCEL", "CANCEL_PENDING_TRANCHES"}:
                if pending_order_ids_provider is None:
                    raise ValueError("CANCEL_PENDING_ORDER_SOURCE_REQUIRED")
                cancel_requests.append(CancelPendingOrdersRequest(
                    signal_id=signal_id,
                    strategy_id=track_id,
                    client_order_ids=tuple(pending_order_ids_provider(track_id)),
                ))
                continue
            if getattr(signal, "execution_proposal", None) is None:
                raise ValueError("EXECUTION_PROPOSAL_REQUIRED")
            evaluation_by_signal_id[signal_id] = evaluation
            identity = instrument_identity_provider(evaluation, market_tick) if instrument_identity_provider is not None else None
            canonical_signals.append(signal_to_canonical(signal, RuntimeSignalContext(signal_id=signal_id, track_id=track_id, price=price, timestamp=timestamp), instrument_identity=identity))
        arbitration = self._arbiter.arbitrate(canonical_signals, account)
        approved_ids = {signal.signal_id for signal in arbitration.approved_signals}
        multi_leg_decisions: list[MultiLegDecision] = []
        if multi_leg_plan_resolver is not None:
            for canonical in canonical_signals:
                if canonical.signal_id not in approved_ids:
                    continue
                evaluation = evaluation_by_signal_id[canonical.signal_id]
                plan = multi_leg_plan_resolver(evaluation, canonical)
                if plan is None:
                    continue
                if plan.strategy_id != canonical.track_id:
                    raise ValueError("MULTI_LEG_STRATEGY_ID_MISMATCH")
                multi_leg_decisions.append(
                    MultiLegDecision(
                        signal_id=canonical.signal_id,
                        strategy_id=canonical.track_id,
                        plan=plan,
                    )
                )
        return RuntimeDecisionResult(
            canonical_signals=tuple(canonical_signals),
            arbitration=arbitration,
            multi_leg_decisions=tuple(multi_leg_decisions),
            cancel_requests=tuple(cancel_requests),
        )
