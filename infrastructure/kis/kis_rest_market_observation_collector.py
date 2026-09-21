from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping, Protocol

from contracts.types import MarketObservation, OptionInstrumentIdentity, RawMarketDataReference
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.kis_rest_market_observation_normalizer import (
    KISRestMarketObservationNormalizer,
)


@dataclass(frozen=True)
class CollectionTarget:
    identity: OptionInstrumentIdentity


@dataclass(frozen=True)
class CollectionResult:
    status: str
    reason: str | None = None
    observation_id: str | None = None
    symbol: str | None = None
    run_id: str | None = None
    cycle_id: str | None = None


class ManualClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class RateLimiter:
    def __init__(self, interval_seconds: float, clock: Any) -> None:
        if interval_seconds <= 0:
            raise ValueError("RATE_LIMIT_INTERVAL_REQUIRED")
        self.interval_seconds = interval_seconds
        self.clock = clock
        self._last: float | None = None

    def wait(self) -> None:
        now = self.clock.monotonic()
        if self._last is not None:
            remaining = self.interval_seconds - (now - self._last)
            if remaining > 0:
                self.clock.sleep(remaining)
        self._last = self.clock.monotonic()


class RestTransport(Protocol):
    def request_price(self, symbol: str) -> tuple[int, dict[str, Any]]: ...
    def request_order_book(self, symbol: str) -> tuple[int, dict[str, Any]]: ...


class KISRestMarketObservationTransport:
    PRICE_PATH = "/uapi/domestic-futureoption/v1/quotations/inquire-price"
    ORDER_BOOK_PATH = "/uapi/domestic-futureoption/v1/quotations/inquire-asking-price"
    PRICE_TR_ID = "FHMIF10000000"
    ORDER_BOOK_TR_ID = "FHMIF10010000"

    def __init__(
        self,
        auth: KISAuthManager,
        *,
        timeout: float = 10.0,
        urlopen: Any = urllib.request.urlopen,
    ) -> None:
        self.auth = auth
        self.timeout = timeout
        self._urlopen = urlopen

    def _get(self, path: str, tr_id: str, symbol: str) -> tuple[int, dict[str, Any]]:
        query = urllib.parse.urlencode(
            {"FID_COND_MRKT_DIV_CODE": "O", "FID_INPUT_ISCD": symbol}
        )
        request = urllib.request.Request(
            f"{self.auth.base_url}{path}?{query}",
            headers=self.auth.get_auth_headers(tr_id=tr_id),
            method="GET",
        )
        with self._urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return int(response.status), payload

    def request_price(self, symbol: str) -> tuple[int, dict[str, Any]]:
        return self._get(self.PRICE_PATH, self.PRICE_TR_ID, symbol)

    def request_order_book(self, symbol: str) -> tuple[int, dict[str, Any]]:
        return self._get(self.ORDER_BOOK_PATH, self.ORDER_BOOK_TR_ID, symbol)


class KISRestMarketObservationCollector:
    def __init__(
        self,
        *,
        identity_source: Mapping[str, OptionInstrumentIdentity] | Any,
        transport: RestTransport,
        store: HistoricalMarketStore,
        clock: Any | None = None,
        limiter: RateLimiter | None = None,
        normalizer: KISRestMarketObservationNormalizer | None = None,
    ) -> None:
        self.identity_source = identity_source
        self.transport = transport
        self.store = store
        self.clock = clock or ManualClock()
        self.limiter = limiter or RateLimiter(1.0, self.clock)
        self.normalizer = normalizer or KISRestMarketObservationNormalizer(self)
    
    def get_contract_identity(self, symbol: str) -> OptionInstrumentIdentity | None:
        if isinstance(self.identity_source, Mapping):
            return self.identity_source.get(symbol)
        getter = getattr(self.identity_source, "get_contract_identity", None)
        if getter is None:
            return None
        return getter(symbol)

    def _resolve_target(self, target: CollectionTarget) -> OptionInstrumentIdentity | None:
        identity = self.get_contract_identity(target.identity.symbol)
        if identity is None:
            return None
        if not identity.instrument_id or not identity.symbol:
            return None
        if identity.symbol != target.identity.symbol:
            return None
        return identity

    @staticmethod
    def _raw_hash(price: dict[str, Any], order_book: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"price": price, "order_book": order_book},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _required_market_values(observation: MarketObservation) -> bool:
        return all(
            value is not None
            for value in (
                observation.quote.last,
                observation.quote.bid,
                observation.quote.ask,
                observation.quote.volume,
            )
        )

    def collect_cycle(
        self,
        targets: list[CollectionTarget],
        *,
        run_id: str,
        cycle_id: str,
    ) -> tuple[CollectionResult, ...]:
        results: list[CollectionResult] = []
        for target in targets:
            identity = self._resolve_target(target)
            symbol = target.identity.symbol
            if identity is None:
                results.append(CollectionResult(
                    status="BLOCKED",
                    reason="AUTHORITATIVE_OPTION_IDENTITY_REQUIRED",
                    symbol=symbol,
                    run_id=run_id,
                    cycle_id=cycle_id,
                ))
                continue

            try:
                self.limiter.wait()
                price_status, price = self.transport.request_price(symbol)
                if price_status < 200 or price_status >= 300:
                    raise ValueError("KIS_REST_HTTP_ERROR")
                self.limiter.wait()
                order_book_status, order_book = self.transport.request_order_book(symbol)
                if order_book_status < 200 or order_book_status >= 300:
                    raise ValueError("KIS_REST_HTTP_ERROR")
                collected_at = self.clock.now()
                raw_hash = self._raw_hash(price, order_book)
                raw_id = f"{run_id}:{cycle_id}:{symbol}:{raw_hash[:16]}"

                if any(record.get("content_hash") == raw_hash for record in self.store.raw_records()):
                    results.append(CollectionResult(
                        status="DUPLICATE", symbol=symbol, run_id=run_id, cycle_id=cycle_id
                    ))
                    continue

                self.store.append_raw_record(
                    raw_id=raw_id,
                    source="kis_vts_rest",
                    provider="KISOptionRestAdapter",
                    endpoint="price+orderbook",
                    tr_id="FHMIF10000000+FHMIF10010000",
                    collected_at=collected_at,
                    run_id=run_id,
                    request_metadata={"symbol": symbol, "cycle_id": cycle_id},
                    response_metadata={
                        "price_rt_cd": price.get("rt_cd"),
                        "order_book_rt_cd": order_book.get("rt_cd"),
                    },
                    payload={"price": price, "order_book": order_book},
                    http_status=200,
                    content_hash=raw_hash,
                )
                observation = self.normalizer.normalize(
                    price_response=price,
                    asking_price_response=order_book,
                    collected_at=collected_at,
                    run_id=run_id,
                )
                if observation.contract != identity:
                    raise ValueError("AUTHORITATIVE_OPTION_IDENTITY_MISMATCH")
                if not self._required_market_values(observation):
                    raise ValueError("REQUIRED_MARKET_VALUE_MISSING")
                observation = MarketObservation(
                    **{**observation.__dict__,
                       "raw_reference": RawMarketDataReference(raw_id=raw_id, content_hash=raw_hash)}
                )
                self.store.append_observation(observation)
                results.append(CollectionResult(
                    status="SUCCESS",
                    observation_id=observation.observation_id,
                    symbol=symbol,
                    run_id=run_id,
                    cycle_id=cycle_id,
                ))
            except (ValueError, urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                results.append(CollectionResult(
                    status="BLOCKED",
                    reason=str(exc) or "KIS_REST_COLLECTION_FAILED",
                    symbol=symbol,
                    run_id=run_id,
                    cycle_id=cycle_id,
                ))
        return tuple(results)
