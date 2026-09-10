[Child Page] kis_live_broker.py
```python
from dataclasses import dataclass

from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from environments.live.contracts import LiveSafetyPolicy
from environments.live.futures_broker_command_adapter import KisFuturesBrokerCommandAdapter
from environments.live.idempotency import IdempotencyRegistry, OrderIdentity
from environments.live.broker.kis_order_payload import KisDomesticFuturesOrderPayloadAdapter
from environments.live.broker.kis_order_transport import KISDomesticFuturesOrderTransport


@dataclass
class LiveBrokerAdapter:
    transport: object
    gate: object
    policy: LiveSafetyPolicy
    idempotency: IdempotencyRegistry
    futures_command_adapter: KisFuturesBrokerCommandAdapter | None = None
    connected: bool = False

    def connect(self) -> bool:
        self.connected = bool(self.transport.authenticate())
        return self.connected

    def submit(self, command: BrokerOrderCommand, identity: OrderIdentity, account_age_seconds: float) -> BrokerOrderResponse:
        if not self.connected:
            raise RuntimeError("live broker is disconnected")
        if not self.idempotency.reserve(identity):
            raise RuntimeError("duplicate client order identity")

        gate = self.gate.evaluate(command.quantity, account_age_seconds)
        if not gate.allowed:
            raise RuntimeError(gate.reason)

        broker_command = command
        if command.asset_type == "FUTURES":
            if self.futures_command_adapter is None:
                raise RuntimeError("FUTURES_COMMAND_ADAPTER_REQUIRED")
            broker_command = self.futures_command_adapter.to_broker_command(command)

        return self.transport.submit(broker_command)
```
## 연결 계약
    - LiveBrokerAdapter가 실제 KISDomesticFuturesOrderTransport를 주입받으면 기존 실행 경계가 그대로 authenticate() → submit()으로 연결된다.
    - submit() 순서는 connected check → Idempotency → Live Safety Gate → authoritative FUTURES broker command mapping → physical transport를 유지한다.
    - FUTURES의 broker_symbol은 KisFuturesBrokerCommandAdapter가 authoritative source에서 공급하고, payload adapter가 KIS body로 직렬화한다.
    - instrument_id는 생성·변경하지 않는다.
    - KISDomesticFuturesOrderTransport는 BrokerOrderResponse ACK만 반환한다. ACK를 ExecutionReport로 승격하지 않는다.
    - WAL/OMS FSM은 계속 OrderRouter 책임이다.
    - 기본 composition factory나 application root에서 KISAuthManager → KisDomesticFuturesOrderPayloadAdapter → KISDomesticFuturesOrderTransport → LiveBrokerAdapter를 구성할 수 있다. 실제 credential 값은 코드에 저장하지 않는다.
    - MARKET 주문은 기존과 동일하게 BLOCKED 유지한다.

[Child Page] kis_order_payload.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

from contracts.types import BrokerOrderCommand


class KisOrderPayloadError(ValueError):
    """Raised when a KIS domestic futures/options order payload is unsafe."""


@dataclass(frozen=True)
class KisOrderAccountContext:
    cano: str
    acnt_prdt_cd: str


@dataclass(frozen=True)
class KisDomesticFuturesOrderPayloadAdapter:
    """Serialize a validated BrokerOrderCommand into the KIS order body.

    This adapter performs only environment-specific serialization. It does not
    invent an instrument code, infer an order type, or perform network I/O.
    """

    account: KisOrderAccountContext
    is_vts: bool = False

    def to_payload(self, command: BrokerOrderCommand) -> dict[str, str]:
        if command.asset_type != "FUTURES":
            raise KisOrderPayloadError("FUTURES_ASSET_TYPE_REQUIRED")
        if not command.broker_symbol:
            raise KisOrderPayloadError("SHTN_PDNO_REQUIRED")
        if not re.fullmatch(r"[A-Za-z0-9]{8}", command.broker_symbol):
            raise KisOrderPayloadError("SHTN_PDNO_MUST_BE_8_ALPHANUMERIC")
        if command.broker_symbol[0] != "1":
            raise KisOrderPayloadError("FUTURES_SHTN_PDNO_PRODUCT_PREFIX_REQUIRED")
        if command.quantity <= 0:
            raise KisOrderPayloadError("ORD_QTY_REQUIRED")
        if command.requested_price is None or command.requested_price <= 0:
            raise KisOrderPayloadError("UNIT_PRICE_REQUIRED")
        if command.order_type != "LIMIT":
            # Current Standard contract does not define a safe market-order mapping.
            raise KisOrderPayloadError("UNSUPPORTED_ORDER_TYPE")

        side = str(command.side).upper()
        if side not in {"BUY", "SELL"}:
            raise KisOrderPayloadError("SIDE_REQUIRED")

        return {
            "CANO": self.account.cano,
            "ACNT_PRDT_CD": self.account.acnt_prdt_cd,
            "SHTN_PDNO": command.broker_symbol,
            "ORD_PRCS_DVSN_CD": "02",
            "SLL_BUY_DVSN_CD": "02" if side == "BUY" else "01",
            "ORD_DVSN_CD": "00",
            "UNIT_PRICE": f"{Decimal(command.requested_price):.2f}",
            "ORD_QTY": str(command.quantity),
            "NMPR_TYPE_CD": "01",
            "KRX_NMPR_CNDT_CD": "0",
        }

    def tr_id(self) -> str:
        return "VTTO1101U" if self.is_vts else "TTTO1101U"
```
## 계약 근거
    - SHTN_PDNO: KIS 국내선물옵션 주문의 실제 단축상품번호를 무변형 전달한다.
    - SLL_BUY_DVSN_CD: BUY=02, SELL=01.
    - ORD_PRCS_DVSN_CD: 신규주문=02.
    - ORD_DVSN_CD: 현재 Standard가 안전하게 정의한 지정가 주문=00.
    - UNIT_PRICE: BrokerOrderCommand.requested_price를 2자리 문자열로 직렬화한다.
    - ORD_QTY: quantity를 문자열로 전달한다.
    - NMPR_TYPE_CD=01, KRX_NMPR_CNDT_CD=0은 기존 프로젝트의 신규 지정가 주문 계약과 일치하는 고정값으로 보존한다.
    - 주간 신규주문 TR은 REAL=TTTO1101U, VTS=VTTO1101U로 분기한다. 매수/매도에 따라 TR ID를 임의 분기하지 않는다.
## 안전 규칙
    - broker_symbol은 앞 단계 KisFuturesBrokerCommandAdapter가 authoritative source에서 공급해야 한다.
    - payload adapter는 SHTN_PDNO를 조합하거나 기본값으로 생성하지 않는다.
    - 현재 Domain에서 MARKET 주문의 KIS 필드 매핑이 확정되지 않았으므로 임의 매핑하지 않고 UNSUPPORTED_ORDER_TYPE으로 차단한다.
    - 이 모듈은 network I/O와 ACK 처리 책임을 갖지 않는다.

[Child Page] kis_order_transport.py
```python
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from infrastructure.kis.auth import KISAuthError, KISAuthManager
from environments.live.broker.kis_order_payload import KisDomesticFuturesOrderPayloadAdapter


KIS_FUTURES_ORDER_PATH = "/uapi/domestic-futureoption/v1/trading/order"


class KisOrderTransportError(RuntimeError):
    """Raised for transport-level failures that cannot be represented as an ACK."""


@dataclass
class KISDomesticFuturesOrderTransport:
    """HTTP transport for the KIS domestic futures/options new-order boundary.

    The transport owns HTTP/authentication and delegates body serialization to the
    existing KIS payload adapter. It never converts an ACK into an ExecutionReport.
    """

    auth: KISAuthManager
    payload_adapter: KisDomesticFuturesOrderPayloadAdapter
    timeout: float = 10.0
    urlopen: Callable[..., Any] = urllib.request.urlopen
    base_url: str | None = None

    def authenticate(self) -> bool:
        try:
            return bool(self.auth.get_access_token())
        except KISAuthError:
            return False

    def submit(self, command: BrokerOrderCommand) -> BrokerOrderResponse:
        payload = self.payload_adapter.to_payload(command)
        tr_id = self.payload_adapter.tr_id()
        base_url = (self.base_url or self.auth.base_url).rstrip("/")
        url = f"{base_url}{KIS_FUTURES_ORDER_PATH}"
        headers = self.auth.get_auth_headers(tr_id=tr_id)
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with self.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
            data = json.loads(raw)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return BrokerOrderResponse(
                client_order_id=command.client_order_id,
                accepted=False,
                broker_code=str(exc.code),
                message=body,
            )
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise KisOrderTransportError(f"KIS order transport failed: {exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KisOrderTransportError(f"KIS order response is not valid JSON: {exc}") from exc

        return self.normalize_response(command.client_order_id, data)

    @staticmethod
    def normalize_response(
        client_order_id: str,
        data: Mapping[str, Any],
    ) -> BrokerOrderResponse:
        rt_cd = str(data.get("rt_cd", ""))
        output = data.get("output")
        output_map = output if isinstance(output, Mapping) else {}
        broker_order_id = output_map.get("ODNO")
        message = data.get("msg1") or data.get("msg_cd")
        accepted = rt_cd == "0" and bool(str(broker_order_id or "").strip())
        return BrokerOrderResponse(
            client_order_id=client_order_id,
            accepted=accepted,
            broker_order_id=str(broker_order_id) if broker_order_id else None,
            broker_code=str(data.get("msg_cd")) if data.get("msg_cd") else rt_cd or None,
            message=str(message) if message else None,
            raw_response=dict(data),
        )
```
## 계약
    - endpoint: POST /uapi/domestic-futureoption/v1/trading/order.
    - tr_id는 기존 KisDomesticFuturesOrderPayloadAdapter.tr_id()가 REAL=TTTO1101U, VTS=VTTO1101U로 결정한다.
    - KISAuthManager.get_auth_headers()를 사용하여 OAuth authorization/appkey/appsecret/tr_id를 주입한다.
    - HTTP body는 기존 KisDomesticFuturesOrderPayloadAdapter가 직렬화하며 transport가 필드를 재작성하지 않는다.
    - KIS rt_cd="0" 및 output.ODNO 존재를 성공 ACK로 정규화한다. 성공 ACK는 체결을 의미하지 않는다.
    - HTTP 오류는 거절 응답으로 정규화하고, timeout/network/비정상 JSON은 transport error로 분리한다.
    - BrokerOrderResponse는 ACK 계층의 결과이며 ExecutionReport를 생성하지 않는다.
공식 KIS Open Trading API의 국내선물옵션 신규주문 예제는 동일 endpoint와 REAL 주간 TTTO1101U / 모의 VTTO1101U를 사용하며 POST body key를 대문자로 요구한다. citeturn0search1

[Child Page] futures_broker_command_[adapter.py]
```python
from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from contracts.types import BrokerOrderCommand


class FuturesBrokerSymbolSource(Protocol):
    def current_symbol(self) -> str: ...


class KisFuturesBrokerCommandAdapter:
    """Attach the authoritative KIS FUTURES broker symbol to a broker command."""

    def __init__(self, symbol_source: FuturesBrokerSymbolSource) -> None:
        self._symbol_source = symbol_source

    def to_broker_command(self, command: BrokerOrderCommand) -> BrokerOrderCommand:
        if command.asset_type != "FUTURES":
            raise ValueError("FUTURES_ASSET_TYPE_REQUIRED")
        if not command.instrument_id.strip():
            raise ValueError("FUTURES_INSTRUMENT_ID_REQUIRED")

        symbol = self._symbol_source.current_symbol().strip()
        if not symbol:
            raise ValueError("FUTURES_BROKER_SYMBOL_REQUIRED")

        return replace(command, broker_symbol=symbol)
```
## 책임 경계
    - Standard instrument_id는 변경하지 않는다.
    - KIS shrn_iscd 기반의 authoritative execution symbol만 broker_symbol에 주입한다.
    - symbol을 조합하거나 기본값으로 생성하지 않는다.
    - 주문 payload 직렬화와 network I/O는 담당하지 않는다.
    - FUTURES 이외 asset type은 이 Adapter의 책임이 아니므로 fail-closed 한다.
## 연결 경로
KIS FUTURES Master → KisFuturesExecutionSymbolSource.current_symbol() → KisFuturesBrokerCommandAdapter.to_broker_command() → LiveBrokerAdapter → KisDomesticFuturesOrderPayloadAdapter → KISDomesticFuturesOrderTransport
instrument_id와 broker_symbol은 서로 다른 identity seam으로 유지한다.