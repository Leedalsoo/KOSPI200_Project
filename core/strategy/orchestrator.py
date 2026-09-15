"""Environment-neutral lifecycle orchestrator for registered strategies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from core.strategy.contracts import Signal, StrategyContext, UnavailableStrategyPayload
from core.strategy.registry import StrategyRegistry


StrategyKey = Tuple[str, str]


@dataclass(frozen=True)
class StrategyRunFailure:
    strategy_id: str
    version: str
    stage: str
    error_type: str
    message: str


@dataclass(frozen=True)
class StrategyRunResult:
    signals: Tuple[Signal, ...]
    failures: Tuple[StrategyRunFailure, ...]


class StrategyOrchestrator:
    """Runs the standard Strategy lifecycle without Runtime/Broker/UI dependency."""

    def __init__(
        self,
        registry: StrategyRegistry,
        strategy_keys: Iterable[StrategyKey],
    ) -> None:
        self._registry = registry
        self._strategy_keys = tuple(strategy_keys)
        self._enabled: Dict[StrategyKey, bool] = {
            key: True for key in self._strategy_keys
        }
        self._initialized: set[StrategyKey] = set()

    def set_enabled(
        self,
        strategy_id: str,
        version: str,
        enabled: bool,
    ) -> None:
        key = (strategy_id, version)
        if key not in self._enabled:
            raise KeyError(f"strategy not managed: {key}")
        self._enabled[key] = enabled

    def is_enabled(self, strategy_id: str, version: str) -> bool:
        return self._enabled[(strategy_id, version)]

    def reset(self) -> None:
        for strategy_id, version in self._strategy_keys:
            strategy = self._registry.get(strategy_id, version)
            strategy.reset()
        self._initialized.clear()

    def run(
        self,
        contexts: Mapping[str, StrategyContext],
        selected: Iterable[StrategyKey] | None = None,
    ) -> StrategyRunResult:
        keys = tuple(selected) if selected is not None else self._strategy_keys
        signals: list[Signal] = []
        failures: list[StrategyRunFailure] = []

        for strategy_id, version in keys:
            key = (strategy_id, version)
            if key not in self._enabled:
                raise KeyError(f"strategy not managed: {key}")
            if not self._enabled[key]:
                continue

            context = contexts.get(strategy_id)
            if context is None:
                failures.append(
                    StrategyRunFailure(
                        strategy_id, version, "context",
                        "KeyError", "strategy context not supplied",
                    )
                )
                continue

            payload = getattr(getattr(context, "input", None), "payload", None)
            if isinstance(payload, UnavailableStrategyPayload):
                failures.append(
                    StrategyRunFailure(
                        strategy_id, version, "input", "UnavailableData",
                        payload.reason,
                    )
                )
                continue

            try:
                strategy = self._registry.prepare(strategy_id, version, context)
            except Exception as exc:
                failures.append(
                    StrategyRunFailure(
                        strategy_id, version, "prepare",
                        type(exc).__name__, str(exc),
                    )
                )
                continue

            if key not in self._initialized:
                try:
                    strategy.initialize(context)
                    self._initialized.add(key)
                except Exception as exc:
                    failures.append(
                        StrategyRunFailure(
                            strategy_id, version, "initialize",
                            type(exc).__name__, str(exc),
                        )
                    )
                    continue

            try:
                strategy.on_market_state(context)
            except Exception as exc:
                failures.append(
                    StrategyRunFailure(
                        strategy_id, version, "on_market_state",
                        type(exc).__name__, str(exc),
                    )
                )
                continue

            try:
                produced = strategy.evaluate(context)
                signals.extend(tuple(produced))
            except Exception as exc:
                failures.append(
                    StrategyRunFailure(
                        strategy_id, version, "evaluate",
                        type(exc).__name__, str(exc),
                    )
                )

        return StrategyRunResult(
            signals=tuple(signals),
            failures=tuple(failures),
        )


# --- Canonical Signal Adapter ---

from contracts.types import OptionInstrumentIdentity
from shared.contracts.canonical import (
    CanonicalAssetType,
    CanonicalOrderSide,
    CanonicalOptionType,
    CanonicalStrategySignal,
)


@dataclass(frozen=True)
class RuntimeSignalContext:
    """Authoritative values supplied by Runtime/Controller, not Strategy."""

    signal_id: str
    track_id: str
    price: float
    timestamp: str


def _require_non_empty(value: str, field_name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field_name}_REQUIRED")
    return value


def signal_to_canonical(
    signal: Signal,
    runtime: RuntimeSignalContext,
    instrument_identity: Optional[OptionInstrumentIdentity] = None,
) -> CanonicalStrategySignal:
    """Convert Standard Signal only from authoritative supplied values."""
    signal_id = _require_non_empty(runtime.signal_id, "SIGNAL_ID")
    track_id = _require_non_empty(runtime.track_id, "TRACK_ID")
    proposal = signal.execution_proposal
    if proposal is None:
        raise ValueError("EXECUTION_PROPOSAL_REQUIRED")

    if proposal.proposed_quantity <= 0:
        raise ValueError("QTY_REQUIRED")
    if not proposal.asset_type:
        raise ValueError("ASSET_TYPE_REQUIRED")
    if not proposal.side:
        raise ValueError("SIDE_REQUIRED")

    asset_type = CanonicalAssetType(str(proposal.asset_type))
    side = CanonicalOrderSide(str(proposal.side))

    identity = instrument_identity if instrument_identity is not None else signal.instrument_identity
    option_type: Optional[CanonicalOptionType] = None
    strike = 0.0
    symbol = ""
    expiry = ""

    if asset_type == CanonicalAssetType.OPTION:
        if identity is None:
            raise ValueError("OPTION_IDENTITY_REQUIRED")
        if not identity.instrument_id or not identity.symbol or not identity.expiry:
            raise ValueError("OPTION_IDENTITY_INCOMPLETE")
        if identity.option_type is None or identity.strike is None:
            raise ValueError("OPTION_IDENTITY_INCOMPLETE")

        if proposal.option_type is not None and str(proposal.option_type) != str(identity.option_type):
            raise ValueError("OPTION_TYPE_IDENTITY_MISMATCH")
        if proposal.strike is not None and proposal.strike != identity.strike:
            raise ValueError("STRIKE_IDENTITY_MISMATCH")

        option_type = CanonicalOptionType(str(identity.option_type))
        strike = float(identity.strike)
        symbol = identity.symbol
        expiry = identity.expiry

    return CanonicalStrategySignal(
        signal_id=signal_id,
        track_id=track_id,
        asset_type=asset_type,
        side=side,
        qty=proposal.proposed_quantity,
        price=float(runtime.price),
        option_type=option_type,
        strike=strike,
        tag_id=str(proposal.tag_id) if proposal.tag_id is not None else "",
        reason=signal.reason,
        timestamp=runtime.timestamp,
        symbol=symbol,
        expiry=expiry,
    )


# --- Runtime Strategy to Decision Adapter ---

from application.composition.runtime_strategy_result_collection_adapter import (
    RuntimeStrategyEvaluation,
)
from core.decision.decision_arbiter import ArbitrationResult, DecisionArbiter

InstrumentIdentityProvider = Callable[[RuntimeStrategyEvaluation], OptionInstrumentIdentity | None]


@dataclass(frozen=True)
class RuntimeDecisionResult:
    canonical_signals: tuple[CanonicalStrategySignal, ...]
    arbitration: ArbitrationResult


class RuntimeStrategyToDecisionAdapter:
    """Connect Runtime-owned Strategy evaluations to existing Canonical/Decision seam."""

    def __init__(self, arbiter: DecisionArbiter) -> None:
        self._arbiter = arbiter

    def arbitrate(
        self,
        evaluations: Iterable[RuntimeStrategyEvaluation],
        *,
        price: float,
        timestamp: str,
        account: Any,
        instrument_identity_provider: InstrumentIdentityProvider | None = None,
    ) -> RuntimeDecisionResult:
        canonical_signals: list[CanonicalStrategySignal] = []
        seen_signal_ids: set[str] = set()

        for evaluation in evaluations:
            signal = evaluation.result
            track_id = str(getattr(evaluation.context, "strategy_id", "") or "").strip()
            if not track_id:
                raise ValueError("RUNTIME_TRACK_ID_REQUIRED")

            signal_id = evaluation.runtime_context.signal_id(track_id)
            if signal_id in seen_signal_ids:
                raise ValueError("RUNTIME_DUPLICATE_SIGNAL_ID")
            seen_signal_ids.add(signal_id)

            identity = (
                instrument_identity_provider(evaluation)
                if instrument_identity_provider is not None
                else None
            )
            canonical_signals.append(
                signal_to_canonical(
                    signal,
                    RuntimeSignalContext(
                        signal_id=signal_id,
                        track_id=track_id,
                        price=price,
                        timestamp=timestamp,
                    ),
                    instrument_identity=identity,
                )
            )

        arbitration = self._arbiter.arbitrate(canonical_signals, account)
        return RuntimeDecisionResult(
            canonical_signals=tuple(canonical_signals),
            arbitration=arbitration,
        )


# --- Runtime Decision Command Adapter ---

from core.runtime.reference_execution_pipeline import (
    DecisionCommandContext,
    approved_signal_to_command,
)
from shared.contracts.canonical import CanonicalOrderCommand


class RuntimeDecisionCommandAdapter:
    """Transport approved signals to CanonicalOrderCommand using Runtime-owned IDs."""

    def build_commands(
        self,
        evaluations: Iterable[RuntimeStrategyEvaluation],
        approved_signals: Iterable[CanonicalStrategySignal],
    ) -> tuple[CanonicalOrderCommand, ...]:
        contexts: dict[str, RuntimeStrategyEvaluation] = {}
        for evaluation in evaluations:
            track_id = str(getattr(evaluation.context, "strategy_id", "") or "").strip()
            if not track_id:
                raise ValueError("RUNTIME_TRACK_ID_REQUIRED")
            signal_id = evaluation.runtime_context.signal_id(track_id)
            if signal_id in contexts:
                raise ValueError("RUNTIME_DUPLICATE_SIGNAL_ID")
            contexts[signal_id] = evaluation

        commands: list[CanonicalOrderCommand] = []
        for signal in approved_signals:
            evaluation = contexts.get(signal.signal_id)
            if evaluation is None:
                raise ValueError("RUNTIME_APPROVED_SIGNAL_CONTEXT_REQUIRED")
            track_id = str(getattr(evaluation.context, "strategy_id", "") or "").strip()
            if track_id != signal.track_id:
                raise ValueError("RUNTIME_TRACK_ID_CONTEXT_MISMATCH")

            commands.append(
                approved_signal_to_command(
                    signal,
                    context=DecisionCommandContext(
                        client_order_id=evaluation.runtime_context.client_order_id(track_id),
                    ),
                )
            )

        return tuple(commands)


