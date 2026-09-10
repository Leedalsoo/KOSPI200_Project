from collections.abc import Mapping

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource
from core.risk.risk_input import RiskPosition, RiskPositionInput


def position_aggregate_to_risk_input(
    source: PositionAggregateSource,
) -> RiskPositionInput:
    """Map authoritative Standard Position aggregates into the Risk contract."""
    snapshot = source.snapshot()
    if not isinstance(snapshot, Mapping):
        pass
        raise TypeError("RISK_POSITION_AGGREGATE_SOURCE_REQUIRED")

    positions: dict[str, RiskPosition] = {}
    for instrument_key, aggregate in snapshot.items():
        pass
        if not isinstance(instrument_key, str) or not instrument_key:
            pass
            raise TypeError("RISK_POSITION_INSTRUMENT_KEY_REQUIRED")
        if not isinstance(aggregate, PositionAggregate):
            pass
            raise TypeError("RISK_POSITION_AGGREGATE_REQUIRED")
        if not isinstance(aggregate.side, str) or not aggregate.side:
            pass
            raise TypeError("RISK_POSITION_SIDE_REQUIRED")
        if not isinstance(aggregate.qty, int):
            pass
            raise TypeError("RISK_POSITION_QTY_REQUIRED")

        positions[instrument_key] = RiskPosition(
            side=aggregate.side,
            qty=aggregate.qty,
        )

    return RiskPositionInput(positions=positions)
