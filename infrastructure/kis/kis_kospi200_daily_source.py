from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from contracts.kis_kospi200_daily_source import (
    KIS_KOSPI200_DAILY_PATH, KIS_KOSPI200_DAILY_TR_ID, KOSPI200_INDEX_CODE,
    KOSPI200DailyContext,
)
from infrastructure.kis.auth import KISAuthManager


class KISKOSPI200DailySourceError(RuntimeError):
    pass


class KISKOSPI200DailySource:
    """Authoritative KIS KOSPI200 daily open/previous-close source."""

    def __init__(self, auth: KISAuthManager, *, urlopen: Callable[..., Any] = urlopen, timeout: float = 10.0) -> None:
        self._auth = auth
        self._urlopen = urlopen
        self._timeout = timeout
        self._cache: dict[date, KOSPI200DailyContext] = {}

    @staticmethod
    def _decimal(row: dict[str, Any], key: str) -> Decimal:
        try:
            value = Decimal(str(row.get(key, "")).strip())
        except (InvalidOperation, AttributeError):
            raise KISKOSPI200DailySourceError(f"KIS_KOSPI200_DAILY_{key.upper()}_INVALID") from None
        if value <= 0:
            raise KISKOSPI200DailySourceError(f"KIS_KOSPI200_DAILY_{key.upper()}_UNAVAILABLE")
        return value

    @staticmethod
    def _date(row: dict[str, Any]) -> date:
        raw = str(row.get("stck_bsop_date", "")).strip()
        try:
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        except (ValueError, IndexError):
            raise KISKOSPI200DailySourceError("KIS_KOSPI200_DAILY_DATE_INVALID") from None

    def get_context(self, trading_date: date) -> KOSPI200DailyContext | None:
        cached = self._cache.get(trading_date)
        if cached is not None:
            return cached
        if not self._auth.has_credentials():
            raise KISKOSPI200DailySourceError("KIS_KOSPI200_DAILY_CREDENTIALS_UNAVAILABLE")
        params = urlencode({
            "FID_PERIOD_DIV_CODE": "D",
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": KOSPI200_INDEX_CODE,
            "FID_INPUT_DATE_1": trading_date.strftime("%Y%m%d"),
        })
        request = Request(
            f"{self._auth.base_url}{KIS_KOSPI200_DAILY_PATH}?{params}",
            headers=self._auth.get_auth_headers(KIS_KOSPI200_DAILY_TR_ID),
            method="GET",
        )
        try:
            with self._urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise KISKOSPI200DailySourceError("KIS_KOSPI200_DAILY_REQUEST_FAILED") from exc
        if str(payload.get("rt_cd", "")) != "0":
            raise KISKOSPI200DailySourceError(f"KIS_KOSPI200_DAILY_API_ERROR:{payload.get('msg_cd', '')}")
        rows = payload.get("output2") or []
        if isinstance(rows, dict):
            rows = [rows]
        parsed = sorted((row for row in rows if isinstance(row, dict)), key=lambda row: str(row.get("stck_bsop_date", "")), reverse=True)
        source_name = f"KIS:{KIS_KOSPI200_DAILY_TR_ID}:{KOSPI200_INDEX_CODE}"
        for index, current in enumerate(parsed):
            current_date = self._date(current)
            if index + 1 >= len(parsed):
                continue
            previous = parsed[index + 1]
            previous_date = self._date(previous)
            if previous_date >= current_date:
                continue
            self._cache[current_date] = KOSPI200DailyContext(
                trading_date=current_date,
                open_price=self._decimal(current, "bstp_nmix_oprc"),
                previous_close=self._decimal(previous, "bstp_nmix_prpr"),
                source=source_name,
            )
        return self._cache.get(trading_date)
