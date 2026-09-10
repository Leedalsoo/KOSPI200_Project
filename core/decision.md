폴더 페이지

[Child Page] pipeline.py
```python
from dataclasses import dataclass
from typing import Sequence
from contracts.types import OrderIntent
from core.strategy.contracts import Signal

@dataclass(frozen=True)
class Decision:
    action: str
    signals: Sequence[Signal]

@dataclass(frozen=True)
class RiskResult:
    allowed: bool
    quantity: int
    reason: str

@dataclass(frozen=True)
class CorePipeline:
    def evaluate(self, strategy, context, risk_engine, position_logic):
        signals = strategy.evaluate(context)
        decision = self._decide(signals)
        risk = risk_engine.validate(decision, context)
        if not risk.allowed:
            return None
        return position_logic.to_order_intent(decision, risk, context)

    def _decide(self, signals):
        return Decision(action="NO_ACTION" if not signals else "EVALUATE", signals=signals)
```
Actual decision/risk rules are migrated from baseline evidence, not fabricated.

[Child Page] decision_arbiter.py
```python
"""Standard Decision Arbiter migrated from Reference Exp_Detail_1.

The arbiter resolves deterministic cross-strategy signal conflicts while
preserving each canonical signal object unchanged.
"""
from dataclasses import dataclass
from typing import Any, List, Tuple


# Reference values: lower number means higher priority.
STRATEGY_PRIORITY_MAP = {
    "HEDGE_DELTA": 1,
    "HEDGE_TAIL": 1,
    "Track1": 2,
    "Track6": 3,
    "Track9": 3,
    "Track3": 4,
    "Track4": 4,
    "Track7": 5,
    "Track8": 5,
    "Track2": 6,
    "Track5": 6,
}


@dataclass(frozen=True)
class ArbitrationResult:
    """Reference-compatible arbitration result DTO."""

    approved_signals: List[Any]
    rejected_signals: List[Tuple[Any, str]]
    netted_clashes: List[str]


class DecisionArbiter:
    """Deterministic priority and same-instrument side conflict resolver."""

    def __init__(self) -> None:
        pass

    def _get_priority(self, track_id: str) -> int:
        return STRATEGY_PRIORITY_MAP.get(track_id, 99)

    @staticmethod
    def _enum_value(value: Any) -> Any:
        return getattr(value, "value", value)

    @classmethod
    def _instrument_key(cls, signal: Any) -> str:
        asset_type = cls._enum_value(signal.asset_type)
        option_type = cls._enum_value(signal.option_type) if signal.option_type is not None else "NONE"
        return f"{asset_type}_{signal.strike}_{option_type}"

    def arbitrate(self, signals: List[Any], account: Any) -> ArbitrationResult:
        """Apply the Reference Exp_Detail_1 arbitration rules exactly.

        `account` is retained in the API for compatibility. The Reference
        implementation accepts it but does not directly use it in arbitration.
        """
        if not signals:
            return ArbitrationResult([], [], [])

        approved: List[Any] = []
        rejected: List[Tuple[Any, str]] = []
        netted_clashes: List[str] = []

        sorted_signals = sorted(
            signals,
            key=lambda signal: (
                self._get_priority(signal.track_id),
                -signal.qty,
                signal.signal_id,
            ),
        )

        instrument_claims: dict[str, Any] = {}

        for signal in sorted_signals:
            instrument_key = self._instrument_key(signal)
            existing = instrument_claims.get(instrument_key)

            if existing is None:
                instrument_claims[instrument_key] = signal
                approved.append(signal)
                continue

            if existing.side != signal.side:
                existing_side = self._enum_value(existing.side)
                signal_side = self._enum_value(signal.side)
                reason = (
                    f"CLASH_NETTING_REJECTED: Subordinate to "
                    f"{existing.track_id} ({existing_side})"
                )
                rejected.append((signal, reason))
                netted_clashes.append(
                    f"Clash on {instrument_key}: Kept "
                    f"{existing.track_id}({existing_side}), Rejected "
                    f"{signal.track_id}({signal_side})"
                )
            else:
                # Reference behavior: preserve the signal; do not aggregate qty.
                approved.append(signal)

        return ArbitrationResult(
            approved_signals=approved,
            rejected_signals=rejected,
            netted_clashes=netted_clashes,
        )
```
### Migration boundary
    - This module contains only Standard Decision arbitration logic; it does not import Legacy Runtime, KIS, VMS, VSSF, Broker, Risk, or OMS.
    - Canonical signal objects are passed through unchanged.
    - account remains an API-compatible argument but is not used to invent additional rules.
    - Provenance/Envelope remains a transport concern and is not used to recalculate priority or conflict decisions.
    - Quantity is never aggregated or rewritten by the arbiter.

[Child Page] decision_arbiter_envelope_adapter.py
```python
"""Parallel transport adapter between StrategySignalEnvelope and DecisionArbiter.

The adapter preserves the existing List[CanonicalStrategySignal] Decision API.
It does not perform arbitration, priority calculation, conflict detection, or
execution-intent inference.
"""
from typing import Iterable, Any

from core.oms.strategy_signal_envelope import StrategySignalEnvelope


def unwrap_strategy_signal_envelopes(
    envelopes: Iterable[StrategySignalEnvelope],
) -> list[Any]:
    """Return the unchanged canonical signals expected by DecisionArbiter."""
    return [envelope.signal for envelope in envelopes]


def index_strategy_signal_envelopes(
    envelopes: Iterable[StrategySignalEnvelope],
) -> dict[str, StrategySignalEnvelope]:
    """Index envelopes by the existing signal_id; fail closed on duplicates."""
    indexed: dict[str, StrategySignalEnvelope] = {}
    for envelope in envelopes:
        signal_id = envelope.signal_id
        if signal_id in indexed:
            raise ValueError(f"DUPLICATE_SIGNAL_ID: {signal_id}")
        indexed[signal_id] = envelope
    return indexed


def reconnect_approved_signal_envelopes(
    approved_signals: Iterable[Any],
    envelope_index: dict[str, StrategySignalEnvelope],
) -> list[StrategySignalEnvelope]:
    """Reconnect Arbiter output to the original envelopes by signal_id.

    The approved signal objects remain authoritative for Decision output; this
    function only restores the parallel provenance wrapper. Missing IDs fail
    closed rather than inventing or matching by list position.
    """
    result: list[StrategySignalEnvelope] = []
    for signal in approved_signals:
        signal_id = str(signal.signal_id)
        envelope = envelope_index.get(signal_id)
        if envelope is None:
            raise ValueError(f"SIGNAL_ID_NOT_FOUND: {signal_id}")
        if envelope.signal is not signal:
            # A matching ID is necessary but identity preservation is also
            # required: do not silently reconnect a different signal object.
            raise ValueError(f"SIGNAL_OBJECT_MISMATCH: {signal_id}")
        result.append(envelope)
    return result
```
### Boundary rules
    - unwrap_strategy_signal_envelopes() supplies exactly the canonical signal list required by the Reference-compatible DecisionArbiter.
    - index_strategy_signal_envelopes() is only an identity/provenance index and rejects duplicate signal_id.
    - reconnect_approved_signal_envelopes() uses signal_id and object identity; it never matches by list position or recalculates semantics.
    - No priority, sorting, clash, quantity, price, side, asset, strike, option type, order purpose, or order type is changed or inferred.
    - Risk/OMS are not imported and are intentionally outside this boundary.

[Child Page] test_decision_arbiter_envelope_adapter.py
```python
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal

import pytest

from core.decision.decision_arbiter import DecisionArbiter
from core.decision.decision_arbiter_envelope_adapter import (
    index_strategy_signal_envelopes,
    reconnect_approved_signal_envelopes,
    unwrap_strategy_signal_envelopes,
)
from core.oms.execution_provenance import ExecutionProvenance
from core.oms.strategy_signal_envelope import StrategySignalEnvelope


class AssetType(str, Enum):
    OPTION = "OPTION"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptionType(str, Enum):
    CALL = "CALL"


@dataclass(frozen=True)
class Signal:
    signal_id: str
    track_id: str
    qty: int
    asset_type: AssetType
    strike: Decimal
    option_type: OptionType | None
    side: Side


def make_signal(signal_id: str, track_id: str = "Track1", side: Side = Side.BUY, qty: int = 1):
    return Signal(signal_id, track_id, qty, AssetType.OPTION, Decimal("350"), OptionType.CALL, side)


def make_envelope(signal: Signal, **raw):
    provenance = ExecutionProvenance(
        strategy_id=raw.get("strategy_id"),
        track_id=raw.get("track_id", signal.track_id),
        tag_id=raw.get("tag_id"),
        action=raw.get("action"),
        reason=raw.get("reason"),
        declared_order_purpose=raw.get("order_purpose"),
        declared_order_type=raw.get("order_type"),
        metadata=raw.get("metadata"),
    )
    return StrategySignalEnvelope(signal=signal, provenance=provenance)


def test_unwrap_preserves_same_signal_objects():
    first = make_signal("s1")
    second = make_signal("s2", track_id="Track2")
    envelopes = [make_envelope(first), make_envelope(second)]
    unwrapped = unwrap_strategy_signal_envelopes(envelopes)
    assert unwrapped == [first, second]
    assert unwrapped[0] is first
    assert unwrapped[1] is second


def test_index_rejects_duplicate_signal_id_fail_closed():
    first = make_signal("same")
    second = make_signal("same", track_id="Track2")
    with pytest.raises(ValueError, match=r"DUPLICATE_SIGNAL_ID: same"):
        index_strategy_signal_envelopes([make_envelope(first), make_envelope(second)])


def test_arbiter_output_reconnects_to_original_envelopes_by_signal_id():
    winner = make_signal("winner", track_id="Track1", side=Side.BUY, qty=5)
    loser = make_signal("loser", track_id="Track2", side=Side.SELL, qty=1)
    winner_env = make_envelope(winner, action="OPEN", order_purpose="ENTRY")
    loser_env = make_envelope(loser, action="CLOSE", order_purpose="EXIT")
    envelopes = [winner_env, loser_env]
    index = index_strategy_signal_envelopes(envelopes)

    result = DecisionArbiter().arbitrate(unwrap_strategy_signal_envelopes(envelopes), account=None)
    approved = reconnect_approved_signal_envelopes(result.approved_signals, index)

    assert approved == [winner_env]
    assert approved[0] is winner_env
    assert approved[0].provenance.action == "OPEN"
    assert approved[0].provenance.declared_order_purpose == "ENTRY"


def test_reconnect_fails_closed_for_unknown_signal_id():
    known = make_signal("known")
    unknown = make_signal("unknown")
    index = index_strategy_signal_envelopes([make_envelope(known)])
    with pytest.raises(ValueError, match=r"SIGNAL_ID_NOT_FOUND: unknown"):
        reconnect_approved_signal_envelopes([unknown], index)


def test_reconnect_fails_closed_for_different_object_with_same_signal_id():
    original = make_signal("same")
    replacement = make_signal("same", track_id="Track2")
    index = index_strategy_signal_envelopes([make_envelope(original)])
    with pytest.raises(ValueError, match=r"SIGNAL_OBJECT_MISMATCH: same"):
        reconnect_approved_signal_envelopes([replacement], index)
```
### Verification target
pytest -q core/decision/test_decision_arbiter_envelope_adapter.py
The test intentionally verifies only parallel transport and provenance reconnection. It does not change the Reference branch and does not connect Risk/OMS.