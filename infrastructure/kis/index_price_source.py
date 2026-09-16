from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from contracts.kis_index_price_source import (
    KIS_INDEX_PRICE_PATH,
    KIS_INDEX_PRICE_TR_ID,
    KOSPI200_INDEX_CODE,
    KISIndexPriceObservation,
)
from infrastructure.kis.auth import KISAuthManager


class KISIndexPriceSourceError(RuntimeError):
    """Raised when an authoritative KIS index-price response is unusable."""


class KISKOSPI200IndexPriceSource:
    """Fetch the authoritative KOSPI200 index price from KIS REST."""

    def __init__(
        self,
        auth: KISAuthManager,
        *,
        urlopen: Callable[..., Any] = urlopen,
        timeout: float = 10.0,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._auth = auth
        self._urlopen = urlopen
        self._timeout = timeout
        self._clock = clock
        self._latest: KISIndexPriceObservation | None = None

    @staticmethod
    def _parse_price(output: dict[str, Any]) -> Decimal:
        raw = output.get("bstp_nmix_prpr")
        try:
            price = Decimal(str(raw).strip())
        except (InvalidOperation, AttributeError):
            raise KISIndexPriceSourceError("KIS_INDEX_PRICE_VALUE_UNAVAILABLE") from None
        if price <= 0:
            raise KISIndexPriceSourceError("KIS_INDEX_PRICE_VALUE_UNAVAILABLE")
        return price

    def refresh(self) -> KISIndexPriceObservation:
        if not self._auth.has_credentials():
            raise KISIndexPriceSourceError("KIS_INDEX_PRICE_CREDENTIALS_UNAVAILABLE")
        params = urlencode({
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": KOSPI200_INDEX_CODE,
        })
        request = Request(
            f"{self._auth.base_url}{KIS_INDEX_PRICE_PATH}?{params}",
            headers=self._auth.get_auth_headers(KIS_INDEX_PRICE_TR_ID),
            method="GET",
        )
        try:
            with self._urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise KISIndexPriceSourceError("KIS_INDEX_PRICE_REQUEST_FAILED") from exc
        if str(payload.get("rt_cd", "")) != "0":
            raise KISIndexPriceSourceError(
                f"KIS_INDEX_PRICE_API_ERROR:{payload.get('msg_cd', '')}"
            )
        output = payload.get("output")
        if not isinstance(output, dict):
            raise KISIndexPriceSourceError("KIS_INDEX_PRICE_OUTPUT_UNAVAILABLE")
        observation = KISIndexPriceObservation(
            underlying_symbol="KOSPI200",
            index_code=KOSPI200_INDEX_CODE,
            price=self._parse_price(output),
            observed_at=self._clock(),
            source=f"KIS:{KIS_INDEX_PRICE_TR_ID}:{KOSPI200_INDEX_CODE}",
        )
        self._latest = observation
        return observation

    def get_latest(self, underlying_symbol: str = "KOSPI200") -> KISIndexPriceObservation | None:
        if str(underlying_symbol).strip() != "KOSPI200":
            return None
        return self._latest
