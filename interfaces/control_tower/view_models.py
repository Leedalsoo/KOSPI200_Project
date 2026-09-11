"""Control Tower view models for runtime status display across 5 environments."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Sequence


class TabEnvironmentId(str, Enum):
    HIGH_SPEED = "high_speed"
    VIRTUAL_EXCHANGE = "virtual_exchange"
    VIRTUAL_BROKER = "virtual_broker"
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True)
class EnvironmentStatusView:
    environment: str | None = None
    runtime_state: str = "UNKNOWN"
    market_state: str = "UNKNOWN"
    account_state: str = "UNKNOWN"
    position_state: str = "UNKNOWN"
    pnl: float | None = None
    orders_state: str = "UNKNOWN"
    risk_state: str = "UNKNOWN"
    kill_switch: bool = True
    live_approval: bool = False
    credential_ready: bool = False
    execution_allowed: bool = False
    speed_multiplier: float | None = None
    scenario: str | None = None
    error: str | None = None


def from_runtime_status(status) -> EnvironmentStatusView:
    """Map only the Runtime status contract; never expose concrete environment objects."""
    return EnvironmentStatusView(
        environment=getattr(status, "environment", None),
        runtime_state=getattr(status, "state", "UNKNOWN"),
    )


# ---------------------------------------------------------------------------
# 5개 환경 탭 전용 View Models (UI Data Interface)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HighSpeedTestView:
    """1. High-Speed Test 환경 탭 뷰모델.
    
    초고속 합성 데이터 기반 실행 상태, 시장 데이터/틱/이벤트 흐름,
    Strategy/Decision 결과, 주문/체결 흐름, 계좌/포지션/PnL, 실행 속도 배속을 나타냅니다.
    """
    tab_id: str = "high_speed"
    tab_name: str = "High-Speed Test"
    runtime_state: str = "STOPPED"
    connection_state: str = "READY"
    speed_multiplier: float = 100.0
    scenario_name: str = "SYNTHETIC_HIGH_SPEED"
    processed_ticks: int = 0
    total_ticks: int = 0
    progress_ratio: float = 0.0
    last_tick_time: str | None = None
    strategy_decisions_count: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    total_pnl: float = 0.0
    cash_balance: float = 100_000_000.0
    positions: list[dict[str, Any]] = field(default_factory=list)
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    audit_logs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VirtualExchangeView:
    """2. 가상거래소 (Virtual Market) 탭 뷰모델.
    
    Virtual Market의 시장 데이터/틱/이벤트 흐름, 시장 상태 및 마지막 시각,
    Strategy/Core로 유입되는 실제 이벤트를 나타냅니다.
    """
    tab_id: str = "virtual_exchange"
    tab_name: str = "가상거래소"
    market_state: str = "OPEN"
    connection_state: str = "CONNECTED"
    last_data_time: str | None = None
    instruments_count: int = 0
    recent_ticks: list[dict[str, Any]] = field(default_factory=list)
    market_depth: dict[str, Any] = field(default_factory=dict)
    feed_latency_ms: float = 0.0
    underlying_index_price: float | None = None
    volatility_index: float | None = None
    audit_logs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VirtualBrokerView:
    """3. 가상증권사 (Virtual Broker) 탭 뷰모델.
    
    주문 접수, 주문 상태 전이, 체결, 계좌/포지션 업데이트 등
    실제 KIS 계약을 미러링한 상태를 나타냅니다.
    """
    tab_id: str = "virtual_broker"
    tab_name: str = "가상증권사"
    broker_state: str = "OPERATIONAL"
    connection_state: str = "CONNECTED"
    account_number: str = "VIRTUAL-8801-01"
    cash_balance: float = 100_000_000.0
    margin_used: float = 0.0
    margin_available: float = 100_000_000.0
    active_orders: list[dict[str, Any]] = field(default_factory=list)
    recent_executions: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    audit_logs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PaperTradingView:
    """4. 모의투자 (KIS Developers 모의) 탭 뷰모델.
    
    실제 KIS 모의투자 API 환경 상태. 실제 미연결 시 가짜 연결 성공을 표시하지 않고
    DISCONNECTED / BLOCKED / NotImplemented 상태를 명확히 표시합니다.
    """
    tab_id: str = "paper"
    tab_name: str = "모의투자"
    runtime_state: str = "STOPPED"
    connection_state: str = "DISCONNECTED"
    api_endpoint: str = "https://openapivts.koreainvestment.com:29443"
    auth_state: str = "TOKEN_NOT_ACQUIRED"
    broker_ready: bool = False
    market_data_state: str = "DISCONNECTED"
    account_number: str = "—"
    cash_balance: float | None = None
    positions: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    executions: list[dict[str, Any]] = field(default_factory=list)
    risk_state: str = "DISCONNECTED"
    blocked_reason: str = "KIS 모의투자 API 실서버 연결 미수행 (LIVE/PAPER 외부망 연결 분리)"
    audit_logs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LiveTradingView:
    """5. 실투자 (KIS Developers 실계좌) 탭 뷰모델.
    
    실계좌 연결/인증 상태, 주문 가능 상태, Risk/Execution, 미체결/체결/포지션/증거금,
    비상정지/안전 상태. 실제 미연결 시 가짜 LIVE 성공을 표시하지 않고 DISCONNECTED/BLOCKED를 표시합니다.
    """
    tab_id: str = "live"
    tab_name: str = "실투자"
    runtime_state: str = "STOPPED"
    connection_state: str = "DISCONNECTED"
    api_endpoint: str = "https://openapi.koreainvestment.com:9443"
    auth_state: str = "CREDENTIAL_UNARMED"
    live_approval: bool = False
    kill_switch_engaged: bool = True
    execution_allowed: bool = False
    account_number: str = "—"
    total_margin: float | None = None
    margin_ratio: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None
    positions: list[dict[str, Any]] = field(default_factory=list)
    open_orders: list[dict[str, Any]] = field(default_factory=list)
    recent_executions: list[dict[str, Any]] = field(default_factory=list)
    risk_circuit_breaker: str = "CLOSED_FAIL_SAFE"
    blocked_reason: str = "실계좌 안전 차단 상태 (명시적 ARM 및 외부 실계좌 연결 승인 필요)"
    audit_logs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ControlTowerSummaryView:
    """5개 환경 통합 요약 상태 뷰모델."""
    active_environment: str = "virtual_exchange"
    system_time: str = ""
    kill_switch_global: bool = True
    tabs: list[dict[str, Any]] = field(default_factory=list)
    alert_message: str | None = None
