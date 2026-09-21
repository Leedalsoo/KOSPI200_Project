from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Iterator

from contracts.types import (
    MarketAnalytics,
    MarketDataProvenance,
    MarketObservation,
    MarketOrderBook,
    MarketQuote,
    OptionInstrumentIdentity,
    OrderBookLevel,
    RawMarketDataReference,
)
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick


class HistoricalMarketStore:
    """Append-only JSONL store for canonical market events.

    The store is source-neutral: real KRX-derived events, replay data, and
    synthetic events must be explicitly identified by the caller and must not
    be silently mixed.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, tick: ReferenceCanonicalMarketTick, *, source: str) -> None:
        source = str(source).strip()
        if not source:
            raise ValueError("MARKET_DATA_SOURCE_REQUIRED")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": "reference-canonical-market-tick-v1",
            "source": source,
            "tick": tick.__dict__,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def append_many(self, ticks: Iterable[ReferenceCanonicalMarketTick], *, source: str) -> int:
        count = 0
        for tick in ticks:
            self.append(tick, source=source)
            count += 1
        return count

    @property
    def observation_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".observations.jsonl")

    @property
    def raw_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".raw.jsonl")

    @staticmethod
    def _json_default(value: Any) -> str:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"UNSUPPORTED_MARKET_DATA_VALUE:{type(value).__name__}")

    @staticmethod
    def _read_jsonl(path: Path) -> Iterator[dict]:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"INVALID_MARKET_DATA_RECORD_LINE:{line_number}") from exc

    def append_observation(self, observation: MarketObservation) -> None:
        record = {
            "schema": "canonical-market-observation-v1",
            "observation": asdict(observation),
        }
        self.observation_path.parent.mkdir(parents=True, exist_ok=True)
        with self.observation_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=self._json_default) + "\n")

    def load_observations(self) -> list[MarketObservation]:
        observations: list[MarketObservation] = []
        for record in self._read_jsonl(self.observation_path):
            if record.get("schema") != "canonical-market-observation-v1":
                raise ValueError("UNSUPPORTED_MARKET_OBSERVATION_SCHEMA")
            value = record["observation"]
            contract = OptionInstrumentIdentity(**value["contract"])
            quote = MarketQuote(**{k: self._decimal(v) for k, v in value["quote"].items()})
            order_book = MarketOrderBook(
                bids=tuple(OrderBookLevel(**{k: self._decimal(v) if k != "level" else v for k, v in level.items()}) for level in value["order_book"]["bids"]),
                asks=tuple(OrderBookLevel(**{k: self._decimal(v) if k != "level" else v for k, v in level.items()}) for level in value["order_book"]["asks"]),
                total_bid_quantity=self._decimal(value["order_book"]["total_bid_quantity"]),
                total_ask_quantity=self._decimal(value["order_book"]["total_ask_quantity"]),
            )
            analytics = MarketAnalytics(**{k: self._decimal(v) for k, v in value["analytics"].items()})
            provenance = MarketDataProvenance(**value["provenance"])
            raw_reference = value.get("raw_reference")
            raw_ref = RawMarketDataReference(**raw_reference) if raw_reference else None
            observed_at = datetime.fromisoformat(value["observed_at"]) if value.get("observed_at") else None
            collected_at = datetime.fromisoformat(value["collected_at"])
            observations.append(MarketObservation(
                observation_id=value["observation_id"], observed_at=observed_at, collected_at=collected_at,
                source=value["source"], provider=value["provider"], schema_version=value["schema_version"],
                run_id=value["run_id"], contract=contract, quote=quote, order_book=order_book,
                analytics=analytics, provenance=provenance, raw_reference=raw_ref,
            ))
        return observations

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None

    @staticmethod
    def _contains_credential_key(value: Any) -> bool:
        forbidden = ("appkey", "appsecret", "secretkey", "access_token", "authorization", "approval_key", "token")
        if isinstance(value, dict):
            for key, child in value.items():
                if any(item in str(key).lower() for item in forbidden):
                    return True
                if HistoricalMarketStore._contains_credential_key(child):
                    return True
        elif isinstance(value, (list, tuple)):
            return any(HistoricalMarketStore._contains_credential_key(child) for child in value)
        return False

    def append_raw_record(self, *, raw_id: str, source: str, provider: str, endpoint: str, tr_id: str,
                          collected_at: datetime, run_id: str, request_metadata: dict[str, Any],
                          response_metadata: dict[str, Any], payload: dict[str, Any], http_status: int) -> None:
        record = {
            "schema": "kis-rest-raw-market-response-v1", "raw_id": raw_id, "source": source,
            "provider": provider, "endpoint": endpoint, "tr_id": tr_id, "collected_at": collected_at,
            "run_id": run_id, "request_metadata": request_metadata, "response_metadata": response_metadata,
            "payload": payload, "http_status": http_status,
        }
        if self._contains_credential_key(record):
            raise ValueError("RAW_MARKET_DATA_CREDENTIAL_FORBIDDEN")
        self.raw_path.parent.mkdir(parents=True, exist_ok=True)
        with self.raw_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=self._json_default) + "\n")

    def raw_records(self) -> list[dict]:
        return list(self._read_jsonl(self.raw_path))

    def records(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"INVALID_MARKET_DATA_RECORD_LINE:{line_number}") from exc
                if record.get("schema") != "reference-canonical-market-tick-v1":
                    raise ValueError(f"UNSUPPORTED_MARKET_DATA_SCHEMA_LINE:{line_number}")
                if not record.get("source"):
                    raise ValueError(f"MARKET_DATA_SOURCE_REQUIRED_LINE:{line_number}")
                yield record

    def load_ticks(self, *, source: str | None = None) -> list[ReferenceCanonicalMarketTick]:
        ticks: list[ReferenceCanonicalMarketTick] = []
        for record in self.records():
            if source is not None and record["source"] != source:
                continue
            ticks.append(ReferenceCanonicalMarketTick(**record["tick"]))
        return ticks
