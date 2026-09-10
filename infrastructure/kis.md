KIS OAuth 인증 및 KIS 외부 API 구현체 경계.

kis_auth_implementation.md

[Child Page] auth.py
```python
"""KIS OAuth2 authentication adapter for OptionProject infrastructure."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

KIS_VTS_BASE_URL = "https://openapivts.koreainvestment.com:29443"
KIS_REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
KIS_TOKEN_PATH = "/oauth2/tokenP"


class KISAuthError(Exception):
    """Raised when KIS OAuth2 authentication cannot produce a usable token."""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        response_data: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.response_data = dict(response_data or {})


@dataclass
class KISAuthToken:
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 86400
    token_expired_at: float = 0.0
    expired_at_str: Optional[str] = None
    issued_at: float = field(default_factory=time.time)

    def is_valid(self, buffer_seconds: int = 60) -> bool:
        return (
            bool(self.access_token.strip())
            and not self.access_token.startswith("MOCK_")
            and time.time() < self.token_expired_at - buffer_seconds
        )

    @classmethod
    def from_response(
        cls,
        data: Mapping[str, Any],
        issued_at: Optional[float] = None,
    ) -> "KISAuthToken":
        now = time.time() if issued_at is None else issued_at
        expires_in = int(data.get("expires_in", 86400))
        expired_at_str = data.get("access_token_token_expired")

        token_expired_at = now + expires_in
        if expired_at_str:
            try:
                kst = timezone(timedelta(hours=9))
                token_expired_at = datetime.strptime(
                    str(expired_at_str).strip(), "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=kst).timestamp()
            except (TypeError, ValueError):
                pass

        return cls(
            access_token=str(data.get("access_token", "")),
            token_type=str(data.get("token_type", "Bearer")),
            expires_in=expires_in,
            token_expired_at=token_expired_at,
            expired_at_str=str(expired_at_str) if expired_at_str else None,
            issued_at=now,
        )


def _load_env_file_fallback(env_path: str = ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if not os.path.exists(env_path):
        return values
    try:
        with open(env_path, encoding="utf-8") as source:
            for raw_line in source:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'").strip('"')
    except OSError as exc:
        logger.warning("Failed to read KIS env file %s: %s", env_path, exc)
    return values


class KISAuthManager:
    """Owns KIS token issuance, cache, expiry and request auth headers."""

    def __init__(
        self,
        app_key: str = "",
        app_secret: str = "",
        base_url: str = KIS_VTS_BASE_URL,
        is_vts: bool = True,
        timeout: float = 10.0,
        cache_file_path: Optional[str] = None,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.app_key = app_key.strip()
        self.app_secret = app_secret.strip()
        self.base_url = base_url.rstrip("/")
        self.is_vts = is_vts
        self.timeout = timeout
        self.cache_file_path = cache_file_path
        self._urlopen = urlopen
        self._current_token: Optional[KISAuthToken] = None
        if cache_file_path:
            self._load_token_from_cache()

    @classmethod
    def from_env(
        cls,
        is_vts: bool = True,
        env_file: Optional[str] = None,
        base_url: Optional[str] = None,
        cache_file_path: Optional[str] = None,
        **kwargs: Any,
    ) -> "KISAuthManager":
        fallback = _load_env_file_fallback(env_file or ".env")

        def value(name: str) -> str:
            return os.getenv(name) or fallback.get(name, "")

        app_key = (
            value("KIS_VTS_APP_KEY") if is_vts else value("KIS_REAL_APP_KEY")
        ) or value("KIS_APP_KEY") or value("REAL_BROKER_APP_KEY")
        app_secret = (
            value("KIS_VTS_APP_SECRET") if is_vts else value("KIS_REAL_APP_SECRET")
        ) or value("KIS_APP_SECRET") or value("REAL_BROKER_APP_SECRET")

        resolved_base_url = (
            base_url
            or value("KIS_BASE_URL")
            or (KIS_VTS_BASE_URL if is_vts else KIS_REAL_BASE_URL)
        )
        if cache_file_path is None:
            prefix = "vts" if is_vts else "real"
            cache_file_path = os.path.join("data", f".kis_token_cache_{prefix}.json")

        return cls(
            app_key=app_key,
            app_secret=app_secret,
            base_url=resolved_base_url,
            is_vts=is_vts,
            cache_file_path=cache_file_path,
            **kwargs,
        )

    def has_credentials(self) -> bool:
        return bool(self.app_key and self.app_secret)

    def _load_token_from_cache(self) -> None:
        if not self.cache_file_path or not os.path.exists(self.cache_file_path):
            return
        try:
            with open(self.cache_file_path, "r", encoding="utf-8") as source:
                token = KISAuthToken(**json.load(source))
            if token.is_valid():
                self._current_token = token
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Failed to load KIS token cache: %s", exc)

    def _save_token_to_cache(self, token: KISAuthToken) -> None:
        if not self.cache_file_path:
            return
        try:
            directory = os.path.dirname(self.cache_file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.cache_file_path, "w", encoding="utf-8") as target:
                json.dump(asdict(token), target, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("Failed to save KIS token cache: %s", exc)

    def issue_token(self) -> KISAuthToken:
        if not self.has_credentials():
            raise KISAuthError("KIS AppKey or AppSecret is missing.")

        payload = json.dumps({
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{KIS_TOKEN_PATH}",
            data=payload,
            headers={"Content-Type": "application/json; charset=UTF-8"},
            method="POST",
        )

        try:
            with self._urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                error_data = json.loads(body)
            except json.JSONDecodeError:
                error_data = {}
            if (
                error_data.get("error_code") == "EGW00133"
                and self._current_token
                and self._current_token.is_valid()
            ):
                return self._current_token
            raise KISAuthError(
                f"HTTP Error {exc.code} ({exc.reason}): {body}",
                error_code=error_data.get("error_code") or str(exc.code),
                response_data=error_data,
            ) from exc
        except urllib.error.URLError as exc:
            raise KISAuthError(f"Network connection failed: {exc.reason}") from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise KISAuthError(f"Unexpected token issuance failure: {exc}") from exc

        if not data.get("access_token"):
            error_code = data.get("error_code") or data.get("msg_cd") or "UNKNOWN_ERR"
            description = data.get("error_description") or data.get("msg1") or str(data)
            raise KISAuthError(
                f"Token missing in response: [{error_code}] {description}",
                error_code=error_code,
                response_data=data,
            )

        token = KISAuthToken.from_response(data)
        self._current_token = token
        self._save_token_to_cache(token)
        return token

    def get_access_token(self, force_refresh: bool = False) -> str:
        if force_refresh or not self._current_token or not self._current_token.is_valid():
            self.issue_token()
        if not self._current_token:
            raise KISAuthError("Failed to obtain a valid access token.")
        return self._current_token.access_token

    def get_token_info(self) -> Optional[KISAuthToken]:
        return self._current_token

    def get_authorization_header(self, force_refresh: bool = False) -> str:
        token = self.get_access_token(force_refresh=force_refresh)
        token_type = self._current_token.token_type if self._current_token else "Bearer"
        return f"{token_type} {token}"

    def get_auth_headers(
        self,
        tr_id: str = "",
        force_refresh: bool = False,
    ) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "authorization": self.get_authorization_header(force_refresh),
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        if tr_id:
            headers["tr_id"] = tr_id
        return headers

```

[Child Page] holiday_provider.py
```python
"""KIS official chk-holiday API provider for OptionProject infrastructure."""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import date
from typing import Any, Callable, Mapping, Optional, Protocol, Set

from infrastructure.kis.auth import KISAuthManager

logger = logging.getLogger(__name__)

KIS_HOLIDAY_TR_ID = "CTCA0903R"
KIS_HOLIDAY_PATH = "/uapi/domestic-stock/v1/quotations/chk-holiday"


class KISHolidayError(Exception):
    """Base error for KIS holiday source failures."""


class KISHolidayParseError(KISHolidayError):
    """Raised when a KIS holiday response cannot be parsed."""


class KISHolidayUnavailableError(KISHolidayError):
    """Raised when strict mode requires an unavailable holiday source."""


class HolidayProvider(Protocol):
    def is_holiday(self, target_date: date) -> bool: ...
    def get_holidays_for_year(self, year: int) -> Set[date]: ...


def parse_kis_holiday_output(output: list[Mapping[str, Any]]) -> Set[date]:
    holidays: Set[date] = set()
    for item in output:
        if item.get("opnd_yn") != "N":
            continue
        raw = str(item.get("bass_dt", "")).strip()
        if len(raw) == 8 and raw.isdigit():
            try:
                holidays.add(date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])))
            except ValueError:
                continue
    return holidays


class KISHolidayProvider:
    """Loads official KIS holiday/open-day data without owning OAuth."""

    def __init__(
        self,
        holidays: Optional[Set[date]] = None,
        auth_manager: Optional[KISAuthManager] = None,
        auto_load: bool = False,
        target_year: Optional[int] = None,
        strict_mode: bool = False,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self._holidays: Set[date] = set(holidays or [])
        self._auth_manager = auth_manager
        self._target_year = target_year or date.today().year
        self.strict_mode = strict_mode
        self._urlopen = urlopen
        self._last_error: Optional[str] = None
        self._loaded_years: Set[int] = {d.year for d in self._holidays}

        if auto_load and not self._holidays:
            self.load_from_kis_api(self._target_year)

    @property
    def is_loaded(self) -> bool:
        return bool(self._loaded_years) and self._last_error is None

    @property
    def total_holidays(self) -> int:
        return len(self._holidays)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def is_holiday(self, target_date: date) -> bool:
        if self.strict_mode and target_date.year not in self._loaded_years:
            raise KISHolidayUnavailableError(
                f"KIS holiday data unavailable for year {target_date.year}: {self._last_error}"
            )
        return target_date in self._holidays

    def get_holidays_for_year(self, year: int) -> Set[date]:
        return {d for d in self._holidays if d.year == year}

    def load_from_response_data(self, response_data: Mapping[str, Any], year: Optional[int] = None) -> int:
        if not isinstance(response_data, Mapping):
            self._last_error = "Invalid response format: expected mapping"
            raise KISHolidayParseError(self._last_error)

        if response_data.get("rt_cd") != "0":
            self._last_error = (
                f"KIS API error (rt_cd={response_data.get('rt_cd')}, "
                f"msg_cd={response_data.get('msg_cd', '')}): {response_data.get('msg1', '')}"
            ).strip()
            raise KISHolidayError(self._last_error)

        output = response_data.get("output", [])
        if not isinstance(output, list):
            self._last_error = "Invalid output field: expected list"
            raise KISHolidayParseError(self._last_error)

        parsed = parse_kis_holiday_output([item for item in output if isinstance(item, Mapping)])
        self._holidays.update(parsed)
        resolved_year = year or (min((d.year for d in parsed), default=None))
        if resolved_year is not None:
            self._loaded_years.add(resolved_year)
        self._last_error = None
        return len(parsed)

    def load_from_kis_api(self, target_year: Optional[int] = None) -> int:
        year = target_year or self._target_year
        try:
            auth = self._auth_manager
            if auth is None:
                auth = KISAuthManager.from_env()
                self._auth_manager = auth

            if not auth.has_credentials():
                self._last_error = "KIS credentials (AppKey/Secret) are missing."
                return 0

            endpoint = f"{auth.base_url}{KIS_HOLIDAY_PATH}"
            base_dt = f"{year}0101"
            ctx_area_nk = ""
            ctx_area_fk = ""
            total_loaded = 0

            for _ in range(15):
                query = urllib.parse.urlencode({
                    "BASS_DT": base_dt,
                    "CTX_AREA_NK": ctx_area_nk,
                    "CTX_AREA_FK": ctx_area_fk,
                })
                request = urllib.request.Request(
                    f"{endpoint}?{query}",
                    headers=auth.get_auth_headers(tr_id=KIS_HOLIDAY_TR_ID),
                    method="GET",
                )
                with self._urlopen(request, timeout=auth.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))

                total_loaded += self.load_from_response_data(data, year=year)
                ctx_area_nk = str(data.get("ctx_area_nk", "")).strip()
                ctx_area_fk = str(data.get("ctx_area_fk", "")).strip()
                if not ctx_area_nk and not ctx_area_fk:
                    break

                output = data.get("output", [])
                if isinstance(output, list) and output:
                    last_dt = str(output[-1].get("bass_dt", ""))
                    if last_dt.startswith(str(year + 1)):
                        break
                    if last_dt:
                        base_dt = last_dt

            self._loaded_years.add(year)
            self._last_error = None
            return total_loaded
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("KIS holiday API load failed: %s", exc)
            return 0
```
    - Infrastructure provider only; OAuth is delegated to KISAuthManager.
    - Core does not import this provider.
    - Empty/failed responses are not silently converted into verified holiday data.

[Child Page] trading_calendar.py
```python
"""Production TradingCalendar backed by a holiday provider."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol


class HolidayProvider(Protocol):
    def is_holiday(self, target_date: date) -> bool: ...


class ProductionTradingCalendar:
    """KRX weekday calendar; holiday knowledge is injected from Infrastructure."""

    def __init__(self, holiday_provider: HolidayProvider) -> None:
        self._holiday_provider = holiday_provider

    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5 and not self._holiday_provider.is_holiday(value)

    def prev_trading_day(self, value: date) -> date:
        current = value - timedelta(days=1)
        while not self.is_trading_day(current):
            current -= timedelta(days=1)
        return current

    def trading_days_between(self, start: date, end: date) -> int:
        if start == end:
            return 0
        sign = 1 if end > start else -1
        current, stop = (start, end) if sign > 0 else (end, start)
        count = 0
        while current < stop:
            current += timedelta(days=1)
            if self.is_trading_day(current):
                count += 1
        return sign * count
```
    - Implements only the existing TradingCalendar capability.
    - Weekends are non-trading days; official holidays are delegated to KISHolidayProvider.
    - Core remains independent of this implementation.

[Child Page] futures_market_transport.py
```python
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.request import Request, urlopen

from infrastructure.kis.auth import KISAuthManager


class FuturesMarketTransportError(RuntimeError):
    """Raised when KIS futures market transport cannot connect or subscribe."""


class FuturesMarketTransport(Protocol):
    async def connect(self) -> None: ...
    async def subscribe(self, tr_id: str, symbol: str) -> None: ...
    async def unsubscribe(self, tr_id: str, symbol: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class KISFuturesMarketTransportConfig:
    is_vts: bool = False
    ws_url: str | None = None
    approval_path: str = "/oauth2/Approval"
    timeout: float = 10.0
    ping_interval: float | None = None

    @property
    def default_ws_url(self) -> str:
        return "ws://ops.koreainvestment.com:31000" if self.is_vts else "ws://ops.koreainvestment.com:21000"


class KISWebSocketApprovalKeyProvider:
    def __init__(self, auth: KISAuthManager, *, approval_path: str = "/oauth2/Approval", timeout: float = 10.0) -> None:
        self._auth = auth
        self._approval_path = approval_path
        self._timeout = timeout

    def issue(self) -> str:
        if not self._auth.has_credentials():
            raise FuturesMarketTransportError("KIS credentials are required for websocket approval key")
        payload = {"grant_type": "client_credentials", "appkey": self._auth.app_key, "secretkey": self._auth.app_secret}
        request = Request(
            f"{self._auth.base_url.rstrip('/')}{self._approval_path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise FuturesMarketTransportError("KIS websocket approval-key request failed") from exc
        approval_key = str(data.get("approval_key", "")).strip()
        if not approval_key:
            raise FuturesMarketTransportError("KIS websocket approval_key is missing")
        return approval_key


class KISFuturesMarketTransport:
    def __init__(self, auth: KISAuthManager, config: KISFuturesMarketTransportConfig | None = None) -> None:
        self._auth = auth
        self._config = config or KISFuturesMarketTransportConfig(is_vts=auth.is_vts)
        self._approval = KISWebSocketApprovalKeyProvider(auth, approval_path=self._config.approval_path, timeout=self._config.timeout)
        self._socket: Any = None
        self._connected = False

    async def connect(self) -> None:
        try:
            import websockets
            self._socket = await websockets.connect(
                self._config.ws_url or self._config.default_ws_url,
                ping_interval=self._config.ping_interval,
                open_timeout=self._config.timeout,
            )
        except Exception as exc:
            raise FuturesMarketTransportError("KIS futures websocket connection failed") from exc
        self._connected = True

    @staticmethod
    def _message(approval_key: str, tr_type: str, tr_id: str, symbol: str) -> str:
        return json.dumps({
            "header": {"approval_key": approval_key, "custtype": "P", "tr_type": tr_type, "content-type": "utf-8"},
            "body": {"input": {"tr_id": tr_id, "tr_key": symbol}},
        })

    async def subscribe(self, tr_id: str, symbol: str) -> None:
        await self._send_subscription("1", tr_id, symbol)

    async def unsubscribe(self, tr_id: str, symbol: str) -> None:
        await self._send_subscription("2", tr_id, symbol)

    async def _send_subscription(self, tr_type: str, tr_id: str, symbol: str) -> None:
        if not self._connected or self._socket is None:
            raise FuturesMarketTransportError("KIS futures websocket is not connected")
        if not tr_id.strip() or not symbol.strip():
            raise FuturesMarketTransportError("tr_id and symbol are required")
        approval_key = self._approval.issue()
        await self._socket.send(self._message(approval_key, tr_type, tr_id, symbol))

    async def recv(self) -> str:
        if not self._connected or self._socket is None:
            raise FuturesMarketTransportError("KIS futures websocket is not connected")
        value = await self._socket.recv()
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    async def close(self) -> None:
        socket = self._socket
        self._socket = None
        self._connected = False
        if socket is not None:
            await socket.close()
```
## 책임 경계
    - 기존 KISAuthManager를 재사용하여 credential을 별도 저장하지 않는다.
    - KIS 공식 /oauth2/Approval에서 WebSocket approval key를 발급한다.
    - 실전 ws://ops.koreainvestment.com:21000, VTS 31000을 명시적으로 분리한다.
    - tr_id와 shrn_iscd는 호출자가 공급하며 상품 코드를 하드코딩하지 않는다.
    - reconnect/backoff는 상위 Runtime lifecycle의 책임이다.

[Child Page] futures_market_consumer.py
```python
from __future__ import annotations

from collections.abc import Awaitable, Callable

from contracts.kis_index_futures_market_ws_adapter import KISIndexFuturesMarketWebSocketAdapter, KisIndexFuturesMarketObservation
from infrastructure.kis.futures_market_transport import FuturesMarketTransport

ObservationCallback = Callable[[KisIndexFuturesMarketObservation], Awaitable[None] | None]


class KISIndexFuturesMarketConsumer:
    TRADE_TR_ID = "H0IFCNT0"
    QUOTE_TR_ID = "H0IFASP0"

    def __init__(self, transport: FuturesMarketTransport, adapter: KISIndexFuturesMarketWebSocketAdapter, on_observation: ObservationCallback) -> None:
        self._transport = transport
        self._adapter = adapter
        self._on_observation = on_observation

    async def start(self, symbol: str, *, include_quote: bool = True) -> None:
        await self._transport.connect()
        await self._transport.subscribe(self.TRADE_TR_ID, symbol)
        if include_quote:
            await self._transport.subscribe(self.QUOTE_TR_ID, symbol)

    async def receive_once(self) -> KisIndexFuturesMarketObservation:
        observation = self._adapter.adapt(await self._transport.recv())
        result = self._on_observation(observation)
        if result is not None:
            await result
        return observation

    async def close(self) -> None:
        await self._transport.close()
```
## 책임 경계
    - transport → wire adapter → typed observation → callback의 실제 consumer 경계를 제공한다.
    - start()는 H0IFCNT0 체결과 H0IFASP0 호가를 동일한 KIS futures short code로 구독한다.
    - instrument_id, MarketState, Risk, OMS는 이 consumer에서 생성하거나 판단하지 않는다.

[Child Page] futures_market_consumer.py
```python
from __future__ import annotations

from collections.abc import Awaitable, Callable

from contracts.kis_index_futures_market_ws_adapter import KISIndexFuturesMarketWebSocketAdapter, KisIndexFuturesMarketObservation
from infrastructure.kis.futures_market_transport import FuturesMarketTransport

ObservationCallback = Callable[[KisIndexFuturesMarketObservation], Awaitable[None] | None]


class KISIndexFuturesMarketConsumer:
    TRADE_TR_ID = "H0IFCNT0"
    QUOTE_TR_ID = "H0IFASP0"

    def __init__(self, transport: FuturesMarketTransport, adapter: KISIndexFuturesMarketWebSocketAdapter, on_observation: ObservationCallback) -> None:
        self._transport = transport
        self._adapter = adapter
        self._on_observation = on_observation

    async def start(self, symbol: str, *, include_quote: bool = True) -> None:
        await self._transport.connect()
        await self._transport.subscribe(self.TRADE_TR_ID, symbol)
        if include_quote:
            await self._transport.subscribe(self.QUOTE_TR_ID, symbol)

    async def receive_once(self) -> KisIndexFuturesMarketObservation:
        observation = self._adapter.adapt(await self._transport.recv())
        result = self._on_observation(observation)
        if result is not None:
            await result
        return observation

    async def close(self) -> None:
        await self._transport.close()
```
## 책임 경계
    - transport → wire adapter → typed observation → callback의 실제 consumer 경계를 제공한다.
    - start()는 H0IFCNT0 체결과 H0IFASP0 호가를 동일한 KIS futures short code로 구독한다.
    - instrument_id, MarketState, Risk, OMS는 이 consumer에서 생성하거나 판단하지 않는다.
    - reconnect/backoff는 상위 Runtime lifecycle이 소유한다.

[Child Page] futures_execution_transport.py
```python
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from infrastructure.kis.auth import KISAuthManager


class FuturesExecutionTransportError(RuntimeError):
    """Raised when the KIS futures execution transport cannot operate safely."""


class FuturesExecutionTransport(Protocol):
    async def connect(self) -> None: ...
    async def subscribe(self, tr_id: str, tr_key: str) -> None: ...
    async def recv(self) -> str: ...
    async def cancel_recv(self) -> None: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class KISFuturesExecutionTransportConfig:
    is_vts: bool = False
    ws_url: str | None = None
    approval_path: str = "/oauth2/Approval"
    timeout: float = 10.0
    ping_interval: float | None = None

    @property
    def default_ws_url(self) -> str:
        return "ws://ops.koreainvestment.com:31000" if self.is_vts else "ws://ops.koreainvestment.com:21000"


class KISFuturesExecutionTransport:
    """Dedicated KIS H0IFCNI0 WebSocket transport.

    This transport is intentionally separate from FuturesMarketTransport. It owns
    execution-notice subscription and the AES-CBC decoding required for KIS's
    encrypted H0IFCNI0 data frames; it does not publish MarketState.
    """

    TR_ID = "H0IFCNI0"

    def __init__(self, auth: KISAuthManager, config: KISFuturesExecutionTransportConfig | None = None, *, socket_factory=None) -> None:
        self._auth = auth
        self._config = config or KISFuturesExecutionTransportConfig(is_vts=auth.is_vts)
        self._socket_factory = socket_factory
        self._socket: Any = None
        self._connected = False
        self._crypto: dict[str, tuple[str, str]] = {}
        self._subscription: tuple[str, str] | None = None

    def _issue_approval_key(self) -> str:
        if not self._auth.has_credentials():
            raise FuturesExecutionTransportError("KIS credentials are required for websocket approval key")
        payload = {"grant_type": "client_credentials", "appkey": self._auth.app_key, "secretkey": self._auth.app_secret}
        request = Request(
            f"{self._auth.base_url.rstrip('/')}{self._config.approval_path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._config.timeout) as response:
                data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise FuturesExecutionTransportError("KIS websocket approval-key request failed") from exc
        approval_key = str(data.get("approval_key", "")).strip()
        if not approval_key:
            raise FuturesExecutionTransportError("KIS websocket approval_key is missing")
        return approval_key

    async def connect(self) -> None:
        if self._connected or self._socket is not None:
            raise FuturesExecutionTransportError("KIS execution websocket is already connected")
        try:
            if self._socket_factory is not None:
                self._socket = await self._socket_factory(self._config.ws_url or self._config.default_ws_url)
            else:
                import websockets
                self._socket = await websockets.connect(
                    self._config.ws_url or self._config.default_ws_url,
                    ping_interval=self._config.ping_interval,
                    open_timeout=self._config.timeout,
                )
        except Exception as exc:
            raise FuturesExecutionTransportError("KIS execution websocket connection failed") from exc
        self._connected = True

    async def subscribe(self, tr_id: str, tr_key: str) -> None:
        if not self._connected or self._socket is None:
            raise FuturesExecutionTransportError("KIS execution websocket is not connected")
        if tr_id != self.TR_ID or not tr_key.strip():
            raise FuturesExecutionTransportError("H0IFCNI0 and HTS ID are required")
        requested = (tr_id, tr_key.strip())
        if self._subscription is not None:
            raise FuturesExecutionTransportError("KIS execution websocket subscription is already active")
        message = {
            "header": {
                "approval_key": self._issue_approval_key(),
                "custtype": "P",
                "tr_type": "1",
                "content-type": "utf-8",
            },
            "body": {"input": {"tr_id": tr_id, "tr_key": tr_key}},
        }
        await self._socket.send(json.dumps(message))
        self._subscription = requested

    @staticmethod
    def _decrypt(ciphertext_b64: str, key: str, iv: str) -> str:
        try:
            cipher = Cipher(algorithms.AES(key.encode("utf-8")), modes.CBC(iv.encode("utf-8")))
            decryptor = cipher.decryptor()
            encrypted = base64.b64decode(ciphertext_b64)
            padded = decryptor.update(encrypted) + decryptor.finalize()
            unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
            return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
        except Exception as exc:
            raise FuturesExecutionTransportError("invalid KIS H0IFCNI0 encrypted payload") from exc

    def _normalize(self, value: str | bytes) -> str | None:
        text = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        if text.startswith("{"):
            try:
                message = json.loads(text)
            except json.JSONDecodeError as exc:
                raise FuturesExecutionTransportError("invalid KIS websocket control message") from exc
            header = message.get("header", {})
            body = message.get("body", {})
            tr_id = str(header.get("tr_id", "")).strip()
            output = body.get("output") or {}
            if tr_id == self.TR_ID and body.get("rt_cd") == "0" and output.get("key") and output.get("iv"):
                self._crypto[tr_id] = (str(output["key"]), str(output["iv"]))
            return None

        parts = text.split("|")
        if len(parts) >= 4 and parts[1] == self.TR_ID:
            crypto = self._crypto.get(self.TR_ID)
            if crypto is None:
                raise FuturesExecutionTransportError("H0IFCNI0 crypto context is not established")
            plain = self._decrypt(parts[3], *crypto)
            field_count = len(plain.split("^"))
            return f"{parts[0]}|{parts[1]}|{field_count}|{plain}"
        return None

    async def recv(self) -> str:
        if not self._connected or self._socket is None:
            raise FuturesExecutionTransportError("KIS execution websocket is not connected")
        while True:
            normalized = self._normalize(await self._socket.recv())
            if normalized is not None:
                return normalized

    async def cancel_recv(self) -> None:
        """Explicitly interrupt a blocked recv without inventing a domain action."""
        await self.close()

    async def close(self) -> None:
        socket = self._socket
        self._socket = None
        self._connected = False
        self._subscription = None
        self._crypto.clear()
        if socket is not None:
            await socket.close()
```
    - Market transport와 분리된 execution 전용 WebSocket owner.
    - KIS /oauth2/Approval approval key를 사용한다.
    - H0IFCNI0은 HTS ID를 tr_key로 구독한다.
    - KIS subscription 응답에서 제공하는 AES key/IV를 보관하고 암호화된 execution frame만 복호화한다.
    - 복호화 후 기존 KISFuturesExecutionNoticeAdapter가 소비할 수 있는 H0IFCNI0 canonical wire envelope로 반환한다.
    - MarketState, instrument identity, order correlation을 생성하지 않는다.
    - cancel_recv()는 blocked recv()를 깨우기 위한 기술적 cancellation capability이며 주문 취소·포지션 청산을 수행하지 않는다.
    - 실제 네트워크 연결은 테스트에서 사용하지 않는다.

[Child Page] [LEGACY_MISPLACED] kis_futures_execution_consumer.py
```python
from __future__ import annotations

from typing import Awaitable, Callable

from environments.live.execution.kis_futures_execution_adapter import (
    KISFuturesExecutionContext,
    KISFuturesExecutionNoticeAdapter,
)
from environments.live.execution.kis_futures_execution_correlation_provider import (
    KISFuturesExecutionCorrelationProvider,
)


class KISFuturesExecutionConsumer:
    """Concrete H0IFCNI0 execution ingress.

    The consumer owns transport -> execution adapter -> OMS correlation ->
    ExecutionReport delivery. Position mutation remains downstream in the
    existing LiveExecutionPositionBridge.
    """

    def __init__(
        self,
        transport,
        adapter: KISFuturesExecutionNoticeAdapter,
        correlation_provider: KISFuturesExecutionCorrelationProvider,
        on_report: Callable[[object], Awaitable[None] | None],
    ) -> None:
        self._transport = transport
        self._adapter = adapter
        self._correlation_provider = correlation_provider
        self._on_report = on_report

    async def start(self, hts_id: str) -> None:
        if not hts_id.strip():
            raise ValueError("HTS ID is required")
        await self._transport.connect()
        await self._transport.subscribe(self._adapter.TR_ID, hts_id)

    async def receive_once(self):
        frame = await self._transport.recv()
        notice = self._adapter.parse(frame)
        correlation = self._correlation_provider.resolve(notice.broker_order_id)
        report = self._adapter.to_execution_report(
            notice,
            KISFuturesExecutionContext(
                correlation.client_order_id,
                correlation.order_quantity,
                correlation.prior_filled_quantity,
            ),
        )
        result = self._on_report(report)
        if hasattr(result, "__await__"):
            await result
        return report

    async def close(self) -> None:
        await self._transport.close()
```
    - H0IFCNI0 → ExecutionReport 실제 ingress를 제공한다.
    - client_order_id, 주문수량, prior filled quantity는 OMS-owned correlation provider에서만 받는다.
    - callback은 ExecutionReport만 전달하며 Position을 직접 변경하지 않는다.
    - 따라서 기존 ExecutionEventDeduplicator → OMS FSM → LiveExecutionPositionBridge → Position 경계를 재사용한다.
    - Market consumer를 import하거나 Market transport를 execution source로 사용하지 않는다.

[Child Page] [LEGACY_MISPLACED] test_kis_futures_execution_consumer.py
```python
import asyncio
import base64
import json

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from environments.live.execution.kis_futures_execution_adapter import KISFuturesExecutionNoticeAdapter
from environments.live.execution.kis_futures_execution_consumer import KISFuturesExecutionConsumer
from environments.live.execution.kis_futures_execution_correlation_provider import KISFuturesExecutionCorrelationProvider
from infrastructure.kis.futures_execution_transport import KISFuturesExecutionTransport


class FakeAuth:
    is_vts = False
    app_key = "APP"
    app_secret = "SECRET"
    base_url = "https://invalid.example"

    def has_credentials(self):
        return True


class FakeSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        return self.messages.pop(0)

    async def close(self):
        return None


def _encrypt(plain: str, key: str, iv: str) -> str:
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plain.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key.encode()), modes.CBC(iv.encode())).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(encrypted).decode()


def _plain_h0ifcni0_frame() -> str:
    values = [
        "C", "A", "B123", "O", "02", "00", "00", "K200", "2", "350.0",
        "101010", "N", "Y", "Y", "01", "5", "N", "KOSPI", "00", "1", "1", "350.0",
    ]
    return "^".join(values)


def test_execution_transport_decrypts_h0ifcni0_and_preserves_envelope():
    key = "0123456789abcdef0123456789abcdef"
    iv = "abcdef0123456789"
    socket = FakeSocket([
        json.dumps({"header": {"tr_id": "H0IFCNI0"}, "body": {"rt_cd": "0", "output": {"key": key, "iv": iv}}}),
        "1|H0IFCNI0|1|" + _encrypt(_plain_h0ifcni0_frame(), key, iv),
    ])

    async def socket_factory(_):
        return socket

    transport = KISFuturesExecutionTransport(FakeAuth(), socket_factory=socket_factory)
    transport._issue_approval_key = lambda: "approval-for-test"

    async def run():
        await transport.connect()
        await transport.subscribe("H0IFCNI0", "HTS01")
        return await transport.recv()

    frame = asyncio.run(run())
    assert frame == "1|H0IFCNI0|22|" + _plain_h0ifcni0_frame()
    assert json.loads(socket.sent[0])["body"]["input"] == {"tr_id": "H0IFCNI0", "tr_key": "HTS01"}


def test_execution_consumer_resolves_oms_context_and_emits_execution_report():
    key = "0123456789abcdef0123456789abcdef"
    iv = "abcdef0123456789"
    socket = FakeSocket([
        json.dumps({"header": {"tr_id": "H0IFCNI0"}, "body": {"rt_cd": "0", "output": {"key": key, "iv": iv}}}),
        "1|H0IFCNI0|1|" + _encrypt(_plain_h0ifcni0_frame(), key, iv),
    ])

    async def socket_factory(_):
        return socket

    transport = KISFuturesExecutionTransport(FakeAuth(), socket_factory=socket_factory)
    transport._issue_approval_key = lambda: "approval-for-test"

    correlation = type("Correlation", (), {
        "client_order_id": "C1",
        "order_quantity": 5,
        "prior_filled_quantity": 0,
    })()
    provider = KISFuturesExecutionCorrelationProvider({"B123": correlation})
    reports = []

    async def run():
        consumer = KISFuturesExecutionConsumer(
            transport,
            KISFuturesExecutionNoticeAdapter(),
            provider,
            reports.append,
        )
        await consumer.start("HTS01")
        return await consumer.receive_once()

    report = asyncio.run(run())
    assert report.client_order_id == "C1"
    assert report.broker_order_id == "B123"
    assert report.filled_quantity == 2
    assert report.remaining_quantity == 3
    assert len(reports) == 1
```
검증 목적은 실제 KIS 네트워크가 아니라 encrypted KIS frame → execution transport → H0IFCNI0 adapter → OMS correlation → ExecutionReport의 계약을 실제 실행 가능한 형태로 확인하는 것이다.