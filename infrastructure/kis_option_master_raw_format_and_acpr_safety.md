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