from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from contracts.track9_iv_timeseries import Track9IVObservation


class KISTrack9IVObservationHistoryStore:
    """Append-only JSONL history for source-owned KIS IV observations."""

    SCHEMA = "track9-iv-observation-v1"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _identity(observation: Track9IVObservation) -> tuple[str, str, str, str, str, str]:
        return (
            observation.symbol,
            observation.expiry,
            observation.option_type,
            str(observation.strike),
            observation.observed_at.isoformat(),
            observation.source,
        )

    @staticmethod
    def _payload(observation: Track9IVObservation) -> dict[str, str]:
        return {
            "symbol": observation.symbol,
            "expiry": observation.expiry,
            "option_type": observation.option_type,
            "strike": str(observation.strike),
            "implied_volatility": str(observation.implied_volatility),
            "observed_at": observation.observed_at.isoformat(),
            "source": observation.source,
        }

    @staticmethod
    def _observation(payload: dict[str, str]) -> Track9IVObservation:
        return Track9IVObservation(
            symbol=payload["symbol"],
            expiry=payload["expiry"],
            option_type=payload["option_type"],
            strike=Decimal(payload["strike"]),
            implied_volatility=Decimal(payload["implied_volatility"]),
            observed_at=datetime.fromisoformat(payload["observed_at"]),
            source=payload["source"],
        )

    def _records(self) -> Iterable[Track9IVObservation]:
        if not self.path.exists():
            return ()
        return tuple(
            self._observation(json.loads(line)["observation"])
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    def append(self, observation: Track9IVObservation) -> None:
        if not observation.source:
            raise ValueError("TRACK9_IV_HISTORY_SOURCE_REQUIRED")
        if not observation.implied_volatility.is_finite() or observation.implied_volatility <= 0:
            raise ValueError("TRACK9_IV_HISTORY_IV_INVALID")
        identity = self._identity(observation)
        payload = self._payload(observation)
        for existing in self._records():
            if self._identity(existing) != identity:
                continue
            if self._payload(existing) != payload:
                raise ValueError("TRACK9_IV_HISTORY_DUPLICATE_CONFLICT")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"schema": self.SCHEMA, "observation": payload}
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def query(
        self,
        *,
        symbol: str,
        expiry: str,
        option_type: str,
        strike: Decimal,
        start: datetime,
        end: datetime,
    ) -> tuple[Track9IVObservation, ...]:
        if end <= start:
            raise ValueError("TRACK9_IV_HISTORY_INVALID_RANGE")
        matches = (
            item
            for item in self._records()
            if item.symbol == symbol
            and item.expiry == expiry
            and item.option_type == option_type
            and item.strike == strike
            and start <= item.observed_at < end
        )
        return tuple(sorted(matches, key=lambda item: item.observed_at))
