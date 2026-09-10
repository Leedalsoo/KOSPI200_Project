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
