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
