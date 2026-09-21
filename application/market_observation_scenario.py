from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Callable, Mapping

from contracts.types import MarketObservation


@dataclass(frozen=True)
class ScenarioMarketObservation:
    source_observation_id: str
    scenario_id: str
    run_id: str
    transformation_metadata: tuple[tuple[str, str], ...]
    observation: MarketObservation


class ScenarioObservationTransformer:
    """Create separately identified scenario observations from canonical data."""

    def transform(
        self,
        observation: MarketObservation,
        *,
        scenario_id: str,
        run_id: str,
        transform: Callable[[MarketObservation], MarketObservation],
        metadata: Mapping[str, str] | None = None,
    ) -> ScenarioMarketObservation:
        if not scenario_id or not run_id:
            raise ValueError("SCENARIO_PROVENANCE_REQUIRED")
        transformed = transform(observation)
        observation_id = sha256(
            f"{observation.observation_id}|{scenario_id}|{run_id}".encode("utf-8")
        ).hexdigest()[:24]
        transformed = replace(
            transformed,
            observation_id=observation_id,
            source=f"scenario:{scenario_id}",
            run_id=run_id,
        )
        return ScenarioMarketObservation(
            source_observation_id=observation.observation_id,
            scenario_id=scenario_id,
            run_id=run_id,
            transformation_metadata=tuple(sorted((metadata or {}).items())),
            observation=transformed,
        )
