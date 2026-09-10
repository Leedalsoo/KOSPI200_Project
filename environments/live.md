폴더 페이지

[Child Page] bundle.py
```python
from dataclasses import dataclass
from environments.live.contracts import LiveSafetyPolicy

@dataclass
class LiveEnvironmentBundle:
    market: object
    broker: object
    account: object
    position: object
    reconciler: object
    recovery: object
    policy: LiveSafetyPolicy

    def initialize(self) -> None:
        if self.policy.approval_state.value != "DISARMED":
            raise RuntimeError("Live bundle must start disarmed")

    def connect(self) -> bool:
        return bool(self.broker.connect())

    def start(self) -> None:
        if not getattr(self.broker, "connected", False):
            raise RuntimeError("Live bundle cannot start before broker connection")

    def stop(self) -> None:
        self.policy = LiveSafetyPolicy()

    def shutdown(self) -> None:
        if getattr(self.broker, "connected", False):
            self.broker.disconnect()
```

[Child Page] safety_gate.py
```python
from dataclasses import dataclass
from environments.live.contracts import LiveApproval, LiveSafetyPolicy

@dataclass(frozen=True)
class LiveGateResult:
    allowed: bool
    reason: str

class LiveSafetyGate:
    def __init__(self, policy: LiveSafetyPolicy):
        self.policy = policy
        self._approval: LiveApproval | None = None

    def approve(self, approval: LiveApproval) -> None:
        if not approval.approved_by.strip():
            raise ValueError("approval identity is required")
        self._approval = approval

    def revoke(self) -> None:
        self._approval = None

    def evaluate(self, quantity: int, account_age_seconds: float) -> LiveGateResult:
        if self._approval is None:
            return LiveGateResult(False, "live approval is missing")
        if not self.policy.can_submit:
            return LiveGateResult(False, "live safety policy is disarmed")
        if quantity <= 0 or quantity > self.policy.max_order_quantity:
            return LiveGateResult(False, "order quantity exceeds live limit")
        if account_age_seconds > self.policy.max_account_staleness_seconds:
            return LiveGateResult(False, "account/position data is stale")
        return LiveGateResult(True, "approved")
```

[Child Page] contracts.py
```python
from dataclasses import dataclass
from enum import Enum

class LiveApprovalState(str, Enum):
    DISARMED = "DISARMED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"

@dataclass(frozen=True)
class LiveSafetyPolicy:
    approval_state: LiveApprovalState = LiveApprovalState.DISARMED
    kill_switch: bool = True
    max_order_quantity: int = 0
    max_daily_loss: float = 0.0
    max_position_quantity: int = 0
    max_account_staleness_seconds: float = 5.0

    @property
    def can_submit(self) -> bool:
        return (
            not self.kill_switch
            and self.max_order_quantity > 0
            and self.max_daily_loss > 0
            and self.max_position_quantity > 0
        )

@dataclass(frozen=True)
class LiveCredentialRef:
    app_key_env: str = "KIS_REAL_APP_KEY"
    app_secret_env: str = "KIS_REAL_APP_SECRET"
    account_env: str = "KIS_REAL_ACCOUNT_NO"
    base_url_env: str = "KIS_REAL_BASE_URL"

@dataclass(frozen=True)
class LiveApproval:
    approved_by: str
    approved_at: str
    reason: str
```

[Child Page] credential.py
```python
import os
from dataclasses import dataclass
from environments.live.contracts import LiveCredentialRef

@dataclass(frozen=True)
class LiveCredentials:
    app_key: str
    app_secret: str
    account_no: str
    base_url: str

    @classmethod
    def from_environment(cls, ref: LiveCredentialRef) -> "LiveCredentials":
        values = {
            "app_key": os.getenv(ref.app_key_env, "").strip(),
            "app_secret": os.getenv(ref.app_secret_env, "").strip(),
            "account_no": os.getenv(ref.account_env, "").strip(),
            "base_url": os.getenv(ref.base_url_env, "https://openapi.koreainvestment.com:9443").strip(),
        }
        if not values["app_key"] or not values["app_secret"] or not values["account_no"]:
            raise RuntimeError("Live credentials are incomplete")
        return cls(**values)
```

[Child Page] reconciliation.py
```python
from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True)
class ReconciliationResult:
    consistent: bool
    reasons: tuple[str, ...]

class LiveReconciler:
    def compare_positions(self, broker: Mapping[str, int], internal: Mapping[str, int]) -> ReconciliationResult:
        reasons: list[str] = []
        for instrument in sorted(set(broker) | set(internal)):
            if broker.get(instrument, 0) != internal.get(instrument, 0):
                reasons.append(f"position mismatch: {instrument}")
        return ReconciliationResult(not reasons, tuple(reasons))
```

[Child Page] recovery.py
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    reason: str

class LiveRecovery:
    def decide(self, reconciliation_consistent: bool, broker_connected: bool) -> RecoveryDecision:
        if not broker_connected:
            return RecoveryDecision("SAFE_STOP", "broker disconnected")
        if not reconciliation_consistent:
            return RecoveryDecision("SAFE_STOP", "broker/internal state mismatch")
        return RecoveryDecision("RESUME_ALLOWED", "state reconciled")
```

[Child Page] idempotency.py
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class OrderIdentity:
    client_order_id: str
    strategy_id: str
    intent_fingerprint: str


class IdempotencyRegistry:
    def __init__(self) -> None:
        self._identities: dict[str, str] = {}

    def reserve(self, identity: OrderIdentity) -> bool:
        fingerprint = f"{identity.strategy_id}:{identity.intent_fingerprint}"
        previous = self._identities.get(identity.client_order_id)
        if previous is not None:
            # Any previously reserved client_order_id is already owned by a submitted intent.
            # A second physical submission must be rejected even when its fingerprint matches.
            return False
        self._identities[identity.client_order_id] = fingerprint
        return True
```
## 책임 경계
    - client_order_id가 한 번 예약되면 동일 fingerprint를 포함한 재제출도 physical transport로 진행하지 않는다.
    - 서로 다른 intent가 같은 client_order_id를 재사용하는 경우도 동일하게 차단한다.
    - 이 registry는 Live 주문 제출 idempotency만 담당하며 Execution Event deduplication과 혼동하지 않는다.

[Child Page] broker
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

[Child Page] market
KIS Live MarketDataProvider 경계. KIS FUTURES WebSocket consumer의 typed observation을 Standard MarketState로 투영하는 Environment 경계이며, instrument_id와 observed_at은 외부 authoritative provider를 명시적으로 주입한다. synthetic identity/time fallback은 금지한다.
[Child Page] kis_futures_market_data.py
```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from contracts.types import CanonicalMarketTick, DataQuality, MarketState, ProviderHealth
from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation


class KISFuturesMarketProjectionError(ValueError):
    """Raised when KIS FUTURES data cannot be projected safely."""


InstrumentIdResolver = Callable[[str], str]
ObservedAtResolver = Callable[[KisIndexFuturesMarketObservation], datetime]
MarketStateSubscriber = Callable[[MarketState], None]


@dataclass
class KISFuturesMarketDataProvider:
    """Environment boundary from typed KIS FUTURES observations to MarketState.

    Standard instrument identity and observation timestamp are authoritative
    inputs. This provider never derives either value from broker short codes
    or local wall-clock fallbacks.
    """

    instrument_id_resolver: InstrumentIdResolver | None = None
    observed_at_resolver: ObservedAtResolver | None = None
    _ticks: dict[str, CanonicalMarketTick] = field(default_factory=dict)
    _quality: dict[str, DataQuality] = field(default_factory=dict)
    _subscribers: list[MarketStateSubscriber] = field(default_factory=list)
    _as_of: datetime | None = None

    def publish(self, observation: KisIndexFuturesMarketObservation) -> CanonicalMarketTick:
        if self.instrument_id_resolver is None:
            raise KISFuturesMarketProjectionError("FUTURES_INSTRUMENT_ID_RESOLVER_REQUIRED")
        if self.observed_at_resolver is None:
            raise KISFuturesMarketProjectionError("FUTURES_OBSERVED_AT_RESOLVER_REQUIRED")

        instrument_id = self.instrument_id_resolver(observation.shrn_iscd.strip())
        if not instrument_id:
            raise KISFuturesMarketProjectionError("FUTURES_INSTRUMENT_ID_REQUIRED")
        observed_at = self.observed_at_resolver(observation)
        if not isinstance(observed_at, datetime):
            raise KISFuturesMarketProjectionError("FUTURES_OBSERVED_AT_REQUIRED")
        if observation.price is None:
            raise KISFuturesMarketProjectionError("FUTURES_LAST_PRICE_REQUIRED")

        tick = CanonicalMarketTick(
            instrument_id=instrument_id,
            observed_at=observed_at,
            price=observation.price,
            volume=observation.volume,
            source_sequence=None,
        )
        quality = DataQuality(
            is_fresh=True,
            is_complete=observation.volume is not None,
            source_available=True,
            reason=None,
        )
        self._ticks[instrument_id] = tick
        self._quality[instrument_id] = quality
        self._as_of = observed_at
        state = self.snapshot()
        for subscriber in tuple(self._subscribers):
            subscriber(state)
        return tick

    def snapshot(self) -> MarketState:
        if self._as_of is None:
            raise KISFuturesMarketProjectionError("FUTURES_MARKET_STATE_UNAVAILABLE")
        return MarketState(
            as_of=self._as_of,
            ticks=dict(self._ticks),
            quality=dict(self._quality),
        )

    def subscribe(self, callback: MarketStateSubscriber) -> None:
        self._subscribers.append(callback)

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            available=self._as_of is not None,
            as_of=self._as_of,
            reason=None if self._as_of is not None else "FUTURES_MARKET_STATE_UNAVAILABLE",
        )
```
## 책임 경계
        - KISIndexFuturesMarketConsumer의 typed observation을 Standard MarketState로 변환하는 실제 Environment 경계다.
        - shrn_iscd는 Market subscription identity로만 입력되며 Standard instrument_id를 직접 생성하지 않는다.
        - instrument_id는 authoritative resolver를 통해서만 공급된다.
        - KIS observed_hour를 임의 날짜나 로컬 현재시각과 조합하지 않는다. observed_at은 명시적 resolver가 공급한다.
        - price가 없는 quote-only observation은 Standard tick으로 승격하지 않고 fail-closed한다.
        - source_sequence를 synthetic sequence로 생성하지 않는다.
        - 변환 결과는 MarketDataProvider contract의 MarketState/ProviderHealth로 노출된다.

[Child Page] futures_broker_command_adapter.py
```python
from __future__ import annotations

from dataclasses import dataclass, replace

from contracts.futures_execution_symbol_source import KisFuturesExecutionSymbolSource
from contracts.types import BrokerOrderCommand


class FuturesBrokerCommandMappingError(ValueError):
    """Raised when a FUTURES broker command cannot be mapped safely."""


@dataclass(frozen=True)
class KisFuturesBrokerCommandAdapter:
    """Attach the authoritative KIS FUTURES execution symbol to a broker command.

    The adapter does not create instrument identity, infer contract codes, or
    submit an order. It only projects the selected Contract Master short code
    into the environment-specific broker_symbol field.
    """

    symbol_source: KisFuturesExecutionSymbolSource

    def to_broker_command(self, command: BrokerOrderCommand) -> BrokerOrderCommand:
        if command.asset_type != "FUTURES":
            raise FuturesBrokerCommandMappingError("FUTURES_ASSET_TYPE_REQUIRED")
        if not command.client_order_id:
            raise FuturesBrokerCommandMappingError("CLIENT_ORDER_ID_REQUIRED")
        if not command.instrument_id:
            raise FuturesBrokerCommandMappingError("INSTRUMENT_ID_REQUIRED")
        if command.quantity <= 0:
            raise FuturesBrokerCommandMappingError("QUANTITY_REQUIRED")
        if not command.order_type:
            raise FuturesBrokerCommandMappingError("ORDER_TYPE_REQUIRED")

        broker_symbol = self.symbol_source.current_symbol()
        if not broker_symbol:
            raise FuturesBrokerCommandMappingError("FUTURES_BROKER_SYMBOL_REQUIRED")

        return replace(command, broker_symbol=broker_symbol)
```
## 책임 경계
    - 입력은 이미 Risk/OMS를 통과한 BrokerOrderCommand다.
    - KisFuturesExecutionSymbolSource가 Contract Master에서 선택한 shrn_iscd를 authoritative broker symbol로 공급한다.
    - instrument_id는 생성·변경하지 않는다.
    - broker_symbol을 만기월/기초자산/코드 규칙으로 조합하지 않는다.
    - 주문 전송은 수행하지 않는다. 실제 Broker transport가 이 결과를 소비한다.
    - symbol source 실패 시 broker 호출 이전에 fail-closed 한다.
## 기존 기능 보존 판단
Exp_Detail_1의 RealBrokerAdapter._map_instrument_code()는 command.symbol을 사용하면서도 잘못된 경우 101V3000 등의 synthetic default가 다른 경로에 존재한다. Standard 계약은 broker symbol을 Environment Adapter가 결정하고 mapping 실패 시 Broker 호출을 하지 않도록 요구한다. 따라서 이 adapter는 기존의 'KIS 단축상품코드를 주문 API에 전달한다'는 기능 의미는 유지하되, synthetic fallback은 제거한다.
## 실행 경계
RiskGate → OrderRouter → BrokerOrderCommand → KisFuturesBrokerCommandAdapter → KIS transport
현재 StandardOptionRuntime.source_sequence 문제와는 독립된 실행 경계이며, KIS FUTURES market observation의 sequence를 합성하지 않는다.

[Child Page] execution
폴더 페이지
실제 KIS 국내선물옵션 체결통보(H0IFCNI0) 기반 Live Execution adapter를 둔다. ACK/주문전송과 분리하고, canonical ExecutionReport만 반환한다.
[Child Page] kis_futures_execution_adapter.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Mapping

from contracts.types import DataQuality, ExecutionReport


KIS_FUTURES_EXECUTION_NOTICE_TR_ID = "H0IFCNI0"


class KISFuturesExecutionAdapterInvalid(ValueError):
    """Raised when a KIS domestic futures/options execution notice is unsafe."""


# H0IFCNI0 fields published by KIS:
# cust_id, acnt_no, oder_no, ooder_no, seln_byov_cls, rctf_cls,
# oder_kind2, stck_shrn_iscd, cntg_qty, cntg_unpr, stck_cntg_hour,
# rfus_yn, cntg_yn, acpt_yn, brnc_no, oder_qty, acnt_name,
# cntg_isnm, oder_cond, ord_grp, ord_grpseq, order_prc
_FIELDS = (
    "cust_id", "acnt_no", "oder_no", "ooder_no", "seln_byov_cls", "rctf_cls",
    "oder_kind2", "stck_shrn_iscd", "cntg_qty", "cntg_unpr", "stck_cntg_hour",
    "rfus_yn", "cntg_yn", "acpt_yn", "brnc_no", "oder_qty", "acnt_name",
    "cntg_isnm", "oder_cond", "ord_grp", "ord_grpseq", "order_prc",
)


@dataclass(frozen=True)
class KISFuturesExecutionContext:
    """OMS-side correlation state required to build a canonical execution report."""

    client_order_id: str
    order_quantity: int
    prior_filled_quantity: int = 0
    group_id: str | None = None
    leg_id: str | None = None


@dataclass(frozen=True)
class KISFuturesExecutionNotice:
    """Typed H0IFCNI0 notice; values retain KIS wire semantics."""

    values: Mapping[str, str]
    raw_frame: str

    @property
    def broker_order_id(self) -> str:
        value = self.values["oder_no"].strip()
        if not value:
            raise KISFuturesExecutionAdapterInvalid("KIS execution notice has no order number")
        return value

    @property
    def filled_quantity(self) -> int:
        try:
            quantity = int(self.values["cntg_qty"].strip())
        except (TypeError, ValueError) as exc:
            raise KISFuturesExecutionAdapterInvalid("invalid KIS cntg_qty") from exc
        if quantity <= 0:
            raise KISFuturesExecutionAdapterInvalid("KIS execution quantity must be positive")
        return quantity

    @property
    def execution_price(self) -> Decimal:
        try:
            price = Decimal(self.values["cntg_unpr"].strip())
        except (InvalidOperation, ValueError) as exc:
            raise KISFuturesExecutionAdapterInvalid("invalid KIS cntg_unpr") from exc
        if price <= 0:
            raise KISFuturesExecutionAdapterInvalid("KIS execution price must be positive")
        return price

    @property
    def execution_hour(self) -> str:
        return self.values["stck_cntg_hour"].strip()


class KISFuturesExecutionNoticeAdapter:
    """Convert authoritative KIS H0IFCNI0 fill notices into ExecutionReport.

    The adapter does not infer a calendar date, synthetic client order id, or
    remaining quantity from broker-only state. The caller supplies OMS correlation
    context and the previously accumulated filled quantity.
    """

    TR_ID = KIS_FUTURES_EXECUTION_NOTICE_TR_ID

    def parse(self, frame: str) -> KISFuturesExecutionNotice:
        parts = frame.split("|")
        if len(parts) < 4 or parts[0] not in {"0", "1"}:
            raise KISFuturesExecutionAdapterInvalid("invalid KIS realtime frame envelope")
        if parts[1] != self.TR_ID:
            raise KISFuturesExecutionAdapterInvalid("unexpected KIS execution notice TR ID")
        try:
            field_count = int(parts[2])
        except ValueError as exc:
            raise KISFuturesExecutionAdapterInvalid("invalid KIS field count") from exc
        values = parts[3].split("^")
        if field_count != len(values) or len(values) != len(_FIELDS):
            raise KISFuturesExecutionAdapterInvalid("KIS execution notice field count mismatch")
        return KISFuturesExecutionNotice(
            values=dict(zip(_FIELDS, values, strict=True)),
            raw_frame=frame,
        )

    def to_execution_report(
        self,
        notice: KISFuturesExecutionNotice,
        context: KISFuturesExecutionContext,
    ) -> ExecutionReport:
        if not context.client_order_id.strip():
            raise KISFuturesExecutionAdapterInvalid("client_order_id is required")
        if context.order_quantity <= 0:
            raise KISFuturesExecutionAdapterInvalid("order_quantity must be positive")
        if context.prior_filled_quantity < 0:
            raise KISFuturesExecutionAdapterInvalid("prior_filled_quantity must be non-negative")
        if notice.values["cntg_yn"].strip().upper() != "Y":
            raise KISFuturesExecutionAdapterInvalid("notice is not an execution event")

        fill_qty = notice.filled_quantity
        cumulative = context.prior_filled_quantity + fill_qty
        if cumulative > context.order_quantity:
            raise KISFuturesExecutionAdapterInvalid("execution quantity exceeds order quantity")
        status = "FILLED" if cumulative == context.order_quantity else "PARTIALLY_FILLED"

        execution_id = "KIS-H0IFCNI0-" + sha256(notice.raw_frame.encode("utf-8")).hexdigest()
        return ExecutionReport(
            client_order_id=context.client_order_id,
            broker_order_id=notice.broker_order_id,
            execution_id=execution_id,
            status=status,
            filled_quantity=fill_qty,
            remaining_quantity=context.order_quantity - cumulative,
            execution_price=notice.execution_price,
            execution_timestamp=None,
            source_freshness=DataQuality(
                is_fresh=True,
                is_complete=False,
                source_available=True,
                reason="KIS H0IFCNI0 supplies execution time without calendar date",
            ),
            group_id=context.group_id,
            leg_id=context.leg_id,
        )
```
## KIS authoritative source
        - H0IFCNI0 = 국내선물옵션 실시간체결통보.
        - KIS 공식 예제의 필드는 oder_no, cntg_qty, cntg_unpr, stck_cntg_hour, cntg_yn, oder_qty 등을 포함한다.
        - ACK(BrokerOrderResponse)와 분리하고 실제 cntg_yn=Y 이벤트만 ExecutionReport로 변환한다.
        - client_order_id는 KIS notice에 없으므로 OMS correlation context에서 공급한다.
        - remaining_quantity는 주문수량과 이전 누적체결수량을 사용해 계산한다. cntg_qty는 해당 체결통보의 체결수량으로 취급한다.
        - 날짜가 없는 stck_cntg_hour를 임의 날짜와 결합하지 않아 execution_timestamp=None으로 보존한다.
        - execution_id는 원문 wire frame SHA-256으로 생성하여 동일 frame 재수신을 동일 event로 식별한다.
[Child Page] execution_event_deduplicator.py
```python
from __future__ import annotations

from contracts.types import ExecutionReport


class ExecutionEventDeduplicator:
    """Live-owned exactly-once delivery gate for execution events."""

    def __init__(self) -> None:
        self._seen_execution_ids: set[str] = set()

    def accept(self, report: ExecutionReport) -> bool:
        execution_id = str(report.execution_id or "").strip()
        if not execution_id:
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if execution_id in self._seen_execution_ids:
            return False
        self._seen_execution_ids.add(execution_id)
        return True

    def contains(self, execution_id: str) -> bool:
        return str(execution_id).strip() in self._seen_execution_ids
```
## Boundary rules
        - ExecutionReport.execution_id is the authoritative execution-event identity.
        - The first occurrence returns True and records the identity.
        - A repeated identity returns False and is not delivered downstream.
        - Missing execution identity fails closed; no fallback identity is generated.
        - This implementation is Live-owned and does not import Virtual execution code.
[Child Page] kis_futures_execution_correlation_provider.py
```python
from __future__ import annotations

from core.oms.oms_fsm import ExecutionCorrelation, OrderStateMachine


class KISFuturesExecutionCorrelationError(ValueError):
    """Raised when a KIS execution notice cannot be correlated safely."""


class KISFuturesExecutionCorrelationProvider:
    """Resolve H0IFCNI0 broker order numbers from OMS-owned state.

    This provider never creates client_order_id, order quantity, prior fill
    quantity, or prior average price. All values come from the accepted ACK/order
    and execution state already owned by OMS.
    """

    def __init__(self, order_state_machine: OrderStateMachine) -> None:
        self._orders = order_state_machine

    def resolve(self, broker_order_id: str) -> ExecutionCorrelation:
        try:
            return self._orders.resolve_execution_correlation(broker_order_id)
        except Exception as exc:
            raise KISFuturesExecutionCorrelationError(str(exc)) from exc
```
## Boundary
        - Source: OMS OrderStateMachine only.
        - Lookup key: authoritative KIS oder_no / broker_order_id.
        - Returned state: client_order_id, original order quantity, prior cumulative fill quantity, and OMS-maintained prior average execution price when available.
        - No synthetic identity, quantity, date, or broker mapping is generated.
        - Unknown broker order IDs fail closed before ExecutionReport creation.
[Child Page] kis_futures_execution_consumer.py
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
    """Concrete H0IFCNI0 execution ingress."""

    def __init__(self, transport, adapter: KISFuturesExecutionNoticeAdapter, correlation_provider: KISFuturesExecutionCorrelationProvider, on_report: Callable[[object], Awaitable[None] | None]) -> None:
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
            KISFuturesExecutionContext(correlation.client_order_id, correlation.order_quantity, correlation.prior_filled_quantity),
        )
        result = self._on_report(report)
        if hasattr(result, "__await__"):
            await result
        return report

    async def cancel_receive(self) -> None:
        """Request transport-level interruption of a blocked receive."""
        cancel = getattr(self._transport, "cancel_recv", None)
        if callable(cancel):
            result = cancel()
            if hasattr(result, "__await__"):
                await result
            return
        await self._transport.close()

    async def close(self) -> None:
        await self._transport.close()
```
책임 경계:
        - dedicated execution transport → H0IFCNI0 adapter → OMS correlation → ExecutionReport.
        - Position mutation은 기존 LiveExecutionPositionBridge에 맡긴다.
        - Market consumer/MarketState를 참조하지 않는다.
        - cancel_receive()는 transport-level receive interruption만 수행하며 Domain 주문 상태를 변경하지 않는다.
[Child Page] kis_futures_execution_recovery_adapter.py
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Sequence

from contracts.types import DataQuality, ExecutionReport


KIS_FUTURES_EXECUTION_INQUIRY_PATH = "/uapi/domestic-futureoption/v1/trading/inquire-ccnl"
KIS_FUTURES_EXECUTION_INQUIRY_REAL_TR_ID = "TTTO5201R"
KIS_FUTURES_EXECUTION_INQUIRY_VTS_TR_ID = "VTTO5201R"


class KISExecutionRecoveryInvalid(ValueError):
    """Raised when authoritative REST recovery data cannot be safely normalized."""


@dataclass(frozen=True)
class KISExecutionRecoveryQuery:
    cano: str
    account_product_code: str
    start_order_date: str
    end_order_date: str
    virtual: bool = False
    ctx_area_fk200: str = ""
    ctx_area_nk200: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.cano, "CANO"),
            (self.account_product_code, "ACNT_PRDT_CD"),
            (self.start_order_date, "STRT_ORD_DT"),
            (self.end_order_date, "END_ORD_DT"),
        ):
            if not str(value).strip():
                raise KISExecutionRecoveryInvalid(f"{name}_REQUIRED")

    @property
    def tr_id(self) -> str:
        return (
            KIS_FUTURES_EXECUTION_INQUIRY_VTS_TR_ID
            if self.virtual
            else KIS_FUTURES_EXECUTION_INQUIRY_REAL_TR_ID
        )

    def params(self) -> Mapping[str, str]:
        return {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.account_product_code,
            "STRT_ORD_DT": self.start_order_date,
            "END_ORD_DT": self.end_order_date,
            "SLL_BUY_DVSN_CD": "00",
            "CCLD_NCCS_DVSN": "01",
            "SORT_SQN": "DS",
            "PDNO": "",
            "STRT_ODNO": "",
            "MKET_ID_CD": "",
            "CTX_AREA_FK200": self.ctx_area_fk200,
            "CTX_AREA_NK200": self.ctx_area_nk200,
        }


@dataclass(frozen=True)
class KISExecutionRecoveryContext:
    client_order_id: str
    order_quantity: int
    prior_filled_quantity: int = 0
    prior_average_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise KISExecutionRecoveryInvalid("CLIENT_ORDER_ID_REQUIRED")
        if self.order_quantity <= 0:
            raise KISExecutionRecoveryInvalid("ORDER_QUANTITY_REQUIRED")
        if self.prior_filled_quantity < 0:
            raise KISExecutionRecoveryInvalid("PRIOR_FILLED_QUANTITY_INVALID")


class KISFuturesExecutionRecoveryAdapter:
    """Normalize the official KIS inquire-ccnl order-level fill snapshot.

    The official response exposes order-level cumulative fields such as
    ``odno``, ``ord_qty``, ``qty``, ``tot_ccld_qty`` and ``avg_idx``. It does
    not expose an authoritative execution-level ID. Therefore this adapter
    derives a *REST-source-local snapshot identity* only for exactly-once
    handling of repeated recovery snapshots; it never claims that identity is
    equivalent to the H0IFCNI0 wire identity.
    """

    PATH = KIS_FUTURES_EXECUTION_INQUIRY_PATH

    def build_request(self, query: KISExecutionRecoveryQuery) -> tuple[str, str, Mapping[str, str]]:
        return self.PATH, query.tr_id, query.params()

    def to_execution_report(
        self,
        row: Mapping[str, object],
        context: KISExecutionRecoveryContext,
    ) -> ExecutionReport | None:
        order_id = self._required(row, "odno")
        cumulative = self._non_negative_int(row, "tot_ccld_qty")
        if cumulative < context.prior_filled_quantity:
            raise KISExecutionRecoveryInvalid("CUMULATIVE_FILLED_QUANTITY_REGRESSION")
        if cumulative > context.order_quantity:
            raise KISExecutionRecoveryInvalid("EXECUTION_QUANTITY_EXCEEDS_ORDER")

        delta = cumulative - context.prior_filled_quantity
        if delta == 0:
            return None

        cumulative_average = self._positive_decimal(row, "avg_idx")
        price = self._delta_execution_price(
            cumulative=cumulative,
            cumulative_average=cumulative_average,
            prior_filled_quantity=context.prior_filled_quantity,
            prior_average_price=context.prior_average_price,
        )
        status = "FILLED" if cumulative == context.order_quantity else "PARTIALLY_FILLED"
        execution_id = self._snapshot_identity(order_id, cumulative, cumulative_average)

        return ExecutionReport(
            client_order_id=context.client_order_id,
            broker_order_id=order_id,
            execution_id=execution_id,
            status=status,
            filled_quantity=delta,
            remaining_quantity=context.order_quantity - cumulative,
            execution_price=price,
            execution_timestamp=self._timestamp_or_none(row),
            source_freshness=DataQuality(
                is_fresh=True,
                is_complete=False,
                source_available=True,
                reason="KIS inquire-ccnl REST recovery order snapshot",
            ),
        )

    def normalize(
        self,
        response: Mapping[str, object],
        context_for_order: Callable[[str], KISExecutionRecoveryContext],
    ) -> tuple[ExecutionReport, ...]:
        rows = response.get("output1")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise KISExecutionRecoveryInvalid("OUTPUT1_REQUIRED")

        reports: list[ExecutionReport] = []
        cumulative_by_order: dict[str, int] = {}
        average_by_order: dict[str, Decimal | None] = {}
        context_by_order: dict[str, KISExecutionRecoveryContext] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise KISExecutionRecoveryInvalid("OUTPUT1_ROW_INVALID")
            order_id = self._required(row, "odno")
            if order_id not in context_by_order:
                context_by_order[order_id] = context_for_order(order_id)
                cumulative_by_order[order_id] = context_by_order[order_id].prior_filled_quantity
                average_by_order[order_id] = context_by_order[order_id].prior_average_price
            base_context = context_by_order[order_id]
            current_context = KISExecutionRecoveryContext(
                client_order_id=base_context.client_order_id,
                order_quantity=base_context.order_quantity,
                prior_filled_quantity=cumulative_by_order[order_id],
                prior_average_price=average_by_order[order_id],
            )
            report = self.to_execution_report(row, current_context)
            if report is not None:
                reports.append(report)
                cumulative_by_order[order_id] += report.filled_quantity
                average_by_order[order_id] = self._positive_decimal(row, "avg_idx")
        return tuple(reports)

    @staticmethod
    def _required(row: Mapping[str, object], key: str) -> str:
        value = str(row.get(key, "")).strip()
        if not value:
            raise KISExecutionRecoveryInvalid(f"{key.upper()}_REQUIRED")
        return value

    @staticmethod
    def _non_negative_int(row: Mapping[str, object], key: str) -> int:
        try:
            value = int(str(row.get(key, "")).strip())
        except (TypeError, ValueError) as exc:
            raise KISExecutionRecoveryInvalid(f"{key.upper()}_INVALID") from exc
        if value < 0:
            raise KISExecutionRecoveryInvalid(f"{key.upper()}_INVALID")
        return value

    @staticmethod
    def _positive_decimal(row: Mapping[str, object], key: str) -> Decimal:
        try:
            value = Decimal(str(row.get(key, "")).strip())
        except (InvalidOperation, ValueError) as exc:
            raise KISExecutionRecoveryInvalid(f"{key.upper()}_INVALID") from exc
        if value <= 0:
            raise KISExecutionRecoveryInvalid(f"{key.upper()}_INVALID")
        return value

    @staticmethod
    def _delta_execution_price(
        *,
        cumulative: int,
        cumulative_average: Decimal,
        prior_filled_quantity: int,
        prior_average_price: Decimal | None,
    ) -> Decimal:
        if prior_filled_quantity == 0:
            return cumulative_average
        if prior_average_price is None:
            raise KISExecutionRecoveryInvalid("PRIOR_AVERAGE_PRICE_REQUIRED_FOR_DELTA_PRICE")
        delta_quantity = cumulative - prior_filled_quantity
        if delta_quantity <= 0:
            raise KISExecutionRecoveryInvalid("DELTA_QUANTITY_INVALID")
        delta_price = (
            cumulative_average * Decimal(cumulative)
            - prior_average_price * Decimal(prior_filled_quantity)
        ) / Decimal(delta_quantity)
        if delta_price <= 0:
            raise KISExecutionRecoveryInvalid("DELTA_EXECUTION_PRICE_INVALID")
        return delta_price

    @staticmethod
    def _snapshot_identity(order_id: str, cumulative: int, cumulative_average: Decimal) -> str:
        return f"REST-CCNL-SNAPSHOT|{order_id}|{cumulative}|{cumulative_average}"

    @staticmethod
    def _timestamp_or_none(row: Mapping[str, object]) -> datetime | None:
        order_date = str(row.get("ord_dt", "")).strip()
        order_time = str(row.get("ord_tmd", "")).strip()
        if len(order_date) == 8 and order_date.isdigit() and len(order_time) == 6 and order_time.isdigit():
            return datetime.strptime(order_date + order_time, "%Y%m%d%H%M%S")
        return None
```
## Boundary
        - Official KIS inquire-ccnl REST recovery is treated as an order-level cumulative snapshot, not an execution-level event stream.
        - tot_ccld_qty is authoritative cumulative filled quantity and avg_idx is the official average execution index/price field.
        - filled_quantity is the delta from the OMS correlation context's prior cumulative fill.
        - Because avg_idx is an order-level cumulative average, a later snapshot's incremental execution price is derived as (current_avg × current_cumulative_qty − prior_avg × prior_cumulative_qty) / delta_qty when prior average price is available.
        - If recovery starts from an already partially filled OMS state but no authoritative prior average price is available, the incremental execution price is fail-closed rather than guessed.
        - execution_id is a REST-source-local snapshot identity only; it is not asserted to equal H0IFCNI0 identity.
        - ctx_area_fk200 / ctx_area_nk200 are carried by the query for official pagination.
        - Synthetic cross-source identity mapping remains prohibited.
[Child Page] test_kis_futures_execution_recovery_adapter.py
```python
from decimal import Decimal

import pytest

from environments.live.execution.kis_futures_execution_recovery_adapter import (
    KISExecutionRecoveryInvalid,
    KISExecutionRecoveryContext,
    KISExecutionRecoveryQuery,
    KISFuturesExecutionRecoveryAdapter,
)


def row(**overrides):
    value = {
        "odno": "00012345",
        "ord_qty": "5",
        "tot_ccld_qty": "2",
        "avg_idx": "350.25",
        "ord_dt": "20260906",
        "ord_tmd": "101530",
    }
    value.update(overrides)
    return value


def context(**overrides):
    value = {
        "client_order_id": "CLIENT-1",
        "order_quantity": 5,
        "prior_filled_quantity": 0,
        "prior_average_price": None,
    }
    value.update(overrides)
    return KISExecutionRecoveryContext(**value)


def test_real_request_contract_matches_official_inquire_ccnl():
    path, tr_id, params = KISFuturesExecutionRecoveryAdapter().build_request(
        KISExecutionRecoveryQuery("12345678", "03", "20260906", "20260906")
    )
    assert path == "/uapi/domestic-futureoption/v1/trading/inquire-ccnl"
    assert tr_id == "TTTO5201R"
    assert params["CCLD_NCCS_DVSN"] == "01"
    assert params["SLL_BUY_DVSN_CD"] == "00"
    assert params["SORT_SQN"] == "DS"
    assert params["CTX_AREA_FK200"] == ""
    assert params["CTX_AREA_NK200"] == ""


def test_vts_request_uses_vt_tr_id():
    query = KISExecutionRecoveryQuery("12345678", "03", "20260906", "20260906", virtual=True)
    assert query.tr_id == "VTTO5201R"


def test_official_order_snapshot_maps_cumulative_total_to_delta_report():
    report = KISFuturesExecutionRecoveryAdapter().to_execution_report(row(), context())
    assert report is not None
    assert report.execution_id == "REST-CCNL-SNAPSHOT|00012345|2|350.25"
    assert report.filled_quantity == 2
    assert report.execution_price == Decimal("350.25")
    assert report.status == "PARTIALLY_FILLED"
    assert report.remaining_quantity == 3


def test_recovery_snapshot_uses_prior_fill_and_average_to_calculate_delta_price():
    report = KISFuturesExecutionRecoveryAdapter().to_execution_report(
        row(tot_ccld_qty="5", avg_idx="351.00"),
        context(prior_filled_quantity=2, prior_average_price=Decimal("350.25")),
    )
    assert report is not None
    assert report.filled_quantity == 3
    assert report.execution_price == Decimal("351.50")
    assert report.remaining_quantity == 0
    assert report.status == "FILLED"


def test_preexisting_partial_recovery_without_prior_average_fails_closed():
    with pytest.raises(KISExecutionRecoveryInvalid, match="PRIOR_AVERAGE_PRICE_REQUIRED_FOR_DELTA_PRICE"):
        KISFuturesExecutionRecoveryAdapter().to_execution_report(
            row(tot_ccld_qty="5", avg_idx="351.00"),
            context(prior_filled_quantity=2),
        )


def test_order_date_and_time_reconstruct_execution_timestamp():
    report = KISFuturesExecutionRecoveryAdapter().to_execution_report(row(), context())
    assert report is not None
    assert report.execution_timestamp is not None
    assert report.execution_timestamp.strftime("%Y%m%d%H%M%S") == "20260906101530"


def test_repeated_same_snapshot_produces_no_new_execution():
    report = KISFuturesExecutionRecoveryAdapter().to_execution_report(
        row(tot_ccld_qty="2"),
        context(prior_filled_quantity=2),
    )
    assert report is None


def test_cumulative_regression_fails_closed():
    with pytest.raises(KISExecutionRecoveryInvalid, match="CUMULATIVE_FILLED_QUANTITY_REGRESSION"):
        KISFuturesExecutionRecoveryAdapter().to_execution_report(
            row(tot_ccld_qty="1"), context(prior_filled_quantity=2)
        )


def test_response_output1_normalization_uses_order_context():
    adapter = KISFuturesExecutionRecoveryAdapter()
    reports = adapter.normalize(
        {
            "output1": [
                row(odno="B1", tot_ccld_qty="2"),
                row(odno="B2", tot_ccld_qty="5", avg_idx="351.25"),
            ]
        },
        lambda order_id: context(client_order_id=f"C-{order_id}"),
    )
    assert [report.client_order_id for report in reports] == ["C-B1", "C-B2"]
    assert [report.filled_quantity for report in reports] == [2, 5]

```
## Targeted verification
        - REAL/VTS TR-ID 분기.
        - 공식 inquire-ccnl request parameters 및 continuation keys.
        - 공식 order-level tot_ccld_qty cumulative snapshot을 delta fill로 변환.
        - 공식 avg_idx 평균지수/가격 field 보존.
        - 반복 동일 snapshot의 no-op 처리.
        - cumulative regression 및 과주문량 fail-closed.
        - REST-source-local snapshot identity와 H0IFCNI0 cross-source identity를 구분.
[Child Page] kis_futures_execution_recovery_transport.py
```python
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
    """Authenticated GET transport for KIS inquire-ccnl recovery.

    The transport owns HTTP/authentication and official KIS continuation. Row
    normalization remains in KISFuturesExecutionRecoveryAdapter and settlement
    remains in Application.
    """

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
```
## Boundary
        - GET /uapi/domestic-futureoption/v1/trading/inquire-ccnl only.
        - Reuses KISAuthManager.get_auth_headers(tr_id=...) and adds official tr_cont only for continuation requests.
        - Query serialization includes official CTX_AREA_FK200 / CTX_AREA_NK200 continuation values.
        - Response pages are accumulated through the official tr_cont response header values M / F and body continuation keys.
        - Pagination has an explicit safety limit; it is not inferred from row count.
        - HTTP/auth failures are transport errors; no synthetic empty response is returned.
[Child Page] live_execution_recovery_service.py
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from contracts.types import ExecutionReport
from environments.live.execution.kis_futures_execution_recovery_adapter import (
    KISExecutionRecoveryContext,
    KISExecutionRecoveryQuery,
    KISFuturesExecutionRecoveryAdapter,
)


class RecoveryTransport(Protocol):
    def inquire(self, query: KISExecutionRecoveryQuery) -> dict[str, object]: ...


class ExecutionCorrelationProvider(Protocol):
    def resolve(self, broker_order_id: str): ...


@dataclass
class LiveExecutionRecoveryService:
    """Application-owned reconciliation entry for REST recovery reports."""

    transport: RecoveryTransport
    adapter: KISFuturesExecutionRecoveryAdapter
    correlation_provider: ExecutionCorrelationProvider
    on_report: Callable[[ExecutionReport], object]

    def recover(self, query: KISExecutionRecoveryQuery) -> tuple[object, ...]:
        response = self.transport.inquire(query)

        def context_for_order(broker_order_id: str) -> KISExecutionRecoveryContext:
            correlation = self.correlation_provider.resolve(broker_order_id)
            return KISExecutionRecoveryContext(
                client_order_id=correlation.client_order_id,
                order_quantity=correlation.order_quantity,
                prior_filled_quantity=correlation.prior_filled_quantity,
                prior_average_price=getattr(correlation, "prior_average_price", None),
            )

        reports = self.adapter.normalize(response, context_for_order)
        return tuple(self.on_report(report) for report in reports)
```
## Responsibility
        - REST recovery and H0IFCNI0 remain separate ingress sources.
        - Both paths converge only through the existing ExecutionReport -> dedup -> OMS -> Position settlement callback.
        - OMS correlation remains authoritative for client order identity and fill context.
        - Duplicate reports are not filtered here; the shared Live deduplicator remains the single exactly-once gate.

[Child Page] position
Live execution에 의해 변경되는 authoritative Position aggregate 경계. Position semantics는 최소 aggregate 수준으로 유지하며, KIS broker/ACK 로직과 분리한다.
[Child Page] live_position_aggregate.py
```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PositionAggregate:
    instrument_id: str
    side: str | None
    qty: int
    avg_price: Decimal | None


class LivePositionAggregate:
    """Live-owned authoritative side/quantity/average-price aggregate."""

    def __init__(self, instrument_id: str) -> None:
        instrument_id = str(instrument_id).strip()
        if not instrument_id:
            raise ValueError("INSTRUMENT_ID_REQUIRED")
        self.instrument_id = instrument_id
        self.side: str | None = None
        self.qty = 0
        self.avg_price: Decimal | None = None

    def apply_fill(self, *, side: str, quantity: int, price: Decimal) -> None:
        if side not in {"BUY", "SELL"}:
            raise ValueError("SIDE_INVALID")
        if not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("QUANTITY_INVALID")
        if not isinstance(price, Decimal) or price <= 0:
            raise ValueError("PRICE_INVALID")

        if self.qty == 0 or self.side is None:
            self.side, self.qty, self.avg_price = side, quantity, price
            return

        if side == self.side:
            assert self.avg_price is not None
            self.avg_price = ((self.avg_price * self.qty) + (price * quantity)) / (self.qty + quantity)
            self.qty += quantity
            return

        if quantity < self.qty:
            self.qty -= quantity
            return
        if quantity == self.qty:
            self.side, self.qty, self.avg_price = None, 0, None
            return

        self.side = side
        self.qty = quantity - self.qty
        self.avg_price = price

    def snapshot(self) -> PositionAggregate:
        return PositionAggregate(self.instrument_id, self.side, self.qty, self.avg_price)
```
## Boundary rules
        - Position state is authoritative within the Live environment: instrument_id, side, qty, avg_price.
        - Same-side fills use weighted-average execution price.
        - Opposite-side fills reduce, clear, or flip the position according to quantity.
        - Side is explicit; no sign-based side inference is used.
        - FIFO, lot attribution, PnL, and Risk policy remain outside this aggregate.
[Child Page] live_position_fill_adapter.py
```python
from __future__ import annotations

from contracts.types import BrokerOrderCommand, ExecutionReport


class LivePositionFillAdapter:
    """Validate a canonical fill against its originating broker command."""

    def __init__(self, aggregate) -> None:
        self._aggregate = aggregate

    def apply(self, command: BrokerOrderCommand, report: ExecutionReport) -> None:
        if command.client_order_id != report.client_order_id:
            raise ValueError("CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self._aggregate.instrument_id:
            raise ValueError("INSTRUMENT_ID_MISMATCH")
        if command.side not in {"BUY", "SELL"}:
            raise ValueError("SIDE_INVALID")
        if report.filled_quantity <= 0 or report.filled_quantity > command.quantity:
            raise ValueError("FILLED_QUANTITY_INVALID")
        if report.execution_price is None:
            raise ValueError("EXECUTION_PRICE_REQUIRED")
        self._aggregate.apply_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=report.execution_price,
        )
```
## Boundary rules
        - client_order_id, instrument_id, side, quantity, and execution price are validated before Position mutation.
        - Side comes only from BrokerOrderCommand; it is never inferred from quantity sign.
        - requested_price is not used for settlement.
        - FIFO, lot attribution, PnL, and Risk policy remain outside this adapter.
[Child Page] live_execution_position_bridge.py
```python
from __future__ import annotations

from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError


class LivePositionFillAdapter:
    """Validate a canonical fill against its originating broker command."""

    def __init__(self, aggregate) -> None:
        self._aggregate = aggregate

    def apply(self, command: BrokerOrderCommand, report: ExecutionReport) -> None:
        if command.client_order_id != report.client_order_id:
            raise ValueError("CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self._aggregate.instrument_id:
            raise ValueError("INSTRUMENT_ID_MISMATCH")
        if command.side not in {"BUY", "SELL"}:
            raise ValueError("SIDE_INVALID")
        if report.filled_quantity <= 0 or report.filled_quantity > command.quantity:
            raise ValueError("FILLED_QUANTITY_INVALID")
        if report.execution_price is None:
            raise ValueError("EXECUTION_PRICE_REQUIRED")
        self._aggregate.apply_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=Decimal(report.execution_price),
        )


class LiveExecutionPositionBridge:
    """Settle an accepted execution exactly once into OMS and Live Position."""

    def __init__(
        self,
        *,
        order_state_machine: OrderStateMachine,
        position_fill_adapter: LivePositionFillAdapter,
        execution_event_deduplicator,
        position_aggregate,
    ) -> None:
        self._oms = order_state_machine
        self._fill_adapter = position_fill_adapter
        self._dedup = execution_event_deduplicator
        self._position = position_aggregate

    def settle(self, report: ExecutionReport) -> object:
        state = self._oms.get(report.client_order_id)
        if state is None:
            raise OrderStateTransitionError("EXECUTION_BEFORE_ACK")

        # A known replay must be detected before the state-transition guard:
        # an already-settled execution can legitimately arrive after FILLED.
        # For a new event, validate the current state first so an invalid/stale
        # event is not consumed by the deduplication gate.
        execution_id = str(report.execution_id or "").strip()
        if not execution_id:
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if self._dedup.contains(execution_id):
            return state

        if state.status not in {"ACKED", "PARTIALLY_FILLED"}:
            raise OrderStateTransitionError("EXECUTION_BEFORE_ACK")

        command = self._oms.get_broker_order_command(report.broker_order_id)
        if report.status not in {"PARTIALLY_FILLED", "FILLED"}:
            raise OrderStateTransitionError("UNSUPPORTED_EXECUTION_STATUS")
        if report.filled_quantity <= 0:
            raise OrderStateTransitionError("FILLED_QUANTITY_INVALID")
        cumulative = state.filled_quantity + report.filled_quantity
        if cumulative > state.order_quantity:
            raise OrderStateTransitionError("FILLED_QUANTITY_EXCEEDS_ORDER")
        if report.remaining_quantity != state.order_quantity - cumulative:
            raise OrderStateTransitionError("REMAINING_QUANTITY_MISMATCH")
        if report.broker_order_id and state.broker_order_id != report.broker_order_id:
            raise OrderStateTransitionError("BROKER_ORDER_ID_MISMATCH")

        # Consume the identity only after the complete transition has been
        # validated, while still keeping replay detection before any mutation.
        if not self._dedup.accept(report):
            return state
        state = self._oms.apply_execution(report)
        self._fill_adapter.apply(command, report)
        return state
```
## Boundary rules
        - client_order_id, instrument_id, side, quantity, and execution price are validated before Position mutation.
        - Side comes only from BrokerOrderCommand; it is never inferred from quantity sign.
        - requested_price is not used for settlement.
        - FIFO, lot attribution, PnL, and Risk policy remain outside this adapter.
        - LiveExecutionPositionBridge resolves the originating BrokerOrderCommand only from OMS-owned state.
        - Duplicate execution events are rejected before OMS/Position mutation.
        - No broker command, identity, side, quantity, or price is synthesized from ExecutionReport.
[Child Page] live_position_aggregate_risk_source.py
```python
# environments/live/position/live_position_aggregate_risk_source.py
from collections.abc import Mapping

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource
from environments.live.position.live_position_aggregate import LivePositionAggregate


class LivePositionAggregateRiskSource(PositionAggregateSource):
    """Read-only projection of authoritative Live aggregates for pre-trade Risk."""

    def __init__(self, aggregates: Mapping[str, LivePositionAggregate]) -> None:
        if not isinstance(aggregates, Mapping):
            raise TypeError("LIVE_POSITION_AGGREGATE_MAPPING_REQUIRED")
        self._aggregates = aggregates

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        projected: dict[str, PositionAggregate] = {}
        for instrument_id, aggregate in self._aggregates.items():
            if not isinstance(instrument_id, str) or not instrument_id:
                raise TypeError("LIVE_POSITION_INSTRUMENT_ID_REQUIRED")
            if not isinstance(aggregate, LivePositionAggregate):
                raise TypeError("LIVE_POSITION_AGGREGATE_REQUIRED")
            state = aggregate.snapshot()
            if state.instrument_id != instrument_id:
                raise ValueError("LIVE_POSITION_INSTRUMENT_ID_MISMATCH")
            if state.qty == 0:
                continue
            if state.side not in {'BUY', 'SELL'}:
                raise TypeError("LIVE_POSITION_SIDE_REQUIRED")
            if not isinstance(state.qty, int) or state.qty <= 0:
                raise TypeError("LIVE_POSITION_QTY_REQUIRED")
            projected[instrument_id] = PositionAggregate(
                side=state.side, qty=state.qty, avg_price=state.avg_price
            )
        return projected
```
## 경계
        - Live aggregate의 authoritative instrument_id/side/qty/avg_price를 읽기 전용으로 Standard PositionAggregateSource에 투영한다.
        - qty=0은 열린 포지션이 아니므로 Risk 입력에서 제외한다.
        - side/qty를 새로 계산하거나 추론하지 않는다.
        - FIFO/PnL/valuation/Risk 정책을 구현하지 않는다.
        - aggregate의 instrument_id와 mapping key 불일치는 fail-closed한다.
[Child Page] live_position_aggregate_risk_source.py
```python
from collections.abc import Mapping

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource
from environments.live.position.live_position_aggregate import LivePositionAggregate


class LivePositionAggregateRiskSource(PositionAggregateSource):
    """Read-only projection of authoritative Live aggregates for pre-trade Risk."""

    def __init__(self, aggregates: Mapping[str, LivePositionAggregate]) -> None:
        if not isinstance(aggregates, Mapping):
            raise TypeError("LIVE_POSITION_AGGREGATE_MAPPING_REQUIRED")
        self._aggregates = aggregates

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        projected = {}
        for instrument_id, aggregate in self._aggregates.items():
            if not isinstance(instrument_id, str) or not instrument_id:
                raise TypeError("LIVE_POSITION_INSTRUMENT_ID_REQUIRED")
            if not isinstance(aggregate, LivePositionAggregate):
                raise TypeError("LIVE_POSITION_AGGREGATE_REQUIRED")
            state = aggregate.snapshot()
            if state.instrument_id != instrument_id:
                raise ValueError("LIVE_POSITION_INSTRUMENT_ID_MISMATCH")
            if state.qty == 0:
                continue
            if state.side not in {"BUY", "SELL"}:
                raise TypeError("LIVE_POSITION_SIDE_REQUIRED")
            if not isinstance(state.qty, int) or state.qty <= 0:
                raise TypeError("LIVE_POSITION_QTY_REQUIRED")
            projected[instrument_id] = PositionAggregate(state.side, state.qty, state.avg_price)
        return projected
```
Read-only Live aggregate → Standard PositionAggregateSource projection. No side inference or state mutation.