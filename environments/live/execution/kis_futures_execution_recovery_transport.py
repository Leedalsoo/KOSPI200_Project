from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from infrastructure.kis.auth import KISAuthManager
from environments.live.execution.kis_futures_execution_recovery_adapter import (
    KISExecutionRecoveryQuery,
    KISExecutionRecoveryInvalid,
    KIS_FUTURES_EXECUTION_INQUIRY_PATH,
)


class KISExecutionRecoveryTransportError(RuntimeError):
    """Raised when the KIS execution recovery HTTP request cannot complete safely."""


@dataclass
class KISFuturesExecutionRecoveryTransport:
    """Authenticated GET transport for KIS inquire-ccnl recovery."""

    auth: KISAuthManager
    timeout: float = 10.0
    urlopen: Callable[..., Any] = urllib.request.urlopen
    base_url: str | None = None
    max_pages: int = 100

    def authenticate(self) -> bool:
        return bool(self.auth.get_access_token())

    def inquire(self, query: KISExecutionRecoveryQuery) -> Mapping[str, object]:
        if self.max_pages <= 0:
            raise KISExecutionRecoveryInvalid("MAX_PAGES_INVALID")

        all_rows: list[object] = []
        current_query = query
        continuation = ""
        last_data: Mapping[str, object] | None = None

        for _page in range(self.max_pages):
            data, continuation = self._request(current_query, continuation)
            last_data = data
            rows = data.get("output1")
            if rows is not None:
                if not isinstance(rows, list):
                    raise KISExecutionRecoveryTransportError("KIS output1 must be an array")
                all_rows.extend(rows)

            if continuation != "M":
                break

            current_query = replace(
                current_query,
                ctx_area_fk200=str(data.get("ctx_area_fk200", "") or ""),
                ctx_area_nk200=str(data.get("ctx_area_nk200", "") or ""),
            )
        else:
            raise KISExecutionRecoveryTransportError("KIS execution recovery pagination limit exceeded")

        if last_data is None:
            raise KISExecutionRecoveryTransportError("KIS execution recovery returned no response")

        result = dict(last_data)
        result["output1"] = all_rows
        return result

    def _request(
        self,
        query: KISExecutionRecoveryQuery,
        tr_cont: str,
    ) -> tuple[Mapping[str, object], str]:
        base_url = (self.base_url or self.auth.base_url).rstrip("/")
        params = urllib.parse.urlencode(query.params())
        url = f"{base_url}{KIS_FUTURES_EXECUTION_INQUIRY_PATH}?{params}"
        headers = self.auth.get_auth_headers(tr_id=query.tr_id)
        if tr_cont:
            headers["tr_cont"] = tr_cont
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                response_tr_cont = str(response.headers.get("tr_cont", "")).strip().upper()
            data = json.loads(raw)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise KISExecutionRecoveryTransportError(
                f"KIS execution recovery HTTP {exc.code}: {body}"
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise KISExecutionRecoveryTransportError(
                f"KIS execution recovery transport failed: {exc}"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KISExecutionRecoveryTransportError(
                f"KIS execution recovery response is not valid JSON: {exc}"
            ) from exc

        if not isinstance(data, Mapping):
            raise KISExecutionRecoveryTransportError("KIS execution recovery response must be object")
        if str(data.get("rt_cd", "")).strip() != "0":
            raise KISExecutionRecoveryTransportError(
                f"KIS execution recovery rejected: {data.get('msg_cd')} {data.get('msg1')}"
            )
        return data, response_tr_cont
