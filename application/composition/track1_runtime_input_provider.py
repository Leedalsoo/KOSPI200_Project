from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Iterable

from contracts.position_provenance import PositionRole, PositionLotProvenance
from core.strategy.track1_tail_defense import Track1Input


@dataclass(frozen=True)
class Track1RuntimeInputResult:
    payload: Track1Input | None
    missing_sources: tuple[str, ...] = ()


class Track1RuntimeInputProvider:
    """Materialize Track1-only Runtime Input from authoritative runtime sources."""

    ROC_LOOKBACK = 12
    STRATEGY_ID = "TRACK1_TAIL_DEFENSE"

    def __init__(
        self,
        *,
        fence_type_source: Callable[[], str | None] | None = None,
        position_lot_store: Any | None = None,
        option_delta_source: Any | None = None,
    ) -> None:
        self.fence_type_source = fence_type_source
        self.position_lot_store = position_lot_store
        self.option_delta_source = option_delta_source

    @staticmethod
    def _momentum_confirmed(
        underlying_history: Iterable[tuple[datetime, Decimal]],
        as_of: datetime,
        fence_type: str,
    ) -> bool | None:
        points = [
            (timestamp, Decimal(str(price)))
            for timestamp, price in underlying_history
            if timestamp <= as_of
        ]
        if len(points) < Track1RuntimeInputProvider.ROC_LOOKBACK + 1:
            return None
        points.sort(key=lambda item: item[0])
        current = points[-1][1]
        previous = points[-(Track1RuntimeInputProvider.ROC_LOOKBACK + 1)][1]
        if previous == 0:
            return None
        roc = (current - previous) / previous
        if fence_type == "CALL":
            return roc > 0
        if fence_type == "PUT":
            return roc < 0
        return None

    def _track1_lots(self) -> tuple[PositionLotProvenance, ...] | None:
        if self.position_lot_store is None:
            return None
        lots = self.position_lot_store.open_lots()
        return tuple(
            lot for lot in lots
            if lot.strategy_id == self.STRATEGY_ID
            and lot.instrument_identity is not None
        )

    def _position_metrics(
        self,
        lots: tuple[PositionLotProvenance, ...],
        as_of: datetime,
    ) -> tuple[Decimal | None, Decimal | None]:
        short_target = sum(
            (Decimal(lot.remaining_quantity) for lot in lots if lot.side == "SELL"),
            Decimal("0"),
        )
        if short_target <= 0:
            return None, None

        covered = sum(
            (
                Decimal(lot.remaining_quantity)
                for lot in lots
                if lot.position_role != PositionRole.NONE
            ),
            Decimal("0"),
        )
        coverage_ratio = covered / short_target

        if self.option_delta_source is None:
            return coverage_ratio, None

        net_delta = Decimal("0")
        for lot in lots:
            if lot.side != "SELL":
                continue
            identity = lot.instrument_identity
            delta = self.option_delta_source.get_delta(
                expiry=identity.expiry,
                option_type=str(identity.option_type),
                strike=Decimal(str(identity.strike)),
                as_of=as_of,
                instrument_id=identity.instrument_id,
            )
            if delta is None:
                return coverage_ratio, None
            net_delta += (
                -Decimal(lot.remaining_quantity)
                * Decimal(str(delta))
                * Decimal(str(lot.contract_multiplier))
            )
        return coverage_ratio, net_delta

    def build(
        self,
        *,
        as_of: datetime,
        active_vol: Decimal | None,
        base_vol: Decimal | None,
        days_to_expiry: float | None,
        underlying_history: Iterable[tuple[datetime, Decimal]],
    ) -> Track1RuntimeInputResult:
        missing: list[str] = []

        fence_type = self.fence_type_source() if self.fence_type_source is not None else None

        lots = self._track1_lots()
        if lots is None:
            missing.extend(("position_coverage", "option_position_greeks"))
            return Track1RuntimeInputResult(None, tuple(dict.fromkeys(missing)))

        initial_unfenced_state = fence_type not in {"PUT", "CALL"} and not lots
        if initial_unfenced_state:
            momentum = False
        else:
            if fence_type not in {"PUT", "CALL"}:
                missing.append("track1_fence_direction")
                momentum = None
            else:
                momentum = self._momentum_confirmed(underlying_history, as_of, fence_type)
            # Insufficient ROC lookback is normal warm-up, not missing authoritative data.
            # Track1 safely evaluates this state as momentum_confirmed=False.

        coverage_ratio, short_option_net_delta = self._position_metrics(lots, as_of)
        if active_vol is None:
            missing.append("active_vol")
        if base_vol is None:
            missing.append("base_vol")
        if days_to_expiry is None:
            missing.append("option_expiry")

        if missing:
            return Track1RuntimeInputResult(None, tuple(dict.fromkeys(missing)))

        return Track1RuntimeInputResult(
            Track1Input(
                momentum_confirmed=bool(momentum),
                days_to_expiry=days_to_expiry,
                current_time=as_of,
                active_vol=float(active_vol),
                base_vol=float(base_vol),
                coverage_ratio=(float(coverage_ratio) if coverage_ratio is not None else None),
                short_option_net_delta=short_option_net_delta,
            ),
            (),
        )