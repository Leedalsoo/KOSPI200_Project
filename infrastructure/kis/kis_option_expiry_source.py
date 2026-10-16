from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.kis_rest_market_observation_collector import KISRestMarketObservationTransport

DEFAULT_EXPIRY_CACHE_DIR = Path("data/reference/kis/option_expiry")
EXPIRY_CACHE_SCHEMA = "kis-option-expiry-record-v1"
EXPIRY_ENDPOINT = KISRestMarketObservationTransport.PRICE_PATH
EXPIRY_TR_ID = KISRestMarketObservationTransport.PRICE_TR_ID


class KISOptionExpiryResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class KISOptionExpiryRecord:
    symbol: str
    expiry_yyyymmdd: str
    environment: str
    source: str
    endpoint: str
    tr_id: str
    requested_at_utc: str
    received_at_utc: str
    http_status: int
    rt_cd: str
    msg_cd: str | None
    response_field: str
    raw_response_sha256: str
    master_sha256: str
    raw_response: Mapping[str, Any]
    schema_version: str = EXPIRY_CACHE_SCHEMA

    def __post_init__(self) -> None:
        try:
            exact = require_exact_option_expiry(self.expiry_yyyymmdd)
        except CanonicalOptionExpiryError as exc:
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_INVALID_DATE") from exc
        if exact != self.expiry_yyyymmdd:
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_NOT_CANONICAL")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", self.symbol):
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_SYMBOL_INVALID")
        if not re.fullmatch(r"[0-9a-f]{64}", self.raw_response_sha256):
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_RESPONSE_HASH_REQUIRED")
        if not re.fullmatch(r"[0-9a-f]{64}", self.master_sha256):
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_MASTER_HASH_REQUIRED")


class _RateLimiter:
    def __init__(self, interval_seconds: float, monotonic: Callable[[], float], sleep: Callable[[float], None]) -> None:
        self.interval_seconds = interval_seconds
        self._monotonic = monotonic
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._monotonic()
        if self._last is not None:
            delay = self.interval_seconds - (now - self._last)
            if delay > 0:
                self._sleep(delay)
        self._last = self._monotonic()


class KISOptionExpiryResolver:
    """Resolve KIS's exact futs_last_tr_date and preserve immutable provenance.

    A failed request is never retried automatically. Rate-limit failures are
    surfaced as BLOCKED; the caller must wait for the documented cooldown before
    an operator-triggered later attempt.
    """

    def __init__(
        self,
        *,
        master_sha256: str,
        auth_manager: KISAuthManager | None = None,
        transport: Any | None = None,
        cache_dir: Path | None = None,
        environment: str = "VTS",
        minimum_request_interval_seconds: float = 1.25,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", str(master_sha256)):
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_MASTER_HASH_REQUIRED")
        if environment not in {"VTS", "LIVE"}:
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_ENVIRONMENT_INVALID")
        self.master_sha256 = master_sha256
        self.environment = environment
        self.cache_dir = Path(cache_dir or DEFAULT_EXPIRY_CACHE_DIR)
        self.auth_manager = auth_manager or KISAuthManager.from_env(is_vts=environment == "VTS")
        self.transport = transport or KISRestMarketObservationTransport(self.auth_manager, timeout=12)
        self._limiter = _RateLimiter(minimum_request_interval_seconds, monotonic, sleep)
        self._now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _canonical_json(value: Mapping[str, Any]) -> bytes:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _cached_records(self, symbol: str) -> list[KISOptionExpiryRecord]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", symbol):
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_SYMBOL_INVALID")
        records: list[KISOptionExpiryRecord] = []
        if not self.cache_dir.is_dir():
            return records
        for path in self.cache_dir.glob(f"expiry_{symbol}_*.json"):
            try:
                raw_bytes = path.read_bytes()
                digest = hashlib.sha256(raw_bytes).hexdigest()
                suffix = path.stem.rsplit("_", 1)[-1]
                if not digest.startswith(suffix):
                    raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_CACHE_HASH_MISMATCH")
                payload = json.loads(raw_bytes.decode("utf-8"))
                if payload.get("schema_version") != EXPIRY_CACHE_SCHEMA or payload.get("symbol") != symbol:
                    raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_CACHE_SCHEMA_INVALID")
                response = payload.get("raw_response")
                if not isinstance(response, dict):
                    raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_CACHE_RAW_RESPONSE_REQUIRED")
                response_hash = hashlib.sha256(self._canonical_json(response)).hexdigest()
                if response_hash != payload.get("raw_response_sha256"):
                    raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_CACHE_RESPONSE_HASH_MISMATCH")
                records.append(KISOptionExpiryRecord(
                    symbol=payload["symbol"],
                    expiry_yyyymmdd=payload["expiry_yyyymmdd"],
                    environment=payload["environment"],
                    source=payload["source"],
                    endpoint=payload["endpoint"],
                    tr_id=payload["tr_id"],
                    requested_at_utc=payload["requested_at_utc"],
                    received_at_utc=payload["received_at_utc"],
                    http_status=int(payload["http_status"]),
                    rt_cd=str(payload["rt_cd"]),
                    msg_cd=payload.get("msg_cd"),
                    response_field=payload["response_field"],
                    raw_response_sha256=payload["raw_response_sha256"],
                    master_sha256=payload["master_sha256"],
                    raw_response=response,
                ))
            except KISOptionExpiryResolutionError:
                raise
            except Exception as exc:
                raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_CACHE_INVALID") from exc
        if len({record.expiry_yyyymmdd for record in records}) > 1:
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_IMMUTABILITY_CONFLICT")
        return records

    def _append_record(self, record: KISOptionExpiryRecord) -> KISOptionExpiryRecord:
        cached = self._cached_records(record.symbol)
        if cached:
            if any(item.expiry_yyyymmdd != record.expiry_yyyymmdd for item in cached):
                raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_IMMUTABILITY_CONFLICT")
            return cached[0]
        payload = {
            "schema_version": record.schema_version,
            "symbol": record.symbol,
            "expiry_yyyymmdd": record.expiry_yyyymmdd,
            "environment": record.environment,
            "source": record.source,
            "endpoint": record.endpoint,
            "tr_id": record.tr_id,
            "requested_at_utc": record.requested_at_utc,
            "received_at_utc": record.received_at_utc,
            "http_status": record.http_status,
            "rt_cd": record.rt_cd,
            "msg_cd": record.msg_cd,
            "response_field": record.response_field,
            "raw_response_sha256": record.raw_response_sha256,
            "master_sha256": record.master_sha256,
            "raw_response": record.raw_response,
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        path = self.cache_dir / f"expiry_{record.symbol}_{digest[:8]}.json"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_APPEND_ONLY_FILENAME_COLLISION")
        with path.open("xb") as target:
            target.write(encoded)
        return record

    def record_verified_response(
        self,
        *,
        symbol: str,
        response: Mapping[str, Any],
        http_status: int,
        requested_at_utc: str,
        received_at_utc: str,
    ) -> KISOptionExpiryRecord:
        """Import a previously captured, successful KIS read-only response without re-querying."""
        if http_status != 200 or str(response.get("rt_cd")) != "0":
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_EVIDENCE_NOT_SUCCESSFUL")
        output = response.get("output1")
        if isinstance(output, list):
            output = output[0] if output and isinstance(output[0], Mapping) else {}
        if not isinstance(output, Mapping):
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_OUTPUT1_REQUIRED")
        try:
            expiry = require_exact_option_expiry(str(output.get("futs_last_tr_date") or "").strip())
        except CanonicalOptionExpiryError as exc:
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_FUTS_LAST_TR_DATE_REQUIRED") from exc
        response_dict = dict(response)
        response_hash = hashlib.sha256(self._canonical_json(response_dict)).hexdigest()
        record = KISOptionExpiryRecord(
            symbol=str(symbol).strip(),
            expiry_yyyymmdd=expiry,
            environment=self.environment,
            source="KIS_REST:futs_last_tr_date",
            endpoint=EXPIRY_ENDPOINT,
            tr_id=EXPIRY_TR_ID,
            requested_at_utc=requested_at_utc,
            received_at_utc=received_at_utc,
            http_status=http_status,
            rt_cd="0",
            msg_cd=str(response.get("msg_cd")) if response.get("msg_cd") is not None else None,
            response_field="output1.futs_last_tr_date",
            raw_response_sha256=response_hash,
            master_sha256=self.master_sha256,
            raw_response=response_dict,
        )
        return self._append_record(record)

    def resolve(self, symbol: str) -> KISOptionExpiryRecord:
        clean_symbol = str(symbol).strip()
        cached = self._cached_records(clean_symbol)
        if cached:
            return sorted(cached, key=lambda item: item.received_at_utc)[0]
        if not self.auth_manager.has_credentials():
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_VTS_CREDENTIALS_MISSING")

        self._limiter.wait()
        requested_at = self._now().astimezone(timezone.utc).isoformat()
        try:
            http_status, response = self.transport.request_price(clean_symbol)
        except Exception as exc:
            body = getattr(exc, "kis_error_body", {})
            code = body.get("msg_cd") if isinstance(body, Mapping) else None
            if code == "EGW00201":
                raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_RATE_LIMIT_EGW00201_NO_AUTO_RETRY") from exc
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_REQUEST_FAILED_NO_AUTO_RETRY") from exc
        received_at = self._now().astimezone(timezone.utc).isoformat()
        if http_status != 200:
            raise KISOptionExpiryResolutionError(f"KIS_OPTION_EXPIRY_HTTP_STATUS_{http_status}")
        if not isinstance(response, Mapping) or str(response.get("rt_cd")) != "0":
            code = response.get("msg_cd") if isinstance(response, Mapping) else None
            raise KISOptionExpiryResolutionError(f"KIS_OPTION_EXPIRY_API_ERROR:{code or 'UNKNOWN'}")
        output = response.get("output1")
        if isinstance(output, list):
            output = output[0] if output and isinstance(output[0], Mapping) else {}
        if not isinstance(output, Mapping):
            output = response.get("output")
        if not isinstance(output, Mapping):
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_OUTPUT1_REQUIRED")
        raw_expiry = str(output.get("futs_last_tr_date") or "").strip()
        try:
            expiry = require_exact_option_expiry(raw_expiry)
        except CanonicalOptionExpiryError as exc:
            raise KISOptionExpiryResolutionError("KIS_OPTION_EXPIRY_FUTS_LAST_TR_DATE_REQUIRED") from exc
        response_dict = dict(response)
        response_hash = hashlib.sha256(self._canonical_json(response_dict)).hexdigest()
        record = KISOptionExpiryRecord(
            symbol=clean_symbol,
            expiry_yyyymmdd=expiry,
            environment=self.environment,
            source="KIS_REST:futs_last_tr_date",
            endpoint=EXPIRY_ENDPOINT,
            tr_id=EXPIRY_TR_ID,
            requested_at_utc=requested_at,
            received_at_utc=received_at,
            http_status=http_status,
            rt_cd="0",
            msg_cd=str(response.get("msg_cd")) if response.get("msg_cd") is not None else None,
            response_field="output1.futs_last_tr_date",
            raw_response_sha256=response_hash,
            master_sha256=self.master_sha256,
            raw_response=response_dict,
        )
        return self._append_record(record)
