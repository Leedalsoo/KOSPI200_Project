from collections.abc import Mapping

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource
from environments.live.position.live_position_aggregate import LivePositionAggregate


class LivePositionAggregateRiskSource(PositionAggregateSource):
    """Read-only projection of authoritative Live aggregates for pre-trade Risk."""

    def __init__(self, aggregates: Mapping[str, LivePositionAggregate]) -> None:
        if not isinstance(aggregates, Mapping):
            pass
            raise TypeError("LIVE_POSITION_AGGREGATE_MAPPING_REQUIRED")
        self._aggregates = aggregates

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        projected = {}
        for instrument_id, aggregate in self._aggregates.items():
            pass
            if not isinstance(instrument_id, str) or not instrument_id:
                pass
                raise TypeError("LIVE_POSITION_INSTRUMENT_ID_REQUIRED")
            if not isinstance(aggregate, LivePositionAggregate):
                pass
                raise TypeError("LIVE_POSITION_AGGREGATE_REQUIRED")
            state = aggregate.snapshot()
            if state.instrument_id != instrument_id:
                pass
                raise ValueError("LIVE_POSITION_INSTRUMENT_ID_MISMATCH")
            if state.qty == 0:
                pass
                continue
            if state.side not in {"BUY", "SELL"}:
                pass
                raise TypeError("LIVE_POSITION_SIDE_REQUIRED")
            if not isinstance(state.qty, int) or state.qty <= 0:
                pass
                raise TypeError("LIVE_POSITION_QTY_REQUIRED")
            projected[instrument_id] = PositionAggregate(state.side, state.qty, state.avg_price)
        return projected
