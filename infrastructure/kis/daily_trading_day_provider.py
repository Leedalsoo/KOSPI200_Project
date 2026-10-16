"""KIS market-time endpoint as a bounded daily trading-session source.

The endpoint confirms only the dates explicitly returned in date1..date5.
A date absent from that rolling window is UNKNOWN, never inferred to be a
holiday or a trading day. Successful raw responses are persisted immutably.
"""
from __future__ import annotations
from contracts.trading_date import format_trading_date, parse_trading_date

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from infrastructure.kis.auth import KISAuthManager

KIS_MARKET_TIME_TR_ID = "HHMCM000002C0"
KIS_MARKET_TIME_PATH = "/uapi/domestic-stock/v1/quotations/market-time"


class KISDailyTradingDayError(RuntimeError):
    """Raised when the KIS daily trading-day response is not authoritative."""


@dataclass(frozen=True)
class KISDailyTradingDaySnapshot:
    environment: str
    fetched_at_utc: str
    source_today: date
    trading_dates: frozenset[date]
    session_open: str
    session_close: str
    response_sha256: str
    evidence_path: str


class KISDailyTradingDayProvider:
    """Fetch and cache KIS-confirmed dates from the rolling market-time response."""

    def __init__(
        self,
        *,
        auth_manager: Optional[KISAuthManager] = None,
        evidence_dir: str | Path = "data/reference/kis/daily_trading_day_snapshots",
        max_age_seconds: int = 300,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self._auth_manager = auth_manager
        self._evidence_dir = Path(evidence_dir)
        self._max_age = timedelta(seconds=max(1, int(max_age_seconds)))
        self._urlopen = urlopen
        self._snapshot: Optional[KISDailyTradingDaySnapshot] = None
        self._response_payload: Optional[Mapping[str, Any]] = None

    @property
    def snapshot(self) -> Optional[KISDailyTradingDaySnapshot]:
        return self._snapshot

    def is_confirmed_trading_day(self, target_date: date) -> Optional[bool]:
        snapshot = self._snapshot
        if snapshot is None or self._is_stale(snapshot):
            snapshot = self.refresh()
        # Positive confirmation only. Absence from a rolling window is UNKNOWN.
        if target_date in snapshot.trading_dates:
            return True
        return None

    def _is_stale(self, snapshot: KISDailyTradingDaySnapshot) -> bool:
        try:
            fetched = datetime.fromisoformat(snapshot.fetched_at_utc)
            return datetime.now(timezone.utc) - fetched >= self._max_age
        except ValueError:
            return True

    def refresh(self) -> KISDailyTradingDaySnapshot:
        auth = self._auth_manager
        if auth is None:
            auth = KISAuthManager.from_env(is_vts=True)
            self._auth_manager = auth
        if not auth.has_credentials():
            raise KISDailyTradingDayError("KIS_DAILY_CALENDAR_CREDENTIALS_MISSING")

        request = urllib.request.Request(
            f"{auth.base_url}{KIS_MARKET_TIME_PATH}",
            headers=auth.get_auth_headers(tr_id=KIS_MARKET_TIME_TR_ID),
            method="GET",
        )
        try:
            with self._urlopen(request, timeout=auth.timeout) as response:
                status = int(getattr(response, "status", response.getcode()))
                raw = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            digest = hashlib.sha256(body).hexdigest()
            raise KISDailyTradingDayError(
                f"KIS_DAILY_CALENDAR_HTTP_{exc.code}:sha256={digest}"
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise KISDailyTradingDayError(
                f"KIS_DAILY_CALENDAR_TRANSPORT_ERROR:{type(exc).__name__}"
            ) from exc

        digest = hashlib.sha256(raw).hexdigest()
        if status != 200:
            raise KISDailyTradingDayError(f"KIS_DAILY_CALENDAR_HTTP_{status}:sha256={digest}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KISDailyTradingDayError("KIS_DAILY_CALENDAR_INVALID_JSON") from exc
        if not isinstance(payload, Mapping) or str(payload.get("rt_cd", "")) != "0":
            code = str(payload.get("msg_cd", "UNKNOWN")) if isinstance(payload, Mapping) else "INVALID"
            raise KISDailyTradingDayError(f"KIS_DAILY_CALENDAR_API_ERROR:{code}")

        output = payload.get("output1")
        if not isinstance(output, Mapping):
            raise KISDailyTradingDayError("KIS_DAILY_CALENDAR_OUTPUT1_MISSING")
        today_raw = str(output.get("today", "")).strip()
        try:
            source_today = parse_trading_date(today_raw)
        except ValueError as exc:
            raise KISDailyTradingDayError("KIS_DAILY_CALENDAR_TODAY_INVALID") from exc
        if len(today_raw) != 8 or not today_raw.isdigit():
            raise KISDailyTradingDayError("KIS_DAILY_CALENDAR_TODAY_INVALID")

        trading_dates: set[date] = set()
        for field in ("date1", "date2", "date3", "date4", "date5"):
            raw_date = str(output.get(field, "")).strip()
            if not raw_date:
                continue
            if len(raw_date) != 8 or not raw_date.isdigit():
                raise KISDailyTradingDayError(f"KIS_DAILY_CALENDAR_{field.upper()}_INVALID")
            try:
                parsed = parse_trading_date(raw_date)
            except ValueError as exc:
                raise KISDailyTradingDayError(
                    f"KIS_DAILY_CALENDAR_{field.upper()}_INVALID"
                ) from exc
            trading_dates.add(parsed)
        if not trading_dates or source_today not in trading_dates:
            raise KISDailyTradingDayError("KIS_DAILY_CALENDAR_TODAY_NOT_IN_CONFIRMED_DATES")

        fetched_at = datetime.now(timezone.utc)
        self._evidence_dir.mkdir(parents=True, exist_ok=True)
        stamp = fetched_at.strftime("%Y%m%dT%H%M%S%fZ")
        evidence_path = self._evidence_dir / f"{stamp}_{digest[:12]}.json"
        evidence = {
            "schema_version": "kis-daily-trading-day-snapshot-v1",
            "source": "KIS",
            "environment": "VTS" if getattr(auth, "is_vts", True) else "LIVE",
            "endpoint": KIS_MARKET_TIME_PATH,
            "tr_id": KIS_MARKET_TIME_TR_ID,
            "http_status": status,
            "rt_cd": "0",
            "source_today": format_trading_date(source_today),
            "confirmed_trading_dates": sorted(format_trading_date(value) for value in trading_dates),
            "session_open": str(output.get("s_time", "")).strip(),
            "session_close": str(output.get("e_time", "")).strip(),
            "fetched_at_utc": fetched_at.isoformat(),
            "raw_response_sha256": digest,
            "raw_response": payload,
            "coverage_note": "Only listed dates are positively confirmed; unlisted dates are UNKNOWN.",
        }
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._response_payload = payload
        self._snapshot = KISDailyTradingDaySnapshot(
            environment=str(evidence["environment"]),
            fetched_at_utc=fetched_at.isoformat(),
            source_today=source_today,
            trading_dates=frozenset(trading_dates),
            session_open=evidence["session_open"],
            session_close=evidence["session_close"],
            response_sha256=digest,
            evidence_path=str(evidence_path),
        )
        return self._snapshot
