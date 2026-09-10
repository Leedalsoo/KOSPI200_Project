폴더: 외부 API, persistence, credential 등 구현체.

[Child Page] market_data
폴더 페이지

[Child Page] broker
폴더 페이지

[Child Page] persistence
폴더 페이지

[Child Page] config
폴더 페이지

[Child Page] credentials
폴더 페이지

[Child Page] monitoring
폴더 페이지

[Child Page] kis_production_trading_calendar_implementation.md
## No.160 구현 — OptionProject KIS 인증·Calendar Composition 실제 경로 조사
### 조사 결과
No.159의 다음 단계에 따라 OptionProject의 Application composition root, KIS 인증/HTTP Adapter, Runtime public entrypoint를 실제 페이지 기준으로 확인했다.
### 1. Application composition
현재 구현된 Application 계층은 다음과 같다.
    - application/runtime_controller/controller.py: EnvironmentHub를 받아 start/stop/status만 담당
    - application/environment_hub/factory.py: Virtual/High-Speed/Paper/Live EnvironmentBundle 선택 및 builder 주입 담당
    - 독립적인 application/bootstrap.py 실제 코드 페이지는 아직 없음
즉 현재 Application에는 Production Calendar를 조립해 OptionContractMaster에 주입하는 composition root가 아직 구현되어 있지 않다.
### 2. KIS 인증/HTTP Adapter
OptionProject/infrastructure에는 broker 폴더가 존재하지만 실제 KIS OAuth 인증 구현은 아직 이식되지 않았다.
최신 Reference option_program/broker/kis_auth.py에는 다음 재사용 대상이 존재한다.
    - KISAuthManager
    - KISAuthToken
    - KISAuthError
    - from_env()
    - get_auth_headers(tr_id=...)
    - OAuth token cache / expiry handling
따라서 OptionProject에 새 인증 체계를 만들면 Reference 기능 중복 및 credential semantics 분기가 발생한다.
### 3. Runtime public entrypoint
Reference의 실제 기본 Runtime 경로는:
OptionProgramRuntime()
→ create_default_krx_calendar(auto_load_kis=True)
→ create_default_option_master(calendar=self.calendar, auto_load_kis=True)
이다.
반면 OptionProject의 현재 RuntimeController는 EnvironmentBundle lifecycle만 관리하며 OptionContractMaster/TradingCalendar를 직접 생성하지 않는다.
따라서 현재 OptionProject에서 Production Calendar의 실제 조립 위치는 기존 RuntimeController 내부가 아니라 별도의 Application composition function/factory로 두는 것이 구조상 안전하다.
### 확정 이식 위치
다음 구조를 기준으로 구현한다.
```plain text
OptionProject/
├─ infrastructure/
│  └─ kis/
│     ├─ auth.py              # Reference KISAuthManager 기능 이식/재사용 경계
│     └─ holiday_provider.py  # KIS chk-holiday API Provider
└─ application/
   └─ composition/
      └─ option_master_factory.py
          create_production_trading_calendar(...)
          create_production_option_master(...)
```
의존 방향:
application composition
→ infrastructure.kis
→ contracts.TradingCalendar
→ core.oms.OptionContractMaster
Core는 Infrastructure를 import하지 않는다.
### 구현 판단
이번 조사 결과 기존 OptionProject에는 재사용 가능한 KISAuthManager가 아직 존재하지 않는다. 따라서 다음 구현 단계에서는 최신 Reference의 인증 기능을 OptionProject Infrastructure 경계로 선별 이식해야 한다.
단, orjson 등 Reference 구현의 부수 의존성을 그대로 복제하지 않고 OptionProject의 현재 pyproject.toml 및 dependency rules와 먼저 대조해야 한다.
### 원격 Git 검증
    - Reference branch: Exp_Detail_1
    - 확인 파일:
        - option_program/broker/kis_auth.py
        - option_program/runtime/program_runtime.py
        - shared/calendar/krx_calendar.py
    - 원격 Git 수정 없음
### 다음 단계
No.161에서는 OptionProject의 pyproject.toml, dependency rules 및 Infrastructure 계층의 기존 import 규칙을 확인한 뒤:
    1. KISAuthManager 최소 이식 범위 확정
    1. infrastructure/kis/auth.py 생성
    1. holiday_provider.py가 요구하는 인증 interface 확정
을 수행한다.
Calendar Provider 구현보다 인증 의존성의 단일 책임을 먼저 확정하여 중복 OAuth 구현을 방지한다.
n## No.164 실제 구현 반영n- infrastructure/kis/trading_calendar.py: ProductionTradingCalendar 구현n- application/composition/option_master_factory.py: Auth → Holiday Provider → Calendar → OptionMaster compositionn- Core는 기존 TradingCalendar Contract 주입 구조를 유지n- 테스트 페이지: test_production_trading_calendar.py, test_option_master_factory.pyn- 원격 Git Reference 수정 없음n
## No.165 정합성 점검 반영
    - infrastructure.kis.trading_calendar 및 application.composition.option_master_factory의 실제 Notion 경로를 확인했다.
    - ProductionTradingCalendar는 기존 TradingCalendar Protocol의 is_trading_day, prev_trading_day, trading_days_between를 모두 제공한다.
    - Factory는 create_default_option_master(calendar=calendar, auto_load_kis=...)로 Calendar를 명시 주입한다.
    - test_option_master_factory.py는 composition 경계와 Calendar 주입 여부를 mock 기반으로 검증하도록 작성되어 있다.
    - 현재 Notion은 파일 페이지 저장소이므로 실제 Python package directory/__init__.py 존재 여부와 pytest 실행 PASS는 물리 workspace materialization 전까지 확정하지 않는다.
## No.166 실행 검증 반영
    - Notion 코드 페이지에서 ProductionTradingCalendar와 test_production_trading_calendar.py의 동일 코드를 임시 Python workspace로 materialize했다.
    - 임시 workspace의 package marker는 검증용으로만 추가했으며 OptionProject 원본 구조 변경이 아니다.
    - python -m unittest discover -s tests -v 결과 3 tests PASS.
    - Factory는 실제 외부 KIS 네트워크 없이 import dependency를 stub/mock으로 대체한 isolated composition 검증에서 Auth → Provider → Calendar → create_default_option_master(calendar=...) 전달을 PASS했다.
    - 따라서 검증 가능한 순수/격리 경계는 실행 PASS로 승격하되, 실제 OptionProject 전체 physical package tree 및 실제 KIS HTTP 통합은 여전히 별도 검증 대상이다.

[Child Page] kis_auth_implementation.md
## 목적
Reference Exp_Detail_1/option_program/broker/kis_auth.py의 OAuth2 인증 기능을 OptionProject의 Infrastructure 경계로 선별 이식하기 위한 구현 기준이다.
## 확정 책임
    - KISAuthManager: OAuth2 access token 발급·캐시·만료 관리·인증 헤더 생성
    - KISAuthToken: token DTO 및 유효성 판정
    - KISAuthError: 인증 실패 의미 보존
    - Holiday Provider는 OAuth 구현을 직접 보유하지 않고 인증 Adapter를 통해 헤더만 공급받는다.
## 이식 위치
OptionProject/infrastructure/kis/auth.py
## Reference 보존 원칙
    - KIS endpoint와 token semantics는 Reference를 기준으로 유지한다.
    - 기존 기능을 임의 단순화하지 않는다.
    - orjson은 OptionProject dependency 기준이 확정되지 않았으므로 표준 json 사용 가능 여부를 구현 단계에서 검증한다.
    - Core는 infrastructure.kis를 import하지 않는다.
## 구현 전제
DEPENDENCY_RULES.md의 infrastructure → contracts 방향과 Core의 외부 API 비의존 원칙을 유지한다.
## 구현 대상 최소 API
    - from_env(...)
    - has_credentials()
    - issue_token()
    - get_access_token(...)
    - get_auth_headers(tr_id=..., ...)
## 후속 연결
infrastructure/kis/holiday_provider.py는 이 Adapter의 인증 헤더 공급 경계를 사용하며, Production Calendar Factory는 Application composition에서 Provider를 조립한다.
## No.162 실제 구현 반영
    - 실제 코드 페이지: auth.py
    - 최소 단위 테스트 페이지: test_kis_auth.py
    - 표준 라이브러리 json을 사용하여 orjson 신규 의존성을 추가하지 않았다.
    - urlopen 주입점을 두어 실제 KIS 네트워크 호출 없이 단위 테스트 대체가 가능하도록 했다.
    - cache load/save, KST 만료시각 해석, EGW00133 유효 캐시 재사용 의미를 Reference와 동일한 책임 범위로 유지한다.

[Child Page] kis
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

[Child Page] kis_info_type_option_type_mapping.md
## 목적
KIS 공식 Master의 info_type과 Standard Core의 CanonicalOptionType 사이의 의미 변환을 KIS 전용 adapter 경계로 고정한다.
## 확인된 양쪽 계약
### Canonical
원격 Exp_Detail_1의 shared/contracts/canonical.py에서 CanonicalOptionType은 정확히 다음 두 값이다.
    - CALL = "CALL"
    - PUT = "PUT"
### KIS Master
공식 Master의 info_type 의미:
    - 5 = 지수 콜옵션
    - 6 = 지수 풋옵션
    - D = 미니 콜옵션
    - E = 미니 풋옵션
    - L = 위클리 콜옵션
    - M = 위클리 풋옵션
## 명시적 매핑
```python
KIS_INFO_TYPE_TO_OPTION_TYPE = {
    "5": CanonicalOptionType.CALL,
    "D": CanonicalOptionType.CALL,
    "L": CanonicalOptionType.CALL,
    "6": CanonicalOptionType.PUT,
    "E": CanonicalOptionType.PUT,
    "M": CanonicalOptionType.PUT,
}
```
## 매핑 위치
매핑은 KIS Master adapter / parser layer에 둔다.
금지:
    - Canonical contract가 KIS info_type을 직접 해석
    - Broker가 info_type을 해석
    - Strategy가 KIS 코드를 보고 Call/Put을 추론
    - action, track_id, tag_id, side 등으로 option_type 생성
권장 흐름:
```plain text
KIS raw MST
  ↓
KIS Master Record
  ├─ shrn_iscd
  ├─ stnd_iscd
  ├─ info_type (원본 보존)
  ├─ acpr
  └─ expiry (기존 계산/조회 의미)
       ↓
KIS-specific explicit adapter
  ├─ info_type → CanonicalOptionType
  └─ acpr → validated strike
       ↓
verified OptionInstrumentIdentity
       ↓
Standard Signal / Position Logic / OMS
```
## Fail-closed 규칙
    1. 지원하지 않는 info_type은 Call/Put으로 임의 분류하지 않는다.
    1. 옵션 주문에 option_type이 필요하지만 명시적 매핑 결과가 없으면 Resolver/validation에서 차단한다.
    1. 원본 info_type은 가능한 한 identity record에 보존한다.
    1. shrn_iscd는 KIS short code이며 SHTN_PDNO 공급 후보이고, stnd_iscd와 혼동하지 않는다.
    1. instrument_id는 이 매핑만으로 생성하지 않는다.
    1. KOSPI200을 상품 ID 또는 KIS short code로 보완값 사용하지 않는다.
## Strike / Expiry 경계
    - acpr는 Master의 행사가 원본이며 검증 후 strike로 공급한다.
    - expiry는 Master에 독립 컬럼으로 존재한다고 가정하지 않고 기존 프로젝트의 월물/위클리 만기 계산 및 lookup 의미를 유지한다.
    - option_type은 info_type의 명시적 매핑으로만 생성한다.
## 현재 상태
이번 단계에서는 원격 Exp_Detail_1 코드를 수정하지 않는다. 다음 구현 단계에서 이 adapter를 실제 Master identity parser/registry에 연결하되, 기존 get_expiry() / register_contract() 호환 API와 분리하여 기능을 보존한다.

[Child Page] kis_shtn_pdno_identity_verification.md
No.137의 후속 작업으로 KIS 공식 주문 API의 SHTN_PDNO 의미와 원격 Exp_Detail_1의 standard_code를 동일한 authoritative 상품식별자로 연결할 수 있는지 검증한다.
## 검증 결과
### 1. KIS 공식 주문 API
KIS Developers 공식 Open Trading API의 국내선물옵션 주문 예제에서 shtn_pdno는 [필수] 단축상품번호이며, 설명은 선물 6자리·옵션 9자리 종목번호 예시를 명시한다.
    - 선물 예: 101W09
    - 옵션 예: 201S03370
따라서 SHTN_PDNO는 단순 표시용 symbol이 아니라 KIS 주문 API가 요구하는 실제 종목/상품의 단축번호다.
### 2. 원격 Exp_Detail_1의 KIS Master parser
shared/contracts/option_master.py의 parse_kis_fo_idx_mst()는 KIS 공식 fo_idx_code_mts.mst 원본에서 다음 필드를 읽는다.
    - symbol
    - standard_code
    - name
    - 상품 타입
현재 parser는 옵션에 대해 symbol과 standard_code를 모두 동일한 expiry lookup key로 저장한다.
즉 standard_code가 현재 Master 내부의 조회키로 사용되는 사실은 확인된다.
### 3. 동일성 판단
현재 확보된 authoritative 자료만으로는 KIS MST의 standard_code라는 필드명이 곧 주문 API의 SHTN_PDNO와 동일하다고 명시적으로 증명할 수 없다.
확인된 사실은 다음 두 가지다.
    1. SHTN_PDNO = KIS 주문 API가 요구하는 단축상품번호.
    1. standard_code = KIS MST 원본 레코드에서 제공되는 코드이며 현재 프로젝트 parser가 보존한다.
그러나 standard_code == SHTN_PDNO라는 직접적인 KIS 공식 필드 매핑 문서는 현재 확인되지 않았다.
따라서 Standard instrument_id로 승격하거나 주문상품코드로 확정하는 작업은 보류한다.
## 안전한 결론
```plain text
KIS MST standard_code
    ↓
[현재: authoritative 후보 코드]
    ↓  직접 동일성 증거가 추가되기 전까지 승격 금지
Standard Instrument Identity / KIS SHTN_PDNO
```
KOSPI200을 주문상품코드로 사용하지 않는다.
symbol + expiry + strike + option_type 조합으로 synthetic ID를 만들지 않는다.
standard_code를 단순히 instrument_id로 이름만 변경하지 않는다.
## 다음 연결 경계
```plain text
KIS official Contract/Product Master
→ verified product-code mapping
→ Instrument Identity
→ Signal / Position Logic
→ OptionIdentityResolver
→ OrderIntentFactory
→ Environment / Broker
```
Runtime의 CanonicalOrderCommand.symbol 기본값을 standard_code로 치환하는 변경은 아직 수행하지 않는다.

[Child Page] kis_option_master_raw_format_and_acpr_safety.md
KIS 공식 fo_idx_code_mts.mst의 실제 컬럼 정의와 현재 원격 shared/contracts/option_master.py의 파싱 방식을 다시 대조하여, KisOptionContractIdentity 구현에 필요한 raw field formatting 및 acpr 파싱 안전 규칙을 확정한다.
## 확인된 공식 구조
KIS 공식 C 구조체는 다음 순서의 9개 필드를 정의한다.
    1. info_type — 상품종류
    1. shrn_iscd — 단축코드
    1. stnd_iscd — 표준코드
    1. kor_name — 한글종목명
    1. atm_cls_code — ATM 구분
    1. acpr — 행사가
    1. mmsc_cls_code — 월물구분코드
    1. unas_shrn_iscd — 기초자산 단축코드
    1. unas_kor_name — 기초자산 명
공식 Python 정제 코드도 | 구분 텍스트를 읽어 위 9개 컬럼 순서로 DataFrame을 만든다. 따라서 현재 프로젝트의 parts[n] 접근은 이 순서를 기준으로 해석해야 한다.
## 현재 원격 parser와의 대조
현재 parse_kis_fo_idx_mst()는 parts[0]~parts[3]만 명시적으로 사용하고, expiry는 parts[4]가 아니라 종목명/심볼의 패턴과 기존 KRX 계산 함수로 산출한다.
따라서 Identity 확장 시 기존 expiry 계산을 건드리지 않는다.
## raw formatting에 대한 확정 범위
    - 공식 정제 코드는 sep='|', encoding='cp949'로 읽는다.
    - 프로젝트 parser도 line.split('|') 후 각 필드를 .strip()한다.
    - 따라서 Identity parser의 1차 정규화는 각 field에 대해 strip()을 적용한다.
    - 필드 수가 6개 미만이면 acpr를 안전하게 읽을 수 없으므로 Identity record 생성 대상에서 제외한다.
    - info_type, shrn_iscd, stnd_iscd는 공백 제거 후 원문 의미를 보존한다.
    - acpr의 고정 폭 바이트 표현이나 암묵적인 소수점 위치는 공식 C 구조체 정의만으로 확정하지 않는다.
## acpr Decimal 안전 규칙
acpr는 공식 Master의 행사가 필드이므로 Decimal의 직접 입력 원천으로 사용한다. 단, 다음 조건을 모두 만족할 때만 Identity의 strike로 승격한다.
    1. raw_acpr = parts[5].strip()가 비어 있지 않아야 한다.
    1. Decimal(raw_acpr) 변환이 성공해야 한다.
    1. 결과가 0보다 커야 한다.
    1. 소수점 위치를 임의로 이동하거나 /10, /100 등의 스케일을 추정하지 않는다.
    1. 숫자가 아닌 장식 문자나 단위 문자를 제거해서 복구하지 않는다.
    1. 위 조건을 만족하지 못하면 strike=None으로 두고 임의의 행사가를 만들지 않는다.
이 규칙은 현재 실제 raw sample에서 acpr가 정수형 문자열인지 소수형 문자열인지가 확인되지 않은 상태에서도 의미를 왜곡하지 않는 보수적 경계다.
## option_type
info_type 원문은 Identity에 보존하고, KIS 전용 adapter에서만 다음 명시적 매핑을 적용한다.
```plain text
5 / D / L -> CanonicalOptionType.CALL
6 / E / M -> CanonicalOptionType.PUT
```
지원하지 않는 값은 임의의 Call/Put으로 변환하지 않는다.
## expiry
expiry는 acpr 또는 Master의 다른 고정 필드에서 새로 추정하지 않는다. 기존 프로젝트의 월물/위클리 이름·심볼 패턴과 KRX calendar 계산 결과를 그대로 사용한다.
## 구현 경계
```plain text
raw MST line
  -> split('|') / strip()
  -> KIS Master Record
  -> validated KisOptionContractIdentity
       shrn_iscd
       stnd_iscd
       info_type
       option_type
       strike
       expiry
  -> legacy expiry compatibility map
```
기존 parse_kis_fo_idx_mst() -> Dict[str, str], get_expiry(), register_contract()의 외부 의미는 변경하지 않는다.
## 보류 사항
실제 최신 KIS MST 파일 원문 샘플 자체를 이 단계의 연결된 공식 GitHub 저장소에서 확보하지 못했으므로 acpr의 실제 문자열 예시나 암묵적 스케일은 확정하지 않는다. 따라서 코드에서 소수점 위치를 추측하는 로직은 금지한다.
## 원격 적용 상태
원격 Exp_Detail_1에는 변경하지 않는다. 이 문서는 다음 단계의 실제 코드 적용 전 계약 문서다.
[Child Page] futures_market_transport.py
```python
from __future__ import annotations

import asyncio
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
        # KIS official websocket endpoints: 21000 real, 31000 VTS.
        return "ws://ops.koreainvestment.com:31000" if self.is_vts else "ws://ops.koreainvestment.com:21000"


class KISWebSocketApprovalKeyProvider:
    def __init__(self, auth: KISAuthManager, *, approval_path: str = "/oauth2/Approval", timeout: float = 10.0) -> None:
        self._auth = auth
        self._approval_path = approval_path
        self._timeout = timeout

    def issue(self) -> str:
        if not self._auth.has_credentials():
            raise FuturesMarketTransportError("KIS credentials are required for websocket approval key")
        payload = {
            "grant_type": "client_credentials",
            "appkey": self._auth.app_key,
            "secretkey": self._auth.app_secret,
        }
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
    """Concrete KIS websocket transport; credentials and endpoint are injected."""

    def __init__(self, auth: KISAuthManager, config: KISFuturesMarketTransportConfig | None = None) -> None:
        self._auth = auth
        self._config = config or KISFuturesMarketTransportConfig(is_vts=auth.is_vts)
        self._approval = KISWebSocketApprovalKeyProvider(
            auth,
            approval_path=self._config.approval_path,
            timeout=self._config.timeout,
        )
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

    def _message(self, approval_key: str, tr_type: str, tr_id: str, symbol: str) -> str:
        return json.dumps(
            {
                "header": {
                    "approval_key": approval_key,
                    "custtype": "P",
                    "tr_type": tr_type,
                    "content-type": "utf-8",
                },
                "body": {"input": {"tr_id": tr_id, "tr_key": symbol}},
            }
        )

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
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    async def close(self) -> None:
        socket = self._socket
        self._socket = None
        self._connected = False
        if socket is not None:
            await socket.close()
```
## 책임 경계
        - FuturesMarketTransport는 Runtime/Consumer가 의존하는 최소 async transport contract다.
        - KISWebSocketApprovalKeyProvider는 기존 KISAuthManager의 app key/secret/base URL을 재사용하며 credential을 새로 저장하지 않는다.
        - KIS 공식 websocket approval endpoint /oauth2/Approval을 사용한다.
        - 실전 기본 endpoint는 ws://ops.koreainvestment.com:21000, VTS는 31000으로 분리한다.
        - tr_id와 KIS futures shrn_iscd는 호출자가 명시적으로 공급한다. KOSPI200/U200 코드를 하드코딩하지 않는다.
        - reconnect 정책은 이 최소 transport에 포함하지 않으며 상위 lifecycle owner가 결정한다.
[Child Page] [LEGACY_MISPLACED] futures_market_consumer.py
이 페이지는 생성 당시 잘못된 Notion 부모(infrastructure/kis_option_master_raw_format_and_acpr_safety.md)에 생성된 LEGACY MISPLACED 항목이다.
실제 구현본은 OptionProject / infrastructure / kis / futures_market_consumer.py에 위치한다.
이 페이지의 코드는 실행 대상에서 제외한다.