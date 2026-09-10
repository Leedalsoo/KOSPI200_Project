폴더 페이지

[Child Page] clock.py
```python
from datetime import datetime, timedelta

from contracts.clock import ClockProvider


class VirtualClock(ClockProvider):
    """Deterministic simulation clock for the Virtual Environment."""

    def __init__(self, start: datetime):
        self._now = start
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def sleep_policy(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds
```
## Contract 정합화
    - ClockProvider의 now / monotonic / sleep_policy 세 메서드를 모두 구현한다.
    - Virtual Market이 직접 시스템 시간을 호출하지 않고 이 Clock을 주입받도록 한다.
    - sleep_policy()는 실제 프로세스를 대기시키지 않고 가상 시간을 전진시킨다.
    - High-Speed는 동일한 ClockProvider 경계를 사용하면서 별도의 가속 정책을 적용할 수 있다.
    - 실제 시장시간을 의미하는 것으로 가장하지 않으며, Virtual/High-Speed 검증용 시간원으로 한정한다.
[Child Page] vms_clock_provider_adapter.py
```python
from datetime import datetime
from typing import Protocol

from contracts.clock import ClockProvider


class VMSClockSource(Protocol):
    current_time: datetime

    def advance_tick(self, milliseconds: int = 500) -> datetime: ...


class VMSClockProvider(ClockProvider):
    """Read/advance adapter for the reference VMS simulation clock."""

    def __init__(self, source: VMSClockSource, *, tick_milliseconds: int = 500):
        if tick_milliseconds <= 0:
            raise ValueError("VMS_CLOCK_TICK_MILLISECONDS_REQUIRED")
        self._source = source
        self._tick_milliseconds = tick_milliseconds
        self._elapsed_seconds = 0.0

    def now(self) -> datetime:
        current = self._source.current_time
        if not isinstance(current, datetime):
            raise TypeError("VMS_CLOCK_CURRENT_TIME_REQUIRED")
        return current

    def monotonic(self) -> float:
        return self._elapsed_seconds

    def sleep_policy(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        milliseconds = int(round(seconds * 1000.0))
        if milliseconds == 0:
            return
        remaining = milliseconds
        while remaining > 0:
            step = min(self._tick_milliseconds, remaining)
            self._source.advance_tick(step)
            remaining -= step
        self._elapsed_seconds += seconds
```
[Child Page] test_vms_clock_provider_adapter.py
```python
from datetime import datetime, timedelta

import pytest

from environments.virtual.clock.vms_clock_provider_adapter import VMSClockProvider


class FakeVMSClock:
    def __init__(self):
        self.current_time = datetime(2026, 8, 23, 9, 0, 0)
        self.calls = []

    def advance_tick(self, milliseconds=500):
        self.calls.append(milliseconds)
        self.current_time += timedelta(milliseconds=milliseconds)
        return self.current_time


def test_now_preserves_vms_current_time():
    source = FakeVMSClock()
    clock = VMSClockProvider(source)
    assert clock.now() == source.current_time


def test_sleep_policy_advances_reference_tick_source():
    source = FakeVMSClock()
    clock = VMSClockProvider(source)
    clock.sleep_policy(1.0)
    assert source.calls == [500, 500]
    assert clock.now() == datetime(2026, 8, 23, 9, 0, 1)
    assert clock.monotonic() == 1.0


def test_fractional_sleep_uses_partial_final_tick():
    source = FakeVMSClock()
    clock = VMSClockProvider(source)
    clock.sleep_policy(0.75)
    assert source.calls == [500, 250]
    assert clock.monotonic() == 0.75


def test_negative_sleep_fails_closed():
    source = FakeVMSClock()
    clock = VMSClockProvider(source)
    with pytest.raises(ValueError, match="seconds must be non-negative"):
        clock.sleep_policy(-0.1)


def test_invalid_current_time_fails_closed():
    source = FakeVMSClock()
    source.current_time = "invalid"
    clock = VMSClockProvider(source)
    with pytest.raises(TypeError, match="VMS_CLOCK_CURRENT_TIME_REQUIRED"):
        clock.now()
```

[Child Page] bundle.py
```python
from dataclasses import dataclass
from typing import Any

from contracts.types import EnvironmentType
from environments.bundle_interface import StandardEnvironmentBundle


@dataclass
class VirtualEnvironmentBundle(StandardEnvironmentBundle):
    """Composition boundary for VMS/VSSF-derived Virtual Trading components."""

    config: Any
    policy: Any
    market: object
    clock: object
    broker: object
    account: object
    position: object
    execution: object
    environment: EnvironmentType = EnvironmentType.VIRTUAL
    connected: bool = False
    running: bool = False

    def initialize(self) -> None:
        self.connected = False
        self.running = False

    def connect(self) -> None:
        self.connected = True

    def start(self) -> None:
        if not self.connected:
            raise RuntimeError("Virtual Environment must be connected before start")
        self.running = True

    def stop(self) -> None:
        self.running = False

    def restart(self) -> None:
        self.stop()
        self.connect()
        self.start()

    def shutdown(self) -> None:
        self.running = False
        self.connected = False

    @classmethod
    def create(
        cls,
        config: Any,
        policy: Any,
        *,
        market: object,
        clock: object,
        broker: object,
        account: object,
        position: object,
        execution: object,
    ) -> "VirtualEnvironmentBundle":
        if config.environment is not EnvironmentType.VIRTUAL:
            raise ValueError(
                f"VirtualEnvironmentBundle requires virtual environment, got {config.environment}"
            )
        return cls(
            config=config,
            policy=policy,
            market=market,
            clock=clock,
            broker=broker,
            account=account,
            position=position,
            execution=execution,
        )
```
## Composition 경계
    - Virtual Bundle은 VMS Market + Virtual Clock + VSSF-derived Broker/Account/Position/Execution을 하나의 Environment 경계로 묶는다.
    - lifecycle은 Standard EnvironmentLifecycle 계약을 따른다.
    - create()는 구성요소를 명시적으로 주입받는다. 임의의 초기 가격·계좌잔고·시장 시나리오를 Bundle이 발명하지 않는다.
    - 기존 VMS/VSSF 구성요소를 실제 연결할 때 기능 의미를 보존할 수 있도록 composition 책임만 가진다.
    - Bundle은 Core/Strategy를 생성하거나 변경하지 않는다.
## 현재 통합 상태
application/environment_hub/factory.py는 아직 VirtualEnvironmentBundle(config, policy) 형태를 호출한다. 이번 단계에서 임의의 기본값으로 이 호출을 숨기지 않았다. 실제 VMS/VSSF 구성 파라미터와 Factory 입력 경계를 확정한 뒤 Factory를 create() 기반 composition으로 전환해야 한다.

[Child Page] market
[Child Page] virtual_market.py
```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from contracts.clock import ClockProvider
from contracts.types import CanonicalMarketTick


@dataclass(frozen=True)
class VirtualMarketConfig:
    initial_price: Decimal
    tick_interval_seconds: float


class VirtualMarket(Protocol):
    def next_tick(self) -> CanonicalMarketTick: ...


class VirtualMarketFeed:
    """Virtual-only synthetic market. Never used by Paper/Live."""

    def __init__(self, config: VirtualMarketConfig, clock: ClockProvider):
        self.config = config
        self.clock = clock
        self._price = config.initial_price
        self._sequence = 0

    def next_tick(self) -> CanonicalMarketTick:
        # Baseline's scenario engine is injected here in the next migration step.
        self._sequence += 1
        observed_at: datetime = self.clock.now()
        return CanonicalMarketTick(
            instrument_id="KOSPI200_VIRTUAL",
            observed_at=observed_at,
            price=self._price,
            volume=Decimal("0"),
            source_sequence=self._sequence,
        )
```
## Contract 정합화
        - 반환 타입을 임의 dict에서 contracts.types.CanonicalMarketTick으로 변경했다.
        - datetime.now() 직접 호출을 제거하고 ClockProvider를 생성자 주입한다.
        - 기존 synthetic price와 sequence 증가 동작은 유지한다.
        - 기존 sequence 의미는 canonical DTO의 source_sequence로 보존한다.
        - VMS 시나리오 엔진 주입 지점은 그대로 남기며, 이번 단계에서 임의의 시장 시나리오 로직을 추가하지 않는다.
        - Paper/Live가 이 Virtual Market을 사용하도록 연결하지 않는다.
[Child Page] reference_vms_market.py
```python
"""Reference VMS boundary package placeholder.

The concrete Runtime source is migrated under this environment-owned package.
Standard contracts remain outside this package.
"""
```
[Child Page] README.md
Reference Exp_Detail_1 VMS Runtime 최소 import closure를 OptionProject Virtual Environment 경계에 이식한다. Standard contracts는 projection adapter를 통해서만 연결한다.
[Child Page] canonical.py
```python
# Compatibility re-export. Canonical DTO ownership is shared.contracts.canonical.
from shared.contracts.canonical import (
    CanonicalAccountSummary, CanonicalAssetType, CanonicalExecutionReport,
    CanonicalMarketTick, CanonicalOptionType, CanonicalOrderCommand, CanonicalOrderSide,
)

__all__ = [
    "CanonicalAccountSummary", "CanonicalAssetType", "CanonicalExecutionReport",
    "CanonicalMarketTick", "CanonicalOptionType", "CanonicalOrderCommand", "CanonicalOrderSide",
]
```
[Child Page] position_manager.py
```python
class PositionManager:
    def __init__(self): self.positions={}
    def update_position(self,symbol,side,qty,price,**kwargs):
        p=self.positions.get(symbol,{"qty":0,"avg_price":0.0,"side":side})
        if p["qty"]==0 or p["side"]==side:
            total=p["qty"]+qty; p["avg_price"]=(p["avg_price"]*p["qty"]+price*qty)/total; p["qty"]=total; p["side"]=side; self.positions[symbol]=p; return 0.0
        close=min(p["qty"],qty); pnl=(price-p["avg_price"])*close*250000.0*(1 if p["side"]=="BUY" else -1); p["qty"]-=close
        if p["qty"]: self.positions[symbol]=p
        else: self.positions.pop(symbol,None)
        return pnl
```
[Child Page] pnl_engine.py
```python
from decimal import Decimal


class PnLEngine:
    def __init__(self):
        self.realized_pnl = Decimal("0")
        self.unrealized_pnl = Decimal("0")

    @staticmethod
    def _decimal(value):
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    def calculate_unrealized(self, positions, current_price, multiplier=Decimal("250000")):
        current = self._decimal(current_price)
        unit_multiplier = self._decimal(multiplier)
        total = Decimal("0")
        for position in positions.values():
            avg_price = self._decimal(position["avg_price"])
            quantity = self._decimal(position["qty"])
            side = str(position["side"])
            if side == "BUY":
                price_delta = current - avg_price
            elif side == "SELL":
                price_delta = avg_price - current
            else:
                raise ValueError("PNL_POSITION_SIDE_INVALID")
            total += price_delta * quantity * unit_multiplier
        self.unrealized_pnl = total
        return total

    def add_realized(self, amount):
        self.realized_pnl += self._decimal(amount)
        return self.realized_pnl
```
[Child Page] margin_engine.py
```python
from decimal import Decimal

MULTIPLIER = Decimal("250000")


class MarginEngine:
    def __init__(self, initial_capital=25000000.0):
        self.initial_capital = Decimal(str(initial_capital))

    @staticmethod
    def _decimal(value):
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    def calculate_order_margin(self, command):
        return self._decimal(command.price) * self._decimal(command.qty) * MULTIPLIER

    def calculate_used_margin(self, positions, multiplier=MULTIPLIER):
        unit_multiplier = self._decimal(multiplier)
        total = Decimal("0")
        for position in positions.values():
            total += (
                self._decimal(position["avg_price"])
                * self._decimal(position["qty"])
                * unit_multiplier
            )
        return total

    def calculate_free_margin(self, total_equity, used_margin):
        return max(Decimal("0"), self._decimal(total_equity) - self._decimal(used_margin))
```
[Child Page] ledger_engine.py
```python
from decimal import Decimal


class LedgerEngine:
    def __init__(self):
        self.transactions = []

    @staticmethod
    def _decimal(value):
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    def record_settlement(self, settlement_type, realized_pnl, unrealized_pnl, balance_after, **kwargs):
        row = {
            "type": "SETTLEMENT",
            "settlement_type": settlement_type,
            "realized_pnl": self._decimal(realized_pnl),
            "unrealized_pnl": self._decimal(unrealized_pnl),
            "balance_after": self._decimal(balance_after),
        }
        self.transactions.append(row)
        return row
```
[Child Page] paper_account.py
```python
from datetime import datetime
from decimal import Decimal
from environments.virtual.authoritative_vssf.position_manager import PositionManager
from environments.virtual.authoritative_vssf.pnl_engine import PnLEngine
from environments.virtual.authoritative_vssf.margin_engine import MarginEngine
from environments.virtual.authoritative_vssf.ledger_engine import LedgerEngine
from shared.contracts.canonical import CanonicalAccountSummary

class PaperTradingAccount:
 def __init__(self,initial_capital=25000000.0):
  capital=Decimal(str(initial_capital)); self.balance=capital; self.realized_pnl=Decimal("0"); self.unrealized_pnl=Decimal("0"); self.position_mgr=PositionManager(); self.pnl_engine=PnLEngine(); self.margin_engine=MarginEngine(initial_capital); self.ledger_engine=LedgerEngine(); self.free_margin=capital; self.used_margin=Decimal("0")
 @property
 def positions(self): return self.position_mgr.positions
 def get_canonical_summary(self):
  total=self.balance+self.realized_pnl+self.unrealized_pnl
  return CanonicalAccountSummary("ACC-VSSF-001",total,self.realized_pnl,self.unrealized_pnl,self.used_margin,self.free_margin,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),positions={k:dict(v) for k,v in self.positions.items()})
 def update_tick_price(self,price):
  self.unrealized_pnl=self.pnl_engine.calculate_unrealized(self.positions,price)
  self.used_margin=self.margin_engine.calculate_used_margin(self.positions)
  equity=self.balance+self.realized_pnl+self.unrealized_pnl
  self.free_margin=self.margin_engine.calculate_free_margin(equity,self.used_margin)
 def apply_execution(self,rep):
  pnl=self.position_mgr.update_position(rep.symbol,rep.side.value if hasattr(rep.side,'value') else str(rep.side),rep.executed_qty,rep.executed_price); self.pnl_engine.add_realized(pnl); self.realized_pnl=self.pnl_engine.realized_pnl; self.balance-=Decimal(str(rep.fee)); self.ledger_engine.transactions.append({"exec_id":rep.exec_id})
```
[Child Page] order_book.py
```python
class OrderBook:
 def __init__(self): self.bid=0.0; self.ask=0.0; self.orders={}
 def update_bid_ask(self,bid,ask): self.bid=float(bid); self.ask=float(ask)
 def match_order(self,command): return self.ask if str(getattr(command.side,'value',command.side))=='BUY' else self.bid
 def cancel_order(self,client_order_id): return self.orders.pop(client_order_id,None) is not None
```
[Child Page] execution_engine.py
```python
from datetime import datetime
from environments.virtual.authoritative_vssf.canonical import CanonicalExecutionReport
class ExecutionEngine:
 def __init__(self): self.reports=[]; self._seq=0
 def execute_order(self,command,price,qty):
  self._seq+=1; rep=CanonicalExecutionReport(f"EXEC-{self._seq:06d}",command.client_order_id,command.track_id,command.asset_type,command.side,int(qty),float(price),0.0,0.0,datetime.now().isoformat(),symbol=getattr(command,'symbol','KOSPI200')); self.reports.append(rep); return rep
```
[Child Page] settlement_engine.py
```python
class SettlementEngine:
 def __init__(self,account): self.account=account
 def perform_eod_settlement(self,final_settlement_price):
  self.account.update_tick_price(final_settlement_price); return self.account.ledger_engine.record_settlement("EOD",self.account.realized_pnl,self.account.unrealized_pnl,self.account.balance)
```
[Child Page] reconciliation.py
```python
class AuthoritativeReconciliationEngine:
 def __init__(self,initial_capital=25000000.0,**kwargs): self.initial_capital=initial_capital
 def reconcile_state(self,account_snapshot,execution_history,current_positions):
  return {"ok":True,"execution_count":len(execution_history),"position_count":len(current_positions),"discrepancies":[]}
```
[Child Page] state_recovery.py
```python
from copy import deepcopy
class StateRecoveryEngine:
 def __init__(self,account): self.account=account
 def create_snapshot(self,sequence_id,metrics=None): return {"sequence_id":sequence_id,"balance":self.account.balance,"positions":deepcopy(self.account.positions),"metrics":dict(metrics or {})}
 def restore_from_snapshot(self,snapshot,target_metrics=None):
  self.account.balance=snapshot["balance"]; self.account.positions.clear(); self.account.positions.update(deepcopy(snapshot["positions"]));
  if target_metrics is not None: target_metrics.update(snapshot.get("metrics",{})); return True
  return True
```
[Child Page] firm_runtime.py
```python
from environments.virtual.authoritative_vssf.canonical import CanonicalMarketTick
from environments.virtual.authoritative_vssf.paper_account import PaperTradingAccount
from environments.virtual.authoritative_vssf.execution_engine import ExecutionEngine
from environments.virtual.authoritative_vssf.order_book import OrderBook
from environments.virtual.authoritative_vssf.reconciliation import AuthoritativeReconciliationEngine
from environments.virtual.authoritative_vssf.settlement_engine import SettlementEngine
from environments.virtual.authoritative_vssf.state_recovery import StateRecoveryEngine
class VirtualSecuritiesFirmRuntime:
 def __init__(self,initial_capital=25000000.0):
  self.account=PaperTradingAccount(initial_capital); self.execution_engine=ExecutionEngine(); self.order_book=OrderBook(); self.reconciliation_engine=AuthoritativeReconciliationEngine(initial_capital); self.settlement_engine=SettlementEngine(self.account); self.recovery_engine=StateRecoveryEngine(self.account); self.margin_engine=self.account.margin_engine; self.metrics={"market_ticks":0,"order_commands":0,"executions_issued":0,"settlement_runs":0}
 @property
 def orderbook(self): return self.order_book
 def process_market_data(self,tick): self.metrics["market_ticks"]+=1; self.order_book.update_bid_ask(tick.bid_price,tick.ask_price); self.account.update_tick_price(tick.underlying_price)
 def process_order(self,command):
  self.metrics["order_commands"]+=1
  if self.account.free_margin < self.margin_engine.calculate_order_margin(command): return None
  price=self.order_book.match_order(command)
  if price<=0: return None
  rep=self.execution_engine.execute_order(command,price,command.qty); self.account.apply_execution(rep); self.account.update_tick_price(price); self.metrics["executions_issued"]+=1; return rep
 def run_settlement(self,final_settlement_price=None): self.metrics["settlement_runs"]+=1; return self.settlement_engine.perform_eod_settlement(final_settlement_price or 350.0)
 def get_account_snapshot(self): return self.account.get_canonical_summary()
 def run_reconciliation(self): return self.reconciliation_engine.reconcile_state(self.get_account_snapshot(),self.execution_engine.reports,self.account.positions)
```
[Child Page] README.md
Reference VSSF authoritative runtime의 최소 import closure를 OptionProject 내부 경계로 materialize한다. 기존 Standard↔Reference Adapter는 유지하며 Runtime 내부 compatibility DTO는 별도 보존한다. 본 단계 구현은 실제 Runtime lifecycle에 필요한 최소 public interface를 우선 이식한 것이다.
[Child Page] simulator_runtime.py
```python
"""Reference Virtual Market Simulator Runtime.

Preserves the Reference scenario/replay lifecycle while allowing the scenario
configuration path to be supplied explicitly by OptionProject composition.
"""
from __future__ import annotations

import random
from typing import Any, Dict, Generator, Iterable, Optional

from environments.virtual.market.reference_vms_market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.reference_vms_market.config import VirtualBrokerConfig, VirtualBrokerControlInterface
from environments.virtual.market.reference_vms_market.clock_controller import VMSClockController
from environments.virtual.market.reference_vms_market.state_manager import VMSStateManager
from environments.virtual.market.reference_vms_market.replay_engine import HistoricalReplayEngine
from environments.virtual.market.reference_vms_market.scenario_engine import ScenarioEngine


class VirtualMarketSimulatorRuntime:
    _SPEED_TO_REPLAY = {"SLOW": 1, "NORMAL": 300, "FAST": 1000}

    def __init__(self, config: Optional[VirtualBrokerConfig] = None, *, scenario_config_path: str | None = None) -> None:
        self.config = config or VirtualBrokerConfig()
        self.control = VirtualBrokerControlInterface(config=self.config)
        self.clock = VMSClockController()
        self.state_mgr = VMSStateManager()
        self.scenario = ScenarioEngine(config_path=scenario_config_path)
        self.replay = HistoricalReplayEngine()
        self._price = 350.0
        self._initial_price = 350.0
        self._volume = 10
        self._volatility_ratio = 1.0
        self._market_regime = "NORMAL"
        self._running = True
        self._tick_speed = "NORMAL"
        self._stress_type: Optional[str] = None
        self._pending_gap_pct = 0.0
        self._pending_shock_delta = 0.0
        self._rng = random.Random(42)
        self._scenario_step_index = 0

    def set_scenario(self, scenario: str) -> Dict[str, Any]:
        self.scenario.set_scenario(scenario)
        return self.get_control_state()

    def load_replay(self, ticks: Iterable[ReferenceCanonicalMarketTick]) -> Dict[str, Any]:
        self.replay.load(ticks)
        self.replay.reset()
        return self.get_control_state()

    def clear_replay(self) -> Dict[str, Any]:
        self.replay.clear()
        return self.get_control_state()

    def set_running(self, running: bool) -> Dict[str, Any]:
        self._running = bool(running)
        return self.get_control_state()

    def set_tick_speed(self, speed: str) -> Dict[str, Any]:
        if speed not in self._SPEED_TO_REPLAY:
            raise ValueError(f"unsupported tick speed: {speed}")
        self._tick_speed = speed
        self.config.replay_speed = self._SPEED_TO_REPLAY[speed]
        return self.get_control_state()

    def get_control_state(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "source": "REPLAY" if self.replay.active else "SCENARIO",
            "scenario": self.scenario.state(),
            "replay": {"active": self.replay.active, "cursor": self.replay.cursor, "exhausted": self.replay.exhausted},
            "tick_speed": self._tick_speed,
            "config": self.control.get_config(),
        }

    def _price_delta(self, scenario_drift: float = 0.0, scenario_volatility: float = 1.0) -> float:
        scale = self._volatility_ratio * scenario_volatility
        return self._rng.uniform(-0.35, 0.35) * scale + scenario_drift

    def _next_market_tick(self, tick_index: int = 0, ticks_per_day: int = 500) -> ReferenceCanonicalMarketTick:
        adjustment = self.scenario.next_adjustment(tick_index, ticks_per_day)
        gap_pct = self._pending_gap_pct or adjustment.gap_pct
        if gap_pct:
            self._price = max(100.0, round(self._price * (1.0 + gap_pct), 2))
            self._pending_gap_pct = 0.0
        delta = self._price_delta(adjustment.drift, adjustment.volatility_multiplier) + adjustment.shock_delta
        self._price = max(100.0, round(self._price + delta, 2))
        spread = max(0.05, min(1.0, float(self.config.base_spread)))
        bid = round(self._price - spread / 2.0, 2)
        ask = round(bid + spread, 2)
        seq = self.state_mgr.next_sequence()
        timestamp = self.clock.get_time_str()
        self.clock.advance_tick(500)
        return ReferenceCanonicalMarketTick(timestamp=timestamp, underlying_price=self._price, strike_price=round(self._price / 2.5) * 2.5, option_type="CALL", bid_price=bid, ask_price=ask, last_price=self._price, volume=self._volume, seq_id=seq)

    def step(self) -> Dict[str, Any]:
        tick = self.replay.next_tick() if self.replay.active else self._next_market_tick(self._scenario_step_index, 500)
        if tick is None:
            raise StopIteration("replay exhausted")
        if not self.replay.active:
            self._scenario_step_index += 1
        return {"timestamp": tick.timestamp, "price": tick.underlying_price, "bid": tick.bid_price, "ask": tick.ask_price, "volume": tick.volume, "seq_id": tick.seq_id}

    def generate_tick_stream(self, total_days: int = 1250, ticks_per_day: int = 500) -> Generator[ReferenceCanonicalMarketTick, None, None]:
        for tick_index in range(total_days * ticks_per_day):
            if not self._running:
                return
            if self.replay.active:
                tick = self.replay.next_tick()
                if tick is None:
                    return
                yield tick
            else:
                yield self._next_market_tick(tick_index, ticks_per_day)
```
[Child Page] canonical.py
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceCanonicalMarketTick:
    timestamp: str
    underlying_price: float
    strike_price: float = 0.0
    option_type: str = "CALL"
    bid_price: float = 0.0
    ask_price: float = 0.0
    last_price: float = 0.0
    volume: int = 0
    seq_id: int = 0
    expiry: str = ""
    symbol: str = ""
```
Reference VMS DTO를 OptionProject 표준 DTO와 분리해 보존한다.
[Child Page] clock_controller.py
```python
from datetime import datetime, timedelta
from typing import Optional


class VMSClockController:
    def __init__(self, start_time: Optional[datetime] = None):
        self.current_time = start_time or datetime(2026, 8, 23, 9, 0, 0)

    def advance_tick(self, milliseconds: int = 500) -> datetime:
        self.current_time += timedelta(milliseconds=milliseconds)
        return self.current_time

    def get_time_str(self) -> str:
        return self.current_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
```
[Child Page] state_manager.py
```python
class VMSStateManager:
    def __init__(self):
        self.sequence_id = 0
        self.active_regime = "NORMAL"

    def next_sequence(self) -> int:
        self.sequence_id += 1
        return self.sequence_id

    def set_regime(self, regime: str) -> None:
        self.active_regime = regime
```
[Child Page] config.py
```python
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class VirtualBrokerConfig:
    replay_speed: int = 1
    slippage_multiplier: float = 1.0
    fee_rate_multiplier: float = 1.0
    volatility_scale: float = 1.0
    scenario_name: str = "COVID_PANIC_2020"
    gap_pct: float = 0.0
    base_spread: float = 0.05
    latency_ms: int = 50

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


class VirtualBrokerControlInterface:
    def __init__(self, config: Optional[VirtualBrokerConfig] = None) -> None:
        self.config = config or VirtualBrokerConfig()

    def get_config(self) -> Dict[str, Any]:
        return self.config.to_dict()
```
[Child Page] replay_engine.py
```python
from collections.abc import Iterable, Iterator
from typing import List, Optional
from environments.virtual.market.reference_vms_market.canonical import ReferenceCanonicalMarketTick


class HistoricalReplayEngine:
    def __init__(self, ticks: Optional[Iterable[ReferenceCanonicalMarketTick]] = None) -> None:
        self._ticks: List[ReferenceCanonicalMarketTick] = list(ticks or [])
        self._cursor = 0

    @property
    def active(self) -> bool:
        return bool(self._ticks)

    @property
    def exhausted(self) -> bool:
        return self._cursor >= len(self._ticks)

    @property
    def cursor(self) -> int:
        return self._cursor

    def load(self, ticks: Iterable[ReferenceCanonicalMarketTick]) -> None:
        self._ticks = list(ticks)
        self._cursor = 0

    def clear(self) -> None:
        self._ticks = []
        self._cursor = 0

    def reset(self) -> None:
        self._cursor = 0

    def next_tick(self) -> Optional[ReferenceCanonicalMarketTick]:
        if self.exhausted:
            return None
        tick = self._ticks[self._cursor]
        self._cursor += 1
        return tick
```
[Child Page] scenario_engine.py
```python
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


@dataclass(frozen=True)
class ScenarioAdjustment:
    volatility_multiplier: float = 1.0
    drift: float = 0.0
    gap_pct: float = 0.0
    shock_delta: float = 0.0


class ScenarioEngine:
    def __init__(self, config_path: Optional[str] = None, seed: int = 42) -> None:
        self.config_path = Path(config_path or "config/market_scenarios.yaml")
        self.seed = seed
        self._rng = random.Random(seed)
        self._scenarios: Dict[str, Dict[str, Any]] = {}
        self._active_name = ""
        self._load()

    def _load(self) -> None:
        with self.config_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        scenarios = payload.get("scenarios") or {}
        if not isinstance(scenarios, dict) or not scenarios:
            raise ValueError("market_scenarios.yaml must define scenarios")
        self._scenarios = {str(name): dict(value or {}) for name, value in scenarios.items()}
        self.set_scenario(str(payload.get("active_scenario") or next(iter(self._scenarios))))

    def set_scenario(self, name: str) -> None:
        if name not in self._scenarios:
            raise ValueError(f"unsupported scenario: {name}")
        self._active_name = name
        self._rng = random.Random(self.seed)

    def next_adjustment(self, tick_index: int, ticks_per_day: int) -> ScenarioAdjustment:
        cfg = self._scenarios[self._active_name]
        drift_range = cfg.get("trend_drift_range", [-0.03, 0.03])
        gap_range = cfg.get("gap_magnitude_percent", [0.0, 0.0])
        shock_range = cfg.get("biweekly_shock_range", [0.0, 0.0])
        interval_days = max(1, int(cfg.get("shock_interval_days", 999999)))
        drift = self._rng.uniform(float(drift_range[0]), float(drift_range[1]))
        gap_pct = shock_delta = 0.0
        interval_ticks = max(1, interval_days * max(1, ticks_per_day))
        if tick_index > 0 and tick_index % interval_ticks == 0:
            magnitude = self._rng.uniform(float(shock_range[0]), float(shock_range[1]))
            direction = -1.0 if self._rng.random() < 0.5 else 1.0
            shock_delta = magnitude * direction
            gap_pct = self._rng.uniform(float(gap_range[0]), float(gap_range[1])) / 100.0 * direction
        return ScenarioAdjustment(max(0.01, float(cfg.get("base_volatility", 1.0))), drift, gap_pct, shock_delta)

    def state(self) -> Dict[str, Any]:
        return {"active_scenario": self._active_name, "available_scenarios": list(self._scenarios)}
```
[Child Page] market_scenarios.yaml
```yaml
active_scenario: HIGH_VOLATILITY
scenarios:
  CALM:
    base_volatility: 1.0
    biweekly_shock_range: [4.0, 8.0]
    gap_magnitude_percent: [0.1, 0.5]
    shock_interval_days: 12
    trend_drift_range: [-0.03, 0.03]
  HIGH_VOLATILITY:
    base_volatility: 2.85
    biweekly_shock_range: [15.0, 25.0]
    gap_magnitude_percent: [1.2, 2.5]
    shock_interval_days: 3
    trend_drift_range: [-0.35, 0.35]
```

[Child Page] broker
[Child Page] virtual_broker.py
```python
from contracts.broker import BrokerAdapter
from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine


class VirtualBroker(BrokerAdapter):
    """VSSF-derived broker boundary; no KIS/Paper/Live dependency."""

    def __init__(self, execution_engine: VirtualExecutionEngine):
        self.execution_engine = execution_engine

    def submit(self, command: BrokerOrderCommand) -> ExecutionReport:
        return self.execution_engine.execute(command)

    def cancel(self, order_id: str) -> ExecutionReport:
        return self.execution_engine.cancel(order_id)

    def query(self, order_id: str) -> ExecutionReport | None:
        return self.execution_engine.query(order_id)
```
## Contract 정합화
        - BrokerAdapter 표준 Protocol을 구현한다.
        - 입력은 canonical BrokerOrderCommand로 제한한다.
        - 실행 결과는 canonical ExecutionReport로 반환한다.
        - Virtual Broker가 KIS/Paper/Live API를 직접 참조하지 않는다.
        - 실제 VSSF 주문·margin·ledger 정책은 이 adapter 경계 아래의 Virtual Execution/VSSF migration 대상으로 보존한다.

[Child Page] account
[Child Page] virtual_account.py
```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from contracts.account import AccountProvider
from contracts.types import AccountSnapshot, DataQuality
from environments.virtual.clock import ClockProvider


@dataclass
class VirtualAccount(AccountProvider):
    cash: Decimal
    margin_used: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    clock: ClockProvider | None = None

    def available_cash(self) -> Decimal:
        return self.cash - self.margin_used

    def snapshot(self) -> AccountSnapshot:
        if self.clock is None:
            raise RuntimeError("VirtualAccount.snapshot requires an injected ClockProvider")
        return AccountSnapshot(
            as_of=self.clock.now(),
            balances={
                "cash": self.cash,
                "margin_used": self.margin_used,
                "realized_pnl": self.realized_pnl,
                "available_cash": self.available_cash(),
            },
            freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="virtual_account_state",
            ),
        )
```
## Standard Contract 정합화
        - 기존 cash / margin_used / realized_pnl / available_cash() 기능은 유지한다.
        - AccountProvider.snapshot()을 구현하여 Virtual Account의 내부 상태를 canonical AccountSnapshot으로 노출한다.
        - AccountSnapshot.as_of는 Virtual Clock에서 취득한다. 시스템 시간을 직접 호출하지 않는다.
        - 기존 생성 코드와의 호환성을 위해 clock은 optional로 두되, snapshot 시점에는 반드시 주입된 ClockProvider가 있어야 한다.
        - balances에는 기존 계정 상태에서 이미 존재하는 값만 매핑하며 통화 단위나 수수료/증거금 계산 규칙을 새로 발명하지 않는다.
        - 현재 VSSF 계정의 실제 margin/PnL/ledger 정책은 그대로 유지하며 이번 변경에서 재정의하지 않는다.
[Child Page] vssf_account_snapshot_adapter.py
```python
from datetime import datetime
from decimal import Decimal
from typing import Any

from contracts.account import AccountProvider
from contracts.types import AccountSnapshot, DataQuality


class VSSFAccountSnapshotAdapter(AccountProvider):
    """Read-only projection of VSSF authoritative account state."""

    def __init__(self, account_source: Any):
        self._account_source = account_source

    def snapshot(self) -> AccountSnapshot:
        getter = getattr(self._account_source, "get_canonical_summary", None)
        if not callable(getter):
            raise TypeError("VSSF_ACCOUNT_SOURCE_REQUIRED")

        summary = getter()
        required = (
            "total_balance",
            "realized_pnl",
            "unrealized_pnl",
            "used_margin",
            "free_margin",
            "timestamp",
        )
        missing = [name for name in required if not hasattr(summary, name)]
        if missing:
            raise TypeError(f"VSSF_ACCOUNT_FIELDS_REQUIRED: {','.join(missing)}")

        try:
            as_of = datetime.strptime(str(summary.timestamp), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError) as exc:
            raise TypeError("VSSF_ACCOUNT_TIMESTAMP_INVALID") from exc

        try:
            balances = {
                "cash": Decimal(str(summary.total_balance)),
                "margin_used": Decimal(str(summary.used_margin)),
                "realized_pnl": Decimal(str(summary.realized_pnl)),
                "available_cash": Decimal(str(summary.free_margin)),
                "unrealized_pnl": Decimal(str(summary.unrealized_pnl)),
            }
        except Exception as exc:
            raise TypeError("VSSF_ACCOUNT_BALANCE_INVALID") from exc

        return AccountSnapshot(
            as_of=as_of,
            balances=balances,
            freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="vssf_authoritative_account_summary",
            ),
        )
```
## 경계
        - VSSF PaperTradingAccount.get_canonical_summary()를 authoritative source로 사용한다.
        - total_balance → cash, used_margin → margin_used, free_margin → available_cash, realized_pnl → realized_pnl, unrealized_pnl → unrealized_pnl로 기존 실제 상태를 그대로 projection한다.
        - Account/PnL/Margin/Ledger 계산이나 mutation은 수행하지 않는다.
        - VSSF summary의 timestamp를 AccountSnapshot.as_of로 변환하며, 변환 실패 시 현재시간으로 대체하지 않고 fail-closed 한다.
        - CanonicalAccountSummary.positions는 Account projection에서 Position 상태로 재해석하지 않는다.
        - VSSF account의 객체 identity와 lifetime을 변경하지 않는다.
[Child Page] test_vssf_account_snapshot_adapter.py
```python
from copy import deepcopy

import pytest

from contracts.types import AccountSnapshot
from environments.virtual.account.vssf_account_snapshot_adapter import (
    VSSFAccountSnapshotAdapter,
)


class StubSummary:
    def __init__(self):
        self.total_balance = 50_000_000.0
        self.realized_pnl = 100_000.0
        self.unrealized_pnl = -25_000.0
        self.used_margin = 1_000_000.0
        self.free_margin = 48_975_000.0
        self.timestamp = "2026-09-05 09:00:00"


class StubAccount:
    def __init__(self):
        self.summary = StubSummary()

    def get_canonical_summary(self):
        return self.summary


def test_authoritative_summary_maps_to_account_snapshot():
    snapshot = VSSFAccountSnapshotAdapter(StubAccount()).snapshot()

    assert isinstance(snapshot, AccountSnapshot)
    assert snapshot.as_of.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-05 09:00:00"
    assert snapshot.balances["cash"] == 50_000_000
    assert snapshot.balances["margin_used"] == 1_000_000
    assert snapshot.balances["realized_pnl"] == 100_000
    assert snapshot.balances["available_cash"] == 48_975_000
    assert snapshot.balances["unrealized_pnl"] == -25_000
    assert snapshot.freshness.is_fresh is True
    assert snapshot.freshness.is_complete is True
    assert snapshot.freshness.source_available is True


def test_invalid_source_fails_closed():
    with pytest.raises(TypeError, match="VSSF_ACCOUNT_SOURCE_REQUIRED"):
        VSSFAccountSnapshotAdapter(object()).snapshot()


def test_missing_field_fails_closed():
    account = StubAccount()
    del account.summary.free_margin

    with pytest.raises(TypeError, match="VSSF_ACCOUNT_FIELDS_REQUIRED"):
        VSSFAccountSnapshotAdapter(account).snapshot()


def test_invalid_timestamp_fails_closed():
    account = StubAccount()
    account.summary.timestamp = "invalid"

    with pytest.raises(TypeError, match="VSSF_ACCOUNT_TIMESTAMP_INVALID"):
        VSSFAccountSnapshotAdapter(account).snapshot()


def test_invalid_balance_fails_closed():
    account = StubAccount()
    account.summary.used_margin = object()

    with pytest.raises(TypeError, match="VSSF_ACCOUNT_BALANCE_INVALID"):
        VSSFAccountSnapshotAdapter(account).snapshot()


def test_source_state_is_not_mutated():
    account = StubAccount()
    before = deepcopy(account.summary.__dict__)

    VSSFAccountSnapshotAdapter(account).snapshot()

    assert account.summary.__dict__ == before
```

[Child Page] position
[Child Page] virtual_position.py
```python
from dataclasses import dataclass
from decimal import Decimal

from contracts.position import PositionProvider
from contracts.types import DataQuality, PositionSnapshot
from environments.virtual.clock import ClockProvider


@dataclass
class VirtualPosition(PositionProvider):
    instrument_id: str
    quantity: int = 0
    average_price: float = 0.0
    clock: ClockProvider | None = None

    def apply_fill(self, quantity: int, price: float) -> None:
        self.quantity += quantity
        self.average_price = price

    def snapshot(self) -> PositionSnapshot:
        if self.clock is None:
            raise RuntimeError("VirtualPosition.snapshot requires an injected ClockProvider")
        return PositionSnapshot(
            as_of=self.clock.now(),
            positions={self.instrument_id: Decimal(str(self.quantity))},
            freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="virtual_position_state",
            ),
        )
```
## Standard Contract 정합화
        - 기존 instrument_id / quantity / average_price / apply_fill() 동작은 유지한다.
        - PositionProvider.snapshot()을 구현하여 Virtual Position 상태를 canonical PositionSnapshot으로 노출한다.
        - PositionSnapshot.as_of는 주입된 Virtual Clock에서 취득한다.
        - 기존 생성 코드의 호환성을 위해 clock은 optional이며, snapshot 호출 시 ClockProvider가 없으면 명시적으로 실패한다.
        - positions에는 현재 VirtualPosition이 실제로 관리하는 단일 instrument_id의 수량만 매핑한다.
        - average_price는 기존 VSSF/VMS 의미를 유지하고 이번 snapshot DTO에서는 수량만 노출한다. 가격/평가금액 계산 규칙을 임의로 추가하지 않는다.
[Child Page] execution_event_identity_adapter.py
```python
from dataclasses import dataclass

from contracts.types import ExecutionReport


@dataclass(frozen=True)
class ExecutionEventIdentity:
    """Environment-owned identity for one canonical execution event."""

    execution_id: str
    client_order_id: str


class ExecutionEventIdentityAdapter:
    """Preserve an Environment execution report's event identity without changing the DTO."""

    def identify(self, report: ExecutionReport) -> ExecutionEventIdentity:
        if not report.execution_id:
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if not report.client_order_id:
            raise ValueError("EXECUTION_EVENT_CLIENT_ORDER_ID_REQUIRED")
        return ExecutionEventIdentity(
            execution_id=report.execution_id,
            client_order_id=report.client_order_id,
        )
```
## Contract
            - Existing ExecutionReport is unchanged.
            - ExecutionReport.execution_id is treated as the Environment-provided execution-event identity when present.
            - No UUID is generated when the report omits an identity.
            - No deduplication state is introduced here; this adapter only validates and preserves identity.
            - client_order_id is retained alongside execution identity so an event cannot be detached from its order context.
[Child Page] test_execution_event_identity_adapter.py
```python
from datetime import datetime
from decimal import Decimal

import pytest

from contracts.types import DataQuality, ExecutionReport
from environments.virtual.execution.execution_event_identity_adapter import (
    ExecutionEventIdentityAdapter,
)


def report(execution_id="EXEC-001", client_order_id="ORD-001"):
    return ExecutionReport(
        client_order_id=client_order_id,
        broker_order_id="BRK-001",
        execution_id=execution_id,
        status="FILLED",
        filled_quantity=3,
        remaining_quantity=0,
        execution_price=Decimal("101.5"),
        execution_timestamp=datetime(2026, 9, 5),
    )


def test_execution_id_is_preserved_without_reconstruction():
    identity = ExecutionEventIdentityAdapter().identify(report())
    assert identity.execution_id == "EXEC-001"
    assert identity.client_order_id == "ORD-001"


def test_missing_execution_id_fails_closed():
    with pytest.raises(ValueError, match="EXECUTION_EVENT_ID_REQUIRED"):
        ExecutionEventIdentityAdapter().identify(report(execution_id=None))


def test_missing_client_order_id_fails_closed():
    with pytest.raises(ValueError, match="EXECUTION_EVENT_CLIENT_ORDER_ID_REQUIRED"):
        ExecutionEventIdentityAdapter().identify(report(client_order_id=""))
```
## Scope
            - Identity preservation only.
            - No Position mutation.
            - No partial-fill accumulation.
            - No deduplication policy.
[Child Page] virtual_position_aggregate.py
```python
from dataclasses import dataclass
from typing import Mapping

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource


@dataclass
class VirtualPositionAggregate(PositionAggregateSource):
    """Environment-owned authoritative side/qty position state.

    This aggregate is deliberately separate from VirtualPosition/PositionSnapshot.
    It receives execution-side information explicitly and never infers side from
    quantity sign or strategy intent.
    """

    instrument_id: str
    side: str | None = None
    qty: int = 0
    avg_price: float | None = None

    def apply_fill(self, *, side: str, quantity: int, price: float | None = None) -> None:
        if not isinstance(side, str) or not side:
            raise ValueError("POSITION_AGGREGATE_SIDE_REQUIRED")
        if side not in {"BUY", "SELL"}:
            raise ValueError("POSITION_AGGREGATE_SIDE_INVALID")
        if not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("POSITION_AGGREGATE_QTY_REQUIRED")

        if self.qty == 0:
            self.side = side
            self.qty = quantity
            self.avg_price = price
            return

        if self.side == side:
            old_qty = self.qty
            self.qty += quantity
            if price is not None:
                if self.avg_price is None:
                    self.avg_price = price
                else:
                    self.avg_price = ((self.avg_price * old_qty) + (price * quantity)) / self.qty
            return

        if quantity < self.qty:
            self.qty -= quantity
            return

        if quantity == self.qty:
            self.side = None
            self.qty = 0
            self.avg_price = None
            return

        self.side = side
        self.qty = quantity - self.qty
        self.avg_price = price

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        if self.qty == 0:
            return {}
        if self.side is None:
            raise RuntimeError("POSITION_AGGREGATE_SIDE_REQUIRED")
        return {
            self.instrument_id: PositionAggregate(
                side=self.side,
                qty=self.qty,
                avg_price=self.avg_price,
            )
        }
```
## 책임 경계
        - 기존 VirtualPosition과 PositionSnapshot은 변경하지 않는다.
        - 체결 갱신 시 side는 BrokerOrderCommand/실행 경로가 명시적으로 공급한다.
        - quantity 부호, strategy action, order purpose로 side를 추론하지 않는다.
        - 동일 방향 체결은 aggregate quantity를 증가시키고 평균 체결가격을 갱신한다.
        - 반대 방향 체결은 기존 quantity를 감소시키며 초과분이 있으면 새로운 side의 잔여 position으로 전환한다.
        - position이 0이면 side도 제거한다.
        - FIFO/lot attribution은 이 최소 aggregate의 책임이 아니다. Risk에는 최종 aggregate side/qty만 공급한다.
        - 실제 Runtime wiring은 별도 단계에서 진행한다.
[Child Page] test_virtual_position_aggregate.py
```python
from core.position.position_aggregate import PositionAggregate
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate


def test_buy_fill_preserves_authoritative_side_and_qty():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=3, price=1.25)

    snapshot = position.snapshot()
    assert snapshot["OPTION_X"] == PositionAggregate(side="BUY", qty=3, avg_price=1.25)


def test_same_side_fill_accumulates_quantity():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=2, price=1.0)
    position.apply_fill(side="BUY", quantity=2, price=2.0)

    aggregate = position.snapshot()["OPTION_X"]
    assert aggregate.side == "BUY"
    assert aggregate.qty == 4
    assert aggregate.avg_price == 1.5


def test_opposite_fill_reduces_existing_position_without_side_inference():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=5, price=1.0)
    position.apply_fill(side="SELL", quantity=2, price=1.2)

    aggregate = position.snapshot()["OPTION_X"]
    assert aggregate.side == "BUY"
    assert aggregate.qty == 3


def test_opposite_fill_beyond_existing_quantity_creates_residual_new_side():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=2, price=1.0)
    position.apply_fill(side="SELL", quantity=5, price=1.2)

    aggregate = position.snapshot()["OPTION_X"]
    assert aggregate.side == "SELL"
    assert aggregate.qty == 3
    assert aggregate.avg_price == 1.2


def test_flat_position_has_no_authoritative_position_entry():
    position = VirtualPositionAggregate("OPTION_X")
    position.apply_fill(side="BUY", quantity=2, price=1.0)
    position.apply_fill(side="SELL", quantity=2, price=1.1)

    assert position.snapshot() == {}


def test_invalid_side_fails_closed():
    position = VirtualPositionAggregate("OPTION_X")
    try:
        position.apply_fill(side="UNKNOWN", quantity=1, price=1.0)
    except ValueError as exc:
        assert str(exc) == "POSITION_AGGREGATE_SIDE_INVALID"
    else:
        raise AssertionError("invalid side must fail closed")
```
## 검증 목적
Environment aggregate의 최소 상태 전이만 검증한다. Risk 정책, FIFO/lot attribution, Broker API 연결은 테스트 대상이 아니다.
[Child Page] virtual_position_fill_adapter.py
```python
from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate


class VirtualPositionFillAdapter:
    """Apply an authoritative execution report to a virtual position aggregate.

    The command supplies side/instrument identity; the report supplies actual
    filled quantity and execution price. This adapter performs validation only
    and delegates position semantics to VirtualPositionAggregate.
    """

    def apply(
        self,
        command: BrokerOrderCommand,
        report: ExecutionReport,
        aggregate: VirtualPositionAggregate,
    ) -> None:
        if command.client_order_id != report.client_order_id:
            raise ValueError("POSITION_FILL_CLIENT_ORDER_ID_MISMATCH")

        if not command.instrument_id:
            raise ValueError("POSITION_FILL_INSTRUMENT_ID_REQUIRED")
        if command.instrument_id != aggregate.instrument_id:
            raise ValueError("POSITION_FILL_INSTRUMENT_ID_MISMATCH")

        if not isinstance(command.side, str) or not command.side:
            raise ValueError("POSITION_FILL_SIDE_REQUIRED")
        if command.side not in {"BUY", "SELL"}:
            raise ValueError("POSITION_FILL_SIDE_INVALID")

        quantity = report.filled_quantity
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValueError("POSITION_FILL_FILLED_QTY_REQUIRED")
        if quantity > command.quantity:
            raise ValueError("POSITION_FILL_FILLED_QTY_EXCEEDS_COMMAND")

        price = report.execution_price
        if price is None:
            raise ValueError("POSITION_FILL_EXECUTION_PRICE_REQUIRED")

        aggregate.apply_fill(
            side=command.side,
            quantity=quantity,
            price=float(price),
        )
```
## 책임 경계
        - ExecutionReport에 side/instrument_id를 추가하지 않는다.
        - side는 BrokerOrderCommand.side에서만 공급한다.
        - Position 갱신 수량은 ExecutionReport.filled_quantity만 사용한다.
        - Position 가격은 ExecutionReport.execution_price만 사용하며 requested_price를 fallback으로 사용하지 않는다.
        - command.client_order_id == report.client_order_id를 확인한다.
        - aggregate의 instrument_id와 command의 instrument_id가 일치해야 한다. Report에 존재하지 않는 instrument_id를 새로 요구하지 않는다.
        - 부분체결은 filled_quantity < command.quantity인 정상 입력으로 허용한다.
        - 중복 체결 방지/deduplication은 이 adapter의 책임으로 새로 정의하지 않는다. 실제 execution 흐름에서 동일 execution report의 반복 가능성을 확인한 뒤 별도 단계에서 결정한다.
        - 실제 반대방향 체결, 평균가격 계산 등 Position semantics는 VirtualPositionAggregate에 위임한다.
[Child Page] test_virtual_position_fill_adapter.py
```python
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter


def command(*, client_order_id="order-1", side="BUY", quantity=10, requested_price=Decimal("100")):
    return BrokerOrderCommand(
        client_order_id=client_order_id,
        instrument_id="OPT-001",
        side=side,
        quantity=quantity,
        order_type="MARKET",
        requested_price=requested_price,
    )


def report(*, client_order_id="order-1", filled_quantity=10, execution_price=Decimal("101")):
    return ExecutionReport(
        client_order_id=client_order_id,
        broker_order_id="broker-1",
        execution_id="exec-1",
        status="FILLED",
        filled_quantity=filled_quantity,
        remaining_quantity=0,
        execution_price=execution_price,
        execution_timestamp=None,
    )


def test_buy_fill_preserves_command_side_and_actual_execution_price():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    VirtualPositionFillAdapter().apply(command(side="BUY"), report(), aggregate)

    assert aggregate.side == "BUY"
    assert aggregate.qty == 10
    assert aggregate.avg_price == 101.0


def test_sell_fill_preserves_command_side():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    VirtualPositionFillAdapter().apply(command(side="SELL"), report(), aggregate)

    assert aggregate.side == "SELL"
    assert aggregate.qty == 10
    assert aggregate.avg_price == 101.0


def test_partial_fill_uses_filled_quantity_not_command_quantity():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    VirtualPositionFillAdapter().apply(
        command(quantity=10),
        report(filled_quantity=4),
        aggregate,
    )

    assert aggregate.qty == 4


def test_client_order_identity_mismatch_fails_closed():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    with pytest.raises(ValueError, match="POSITION_FILL_CLIENT_ORDER_ID_MISMATCH"):
        VirtualPositionFillAdapter().apply(
            command(client_order_id="order-1"),
            report(client_order_id="order-2"),
            aggregate,
        )


def test_missing_or_invalid_side_fails_closed():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    with pytest.raises(ValueError, match="POSITION_FILL_SIDE_REQUIRED"):
        VirtualPositionFillAdapter().apply(command(side=""), report(), aggregate)

    with pytest.raises(ValueError, match="POSITION_FILL_SIDE_INVALID"):
        VirtualPositionFillAdapter().apply(command(side="HOLD"), report(), aggregate)


def test_invalid_filled_quantity_fails_closed():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    for quantity in (0, -1, True):
        with pytest.raises(ValueError, match="POSITION_FILL_FILLED_QTY_REQUIRED"):
            VirtualPositionFillAdapter().apply(
                command(), report(filled_quantity=quantity), aggregate
            )


def test_filled_quantity_cannot_exceed_command_quantity():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    with pytest.raises(ValueError, match="POSITION_FILL_FILLED_QTY_EXCEEDS_COMMAND"):
        VirtualPositionFillAdapter().apply(
            command(quantity=5),
            report(filled_quantity=6),
            aggregate,
        )


def test_missing_execution_price_fails_closed():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-001")

    with pytest.raises(ValueError, match="POSITION_FILL_EXECUTION_PRICE_REQUIRED"):
        VirtualPositionFillAdapter().apply(
            command(requested_price=Decimal("100")),
            report(execution_price=None),
            aggregate,
        )


def test_instrument_identity_mismatch_fails_closed():
    aggregate = VirtualPositionAggregate(instrument_id="OPT-002")

    with pytest.raises(ValueError, match="POSITION_FILL_INSTRUMENT_ID_MISMATCH"):
        VirtualPositionFillAdapter().apply(command(), report(), aggregate)
```
## 검증 의도
        - 정상 BUY/SELL 체결에서 command의 side가 그대로 aggregate에 전달되는지 확인한다.
        - 부분체결에서 filled_quantity만 position quantity로 반영되는지 확인한다.
        - requested price가 아니라 실제 execution_price가 평균 체결가격에 사용되는지 확인한다.
        - command/report identity mismatch, side 오류, filled quantity 오류, execution price 누락, instrument identity mismatch를 fail-closed로 확인한다.
        - 실제 pytest 실행은 별도 실행 결과가 없는 한 UNVERIFIED로 유지한다.
[Child Page] virtual_position_fill_adapter.py
```python
from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate


class VirtualPositionFillAdapter:
    """Apply one authoritative execution fill to the virtual position aggregate."""

    def __init__(self, position: VirtualPositionAggregate):
        self.position = position

    def apply(self, command: BrokerOrderCommand, report: ExecutionReport) -> None:
        if command.client_order_id != report.client_order_id:
            raise ValueError("POSITION_FILL_CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self.position.instrument_id:
            raise ValueError("POSITION_FILL_INSTRUMENT_ID_MISMATCH")
        if not command.side or command.side not in {"BUY", "SELL"}:
            raise ValueError("POSITION_FILL_SIDE_REQUIRED")
        if not isinstance(report.filled_quantity, int) or report.filled_quantity <= 0:
            raise ValueError("POSITION_FILL_QTY_REQUIRED")
        if report.execution_price is None:
            raise ValueError("POSITION_FILL_PRICE_REQUIRED")

        self.position.apply_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=float(report.execution_price),
        )
```
        - side는 BrokerOrderCommand에서 명시적으로 공급한다.
        - 체결 수량은 ExecutionReport.filled_quantity만 사용한다.
        - 실제 체결가격은 ExecutionReport.execution_price만 사용한다.
        - Position 의미를 추론하거나 execution_id를 임의로 deduplicate하지 않는다.
[Child Page] test_virtual_position_fill_adapter.py
```python
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter


def command(side="BUY", order_id="o1"):
    return BrokerOrderCommand(
        client_order_id=order_id,
        instrument_id="K200-C-350",
        side=side,
        quantity=10,
        order_type="LIMIT",
    )


def report(order_id="o1", qty=3, price=Decimal("101.5")):
    return ExecutionReport(
        client_order_id=order_id,
        broker_order_id="b1",
        execution_id="e1",
        status="PARTIALLY_FILLED",
        filled_quantity=qty,
        remaining_quantity=7,
        execution_price=price,
        execution_timestamp=None,
    )


def test_buy_and_sell_side_are_preserved():
    p = VirtualPositionAggregate("K200-C-350")
    a = VirtualPositionFillAdapter(p)
    a.apply(command("BUY"), report())
    assert p.snapshot()["K200-C-350"].side == "BUY"
    assert p.snapshot()["K200-C-350"].qty == 3

    p2 = VirtualPositionAggregate("K200-C-350")
    a2 = VirtualPositionFillAdapter(p2)
    a2.apply(command("SELL"), report())
    assert p2.snapshot()["K200-C-350"].side == "SELL"


def test_identity_mismatch_fails_closed():
    p = VirtualPositionAggregate("K200-C-350")
    with pytest.raises(ValueError, match="POSITION_FILL_CLIENT_ORDER_ID_MISMATCH"):
        VirtualPositionFillAdapter(p).apply(command(order_id="o1"), report(order_id="o2"))


def test_missing_execution_price_fails_closed():
    p = VirtualPositionAggregate("K200-C-350")
    with pytest.raises(ValueError, match="POSITION_FILL_PRICE_REQUIRED"):
        VirtualPositionFillAdapter(p).apply(command(), report(price=None))
```
        - 정상 BUY/SELL, 부분체결, identity mismatch, execution price 누락을 독립 검증한다.
        - 실제 pytest 실행은 별도 검증 단계에서 수행한다.
[Child Page] vssf_position_aggregate_adapter.py
```python
from collections.abc import Mapping
from typing import Any

from core.position.position_aggregate import PositionAggregate, PositionAggregateSource


class VSSFPositionAggregateAdapter(PositionAggregateSource):
    """Read-only projection of VSSF authoritative positions into the Standard contract."""

    def __init__(self, position_source: Any):
        self._position_source = position_source

    def snapshot(self) -> Mapping[str, PositionAggregate]:
        positions = getattr(self._position_source, "positions", None)
        if not isinstance(positions, Mapping):
            raise TypeError("VSSF_POSITION_SOURCE_REQUIRED")

        projected: dict[str, PositionAggregate] = {}
        for instrument_key, state in positions.items():
            if not isinstance(instrument_key, str) or not instrument_key:
                raise TypeError("VSSF_POSITION_INSTRUMENT_KEY_REQUIRED")
            if not isinstance(state, Mapping):
                raise TypeError("VSSF_POSITION_STATE_REQUIRED")

            side = state.get("side")
            qty = state.get("qty")
            avg_price = state.get("avg_price")

            if not isinstance(side, str) or side not in {"BUY", "SELL"}:
                raise TypeError("VSSF_POSITION_SIDE_REQUIRED")
            if not isinstance(qty, int) or qty <= 0:
                raise TypeError("VSSF_POSITION_QTY_REQUIRED")
            if avg_price is not None and not isinstance(avg_price, (int, float)):
                raise TypeError("VSSF_POSITION_AVG_PRICE_INVALID")

            projected[instrument_key] = PositionAggregate(
                side=side,
                qty=qty,
                avg_price=float(avg_price) if avg_price is not None else None,
            )

        return projected
```
## 책임 경계
        - 입력은 VSSF authoritative PositionManager.positions를 노출하는 객체의 positions read interface다.
        - symbol -> {qty, avg_price, side}를 Standard immutable PositionAggregate로 투영한다.
        - source mapping과 내부 entry를 수정하지 않는다.
        - FIFO/lot attribution, PnL, 반대방향 체결, Position mutation은 수행하지 않는다.
        - side는 반드시 VSSF state가 명시한 값을 사용하며 quantity 부호로 추론하지 않는다.
        - avg_price는 Standard projection에 보존하지만 Risk Adapter에서 소비하지 않는다.
## Fail-closed
        - positions가 Mapping이 아니면 실패
        - instrument key가 유효하지 않으면 실패
        - position state가 Mapping이 아니면 실패
        - side가 BUY/SELL이 아니면 실패
        - qty가 양의 정수가 아니면 실패
        - avg_price가 존재하면서 숫자가 아니면 실패
## 수명/구성 원칙
현재 단계에서는 Application Composition에 연결하지 않는다. VSSF Runtime의 authoritative mutation은 Account.apply_execution() -> PositionManager.update_position() 경로가 담당하므로, 이 Adapter는 읽기 전용 projection으로만 사용한다.
[Child Page] test_vssf_position_aggregate_adapter.py
```python
from copy import deepcopy

import pytest

from core.position.position_aggregate import PositionAggregate
from environments.virtual.position.vssf_position_aggregate_adapter import (
    VSSFPositionAggregateAdapter,
)


class StubVSSFPositionSource:
    def __init__(self, positions):
        self.positions = positions


def test_buy_sell_qty_and_avg_price_are_preserved():
    source = StubVSSFPositionSource({
        "K200-C-350": {"qty": 3, "avg_price": 101.5, "side": "BUY"},
        "K200-P-350": {"qty": 5, "avg_price": 98.25, "side": "SELL"},
    })

    snapshot = VSSFPositionAggregateAdapter(source).snapshot()

    assert snapshot["K200-C-350"] == PositionAggregate("BUY", 3, 101.5)
    assert snapshot["K200-P-350"] == PositionAggregate("SELL", 5, 98.25)


def test_missing_side_fails_closed():
    source = StubVSSFPositionSource({"K200-C-350": {"qty": 3, "avg_price": 101.5}})

    with pytest.raises(TypeError, match="VSSF_POSITION_SIDE_REQUIRED"):
        VSSFPositionAggregateAdapter(source).snapshot()


def test_invalid_qty_fails_closed():
    source = StubVSSFPositionSource({"K200-C-350": {"qty": 0, "avg_price": 101.5, "side": "BUY"}})

    with pytest.raises(TypeError, match="VSSF_POSITION_QTY_REQUIRED"):
        VSSFPositionAggregateAdapter(source).snapshot()


def test_malformed_mapping_fails_closed():
    source = StubVSSFPositionSource({"K200-C-350": ["BUY", 3, 101.5]})

    with pytest.raises(TypeError, match="VSSF_POSITION_STATE_REQUIRED"):
        VSSFPositionAggregateAdapter(source).snapshot()


def test_non_mapping_source_fails_closed():
    source = StubVSSFPositionSource([])

    with pytest.raises(TypeError, match="VSSF_POSITION_SOURCE_REQUIRED"):
        VSSFPositionAggregateAdapter(source).snapshot()


def test_source_is_not_mutated():
    positions = {
        "K200-C-350": {"qty": 3, "avg_price": 101.5, "side": "BUY"},
    }
    before = deepcopy(positions)
    source = StubVSSFPositionSource(positions)

    VSSFPositionAggregateAdapter(source).snapshot()

    assert positions == before

```

[Child Page] execution
[Child Page] virtual_execution.py
```python
from typing import Callable, Iterable

from contracts.execution import ExecutionProvider
from contracts.types import BrokerOrderCommand, DataQuality, ExecutionReport


class VirtualExecutionEngine(ExecutionProvider):
    """Virtual execution boundary with an explicit authoritative-fill seam.

    The environment supplies the real VSSF market-match/execution adapter.
    This class does not invent an execution price when that adapter is absent.
    """

    def __init__(
        self,
        position,
        account,
        *,
        authoritative_execute: Callable[[BrokerOrderCommand], ExecutionReport]
        | None = None,
    ):
        self.position = position
        self.account = account
        self._authoritative_execute = authoritative_execute
        self._reports: dict[str, ExecutionReport] = {}

    def execute(self, order: BrokerOrderCommand) -> ExecutionReport:
        if self._authoritative_execute is not None:
            report = self._authoritative_execute(order)
            self._reports[order.client_order_id] = report
            return report

        # A virtual execution cannot be reported as FILLED without the
        # authoritative VSSF matching/execution path. Fail closed instead of
        # manufacturing a synthetic fill report.
        raise RuntimeError("AUTHORITATIVE_VSSF_EXECUTION_ADAPTER_REQUIRED")

    def cancel(self, client_order_id: str) -> ExecutionReport:
        report = ExecutionReport(
            client_order_id=client_order_id,
            broker_order_id=client_order_id,
            execution_id=None,
            status="CANCELLED",
            filled_quantity=0,
            remaining_quantity=0,
            execution_price=None,
            execution_timestamp=None,
            source_freshness=DataQuality(
                is_fresh=True,
                is_complete=False,
                source_available=True,
                reason="virtual_execution_cancel_policy",
            ),
        )
        self._reports[client_order_id] = report
        return report

    def query(self, client_order_id: str) -> ExecutionReport | None:
        return self._reports.get(client_order_id)

    def reports(self) -> Iterable[ExecutionReport]:
        return tuple(self._reports.values())

    def query_execution(self, execution_id: str) -> ExecutionReport | None:
        for report in self._reports.values():
            if report.execution_id == execution_id:
                return report
        return None
```
## 이번 단계 정합화
        - 원격 Exp_Detail_1의 실제 VSSF OrderBook.match_order()가 CanonicalOrderCommand.price를 그대로 체결가격으로 쓰지 않고 실제 best_ask/best_bid와 비교하여 matched_price를 산출하는 것을 확인했다.
        - 원격 VSSF ExecutionEngine.execute_order(command, fill_price, fill_qty)는 이 실제 매칭가격을 입력받아 SlippageEngine을 적용하고 CanonicalExecutionReport.executed_price를 확정한다.
        - 따라서 Standard VirtualExecutionEngine에는 임의 가격을 추가하지 않고, 실제 VMS/VSSF adapter를 authoritative_execute로 주입할 수 있는 명시적 경계를 추가했다.
        - adapter가 연결되면 흐름은 Standard BrokerOrderCommand → VSSF OrderBook 실제 matched_price → VSSF ExecutionEngine.execute_order(fill_price, fill_qty) → CanonicalExecutionReport → Standard ExecutionReport가 된다.
        - OrderIntent와 BrokerOrderCommand에는 requested_price를 보존하는 필드를 추가했다. 이는 주문 요청 의미를 전달하기 위한 것이며 실제 체결가격과 동일시하지 않는다.
        - adapter가 없을 때는 FILLED 또는 불완전 체결 보고서를 생성하지 않고 AUTHORITATIVE_VSSF_EXECUTION_ADAPTER_REQUIRED로 fail-closed한다.
        - 실제 VSSF Account/Position/PnL/Margin/Ledger 변경은 authoritative report의 실제 가격/수량/side를 확보한 후 다음 경계에서 연결한다.
        - No.125의 PRICE_MISMATCH 안전 원칙에 따라 주문가격을 체결가격 fallback으로 사용하지 않는다.
## 검증 상태
        - 원격 Exp_Detail_1 shared/contracts/canonical.py 확인: PASS
        - 원격 Exp_Detail_1 VMS HistoricalReplayEngine의 price/bid/ask source 확인: PASS
        - 원격 Exp_Detail_1 VSSF OrderBook.match_order() 확인: PASS
        - 원격 Exp_Detail_1 VSSF ExecutionEngine.execute_order() 확인: PASS
        - 원격 Git branch write: 미수행
        - Python/pytest: 원격 branch 수정 없이 실행 가능한 환경이 없어 미실행
        - 실제 VMS→VSSF→Standard runtime wiring: ConcreteVirtualEnvironmentBuilder에서 VSSFExecutionAdapter.execute를 authoritative_execute로 주입하는 경로가 구성되어 있다.
[Child Page] vssf_execution_adapter.py
```python
from dataclasses import dataclass
from typing import Protocol

from contracts.types import BrokerOrderCommand


class VSSFCommandContextProvider(Protocol):
	"""Standard 주문으로부터 실제 VSSF 주문 생성에 필요한 권위 데이터를 공급한다."""

	def build_command(self, order: BrokerOrderCommand) -> object: ...


class VSSFRuntime(Protocol):
	"""실제 VSSF 전체 주문→Risk→OrderBook→Execution 경로."""

	def process_order(self, command: object) -> object: ...


@dataclass(frozen=True)
class VSSFExecutionAdapter:
	"""Standard BrokerOrderCommand를 실제 VSSF Runtime 경계로 연결한다."""

	command_context: VSSFCommandContextProvider
	vssf_runtime: VSSFRuntime

	def execute(self, order: BrokerOrderCommand) -> object:
		vssf_command = self.command_context.build_command(order)
		return self.vssf_runtime.process_order(vssf_command)
```
## 이번 단계에서 확정된 실제 연결 경계
        - 원격 VirtualSecuritiesFirmRuntime.process_order()가 VSSF의 단일 주문 처리 진입점이다.
        - process_order() 내부에서 Margin/Risk 검증 → OrderBook.match_order() → ExecutionEngine.execute_order() → PaperTradingAccount.apply_execution()까지 연결된다.
        - 따라서 Standard Adapter에서 FillMatcher와 ExecutionEngine을 별도로 호출하여 동일 단계를 중복 실행하지 않는다.
        - Standard BrokerOrderCommand → 실제 VSSF CanonicalOrderCommand 변환은 VSSFCommandContextProvider가 담당한다.
        - 실제 옵션 identity와 가격은 이 provider가 기존 프로그램의 authoritative source에서 가져와야 한다.
## 확인된 Standard 입력의 한계
현재 Standard BrokerOrderCommand는 client_order_id, instrument_id, side, quantity, order_type, broker_symbol, session_id만 가진다.
따라서 price, track_id, asset_type, option_type, strike, expiry를 adapter에서 임의 생성하지 않는다.
특히 다음은 금지한다.
        - Standard 주문가격을 VSSF 체결가격으로 사용하지 않는다.
        - 0.0 또는 임의 가격을 VSSF command에 넣지 않는다.
        - 임의의 옵션 strike/expiry/type을 생성하지 않는다.
        - Standard Contract에 VSSF 전용 필드를 추가하지 않는다.
## 기존 프로그램 보존
        - 기존 PaperBrokerAdapter는 이미 send_order()와 poll_execution_reports()를 분리하고 VSSF Runtime을 호출한다.
        - OMS OrderRouter는 주문 등록/WAL/FSM을 담당하고 Broker 직접 발주는 Orchestrator에 위임한다.
        - 기존 VSSF의 Margin, Position, PnL, Ledger, Reconciliation, Recovery 책임은 VSSF 내부에 그대로 둔다.
        - 9개 전략 및 Legacy Runtime의 동작을 이 adapter 작업 때문에 변경하지 않는다.
## 실제 주문 생성부 추적 결과
원격 Exp_Detail_1에서 실제 CanonicalOrderCommand 생성부를 확인했다.
option_program/runtime/program_runtime.py의 OptionProgramRuntime.process_tick()에서 DecisionArbiter가 승인한 CanonicalStrategySignal을 기반으로 CanonicalOrderCommand를 직접 생성한다.
```plain text
VMS CanonicalMarketTick
  → OptionProgramRuntime.process_tick()
  → Track 1~9 전략 평가
  → CanonicalStrategySignal
  → DecisionArbiter
  → CanonicalOrderCommand 생성
  → RiskGate.admit_order()
  → OrderRouter.register_and_route()
  → TradingSystem.run_loop()
  → Broker.send_order()
  → VSSF Runtime.process_order()
```
실제 command 생성 시 다음 값은 approved_sig에서 공급된다.
        - track_id ← approved_sig.track_id
        - asset_type ← approved_sig.asset_type
        - side ← approved_sig.side
        - qty ← approved_sig.qty
        - price ← approved_sig.price
        - option_type ← approved_sig.option_type
        - strike ← approved_sig.strike
        - tag_id ← approved_sig.tag_id
        - client_order_id ← 현재 tick sequence + track + signal sequence로 생성
따라서 실제 프로그램에는 이미 Standard와 동일 계층의 canonical command가 존재하며, 현재 Paper/Shadow 경로에서는 별도의 VSSF 전용 command 변환 없이 같은 CanonicalOrderCommand가 VSSF Runtime으로 전달된다.
## 실제 VSSF 연결 결과
TradingSystem.run_loop()는 OptionProgramRuntime.process_tick()이 반환한 command를 Broker.send_order(cmd)로 전달한다. PaperBrokerAdapter.poll_execution_reports()는 pending command를 self.vssf.process_order(cmd)로 전달한다.
VSSF process_order()는 다음을 단일 권위 경로로 수행한다.
Margin/Risk → OrderBook.match_order() → matched_price → ExecutionEngine.execute_order() → PaperTradingAccount.apply_execution()
따라서 adapter가 OrderBook이나 ExecutionEngine을 다시 호출하면 기존 프로그램의 체결 경로를 중복하게 된다.
## 현재 Standard Adapter의 결론
현재 VSSFExecutionAdapter는 실제 VSSF 전체 경로를 직접 복제하지 않고 VSSFCommandContextProvider → VSSFRuntime.process_order()라는 경계만 제공하는 것이 맞다.
다만 Standard BrokerOrderCommand에는 실제 OptionProgram command가 보유하는 track_id / asset_type / price / option_type / strike / expiry 등이 없으므로, 이 adapter에 concrete translator를 추가하려면 authoritative context provider의 실제 source를 별도로 연결해야 한다.
다음 concrete 구현에서 임의 가격, 임의 strike/expiry/type, 주문가격을 체결가격으로 사용하는 fallback은 금지한다. 기존 PaperBrokerAdapter → VSSF Runtime 경로와 9개 전략, OMS/WAL/FSM, VSSF Margin/Position/PnL/Ledger/Reconciliation/Recovery를 유지한다.
원격 Exp_Detail_1에는 write하지 않는다.
[Child Page] order_intent_adapter.py
```python
from dataclasses import dataclass

from contracts.types import BrokerOrderCommand, OrderIntent


class OrderIntentMappingError(ValueError):
    """Raised when an OrderIntent cannot be safely translated."""


@dataclass(frozen=True)
class OrderIntentAdapter:
    """Environment boundary: OrderIntent -> BrokerOrderCommand.

    This layer performs validation and environment-neutral field preservation.
    Broker-specific symbol/API conversion belongs to the concrete environment
    adapter, not to Core/OMS.
    """

    def to_broker_command(self, intent: OrderIntent) -> BrokerOrderCommand:
        if not intent.client_order_id:
            raise OrderIntentMappingError("CLIENT_ORDER_ID_REQUIRED")
        if not intent.instrument_id:
            raise OrderIntentMappingError("INSTRUMENT_ID_REQUIRED")
        if intent.quantity <= 0:
            raise OrderIntentMappingError("QUANTITY_REQUIRED")
        if not intent.side:
            raise OrderIntentMappingError("SIDE_REQUIRED")
        if not intent.order_type:
            raise OrderIntentMappingError("ORDER_TYPE_REQUIRED")

        identity = intent.instrument_identity
        if intent.asset_type == "OPTION":
            if identity is None:
                raise OrderIntentMappingError("OPTION_IDENTITY_REQUIRED")
            if not identity.symbol or not identity.expiry:
                raise OrderIntentMappingError("OPTION_SYMBOL_EXPIRY_REQUIRED")
            if identity.option_type is None or identity.strike is None or identity.strike <= 0:
                raise OrderIntentMappingError("OPTION_CONTRACT_FIELDS_REQUIRED")
            if identity.instrument_id != intent.instrument_id:
                raise OrderIntentMappingError("INSTRUMENT_IDENTITY_MISMATCH")

        return BrokerOrderCommand(
            client_order_id=intent.client_order_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            broker_symbol=identity.symbol if identity is not None else None,
            instrument_identity=identity,
            asset_type=intent.asset_type,
            requested_price=intent.requested_price,
            strategy_id=intent.strategy_id,
            order_purpose=intent.order_purpose,
            track_id=intent.track_id,
            tag_id=intent.tag_id,
            group_id=intent.group_id,
            leg_id=intent.leg_id,
        )
```
## 매핑 원칙
        - OrderIntent가 확정한 identity를 다시 추론하거나 legacy default로 보완하지 않는다.
        - instrument_id, side, quantity, order_type, requested price, strategy/provenance metadata를 보존한다.
        - OPTION은 symbol/expiry/option_type/strike와 instrument_id 일치 여부를 매핑 직전에 검증한다.
        - requested_price는 주문 요청 의미이며 실제 체결가격은 ExecutionReport.execution_price로만 표현한다.
        - 실제 VSSF/KIS symbol/API 형식 변환은 구체적인 Environment Adapter의 책임이다.
        - broker command 생성 실패 시 주문을 전송하지 않는다.
[Child Page] test_order_intent_adapter.py
```python
from decimal import Decimal

import pytest

from contracts.types import OptionInstrumentIdentity, OrderIntent
from environments.virtual.execution.order_intent_adapter import (
    OrderIntentAdapter,
    OrderIntentMappingError,
)


def test_option_intent_maps_identity_and_requested_price_without_fabrication():
    identity = OptionInstrumentIdentity(
        instrument_id="OPT-700-C-202609",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal("700"),
    )
    intent = OrderIntent(
        client_order_id="ORD-1",
        instrument_id=identity.instrument_id,
        side="BUY",
        quantity=2,
        intent_type="ENTRY",
        strategy_id="track1",
        instrument_identity=identity,
        asset_type="OPTION",
        requested_price=Decimal("1.25"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        track_id="track1",
        tag_id="tail-defense",
    )

    command = OrderIntentAdapter().to_broker_command(intent)

    assert command.instrument_id == identity.instrument_id
    assert command.instrument_identity == identity
    assert command.broker_symbol == identity.symbol
    assert command.requested_price == Decimal("1.25")
    assert command.order_type == "LIMIT"
    assert command.strategy_id == "track1"
    assert command.track_id == "track1"
    assert command.tag_id == "tail-defense"


def test_option_identity_mismatch_fails_closed():
    identity = OptionInstrumentIdentity(
        instrument_id="OPT-700-C-202609",
        symbol="KOSPI200",
        expiry="202609",
        option_type="CALL",
        strike=Decimal("700"),
    )
    intent = OrderIntent(
        client_order_id="ORD-2",
        instrument_id="OTHER",
        side="BUY",
        quantity=1,
        intent_type="ENTRY",
        instrument_identity=identity,
        asset_type="OPTION",
        order_type="LIMIT",
        order_purpose="ENTRY",
    )

    with pytest.raises(OrderIntentMappingError, match="INSTRUMENT_IDENTITY_MISMATCH"):
        OrderIntentAdapter().to_broker_command(intent)


def test_missing_requested_price_is_allowed_for_market_semantics():
    intent = OrderIntent(
        client_order_id="ORD-3",
        instrument_id="FUT-1",
        side="BUY",
        quantity=1,
        intent_type="ENTRY",
        asset_type="FUTURES",
        requested_price=None,
        order_type="MARKET",
        order_purpose="ENTRY",
    )

    command = OrderIntentAdapter().to_broker_command(intent)
    assert command.requested_price is None
    assert command.order_type == "MARKET"
```
## 검증 기준
        - 확정된 identity가 BrokerOrderCommand까지 보존된다.
        - requested_price와 execution_price의 의미가 분리된다.
        - OPTION의 symbol/expiry/option_type/strike/instrument_id 불일치는 fail-closed 한다.
        - MARKET 주문처럼 요청가격이 없는 경우 None을 보존하며 임의 가격을 만들지 않는다.
        - 실제 Broker/VSSF API 호출은 수행하지 않는다.
[Child Page] execution_event_deduplicator.py
```python
from contracts.types import ExecutionReport
from environments.virtual.execution.execution_event_identity_adapter import (
    ExecutionEventIdentityAdapter,
)


class ExecutionEventDeduplicator:
    """Environment-owned execution-event gate for exactly-once downstream delivery."""

    def __init__(self, identity_adapter: ExecutionEventIdentityAdapter | None = None):
        self._identity_adapter = identity_adapter or ExecutionEventIdentityAdapter()
        self._seen_execution_ids: set[str] = set()

    def accept(self, report: ExecutionReport) -> bool:
        """Return True only for a previously unseen execution identity."""
        identity = self._identity_adapter.identify(report)
        if identity.execution_id in self._seen_execution_ids:
            return False
        self._seen_execution_ids.add(identity.execution_id)
        return True
```
[Child Page] test_execution_event_deduplicator.py
```python
from datetime import datetime
from decimal import Decimal

import pytest

from contracts.types import ExecutionReport
from environments.virtual.execution.execution_event_deduplicator import (
    ExecutionEventDeduplicator,
)


def report(execution_id="EXEC-001", client_order_id="ORD-001"):
    return ExecutionReport(
        client_order_id=client_order_id,
        broker_order_id="BRK-001",
        execution_id=execution_id,
        status="FILLED",
        filled_quantity=3,
        remaining_quantity=0,
        execution_price=Decimal("101.5"),
        execution_timestamp=datetime(2026, 9, 5),
    )


def test_first_execution_event_is_accepted():
    assert ExecutionEventDeduplicator().accept(report()) is True


def test_same_execution_id_is_accepted_only_once():
    gate = ExecutionEventDeduplicator()
    assert gate.accept(report("EXEC-001")) is True
    assert gate.accept(report("EXEC-001", "ORD-002")) is False


def test_distinct_execution_ids_are_independent():
    gate = ExecutionEventDeduplicator()
    assert gate.accept(report("EXEC-001")) is True
    assert gate.accept(report("EXEC-002", "ORD-002")) is True


def test_missing_execution_id_fails_closed():
    with pytest.raises(ValueError, match="EXECUTION_EVENT_ID_REQUIRED"):
        ExecutionEventDeduplicator().accept(report(None))
```
[Child Page] virtual_execution_position_bridge.py
```python
from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter


class VirtualExecutionPositionBridge:
    """Environment-owned bridge from one broker execution to Position settlement."""

    def __init__(self, broker, deduplicator: ExecutionEventDeduplicator, fill_adapter: VirtualPositionFillAdapter):
        self.broker = broker
        self.deduplicator = deduplicator
        self.fill_adapter = fill_adapter

    def submit(self, command: BrokerOrderCommand) -> ExecutionReport:
        report = self.broker.submit(command)
        if self.deduplicator.accept(report):
            self.fill_adapter.apply(command, report)
        return report
```
## 책임
        - 기존 VirtualBroker.submit()을 먼저 호출한다.
        - 반환된 ExecutionReport를 Environment execution-event deduplication 경계에 통과시킨다.
        - 최초 execution event만 VirtualPositionFillAdapter.apply()로 전달한다.
        - 중복 event는 Position에 다시 적용하지 않는다.
        - filled_quantity를 cumulative/delta로 재해석하지 않는다.
        - 기존 VirtualBroker, VirtualExecutionEngine, ExecutionReport 계약은 변경하지 않는다.
## 연결 위치
        - Bridge는 Environment 실행→정산 경계다.
        - 실제 객체 조립은 application/composition이 담당한다.
        - 현재 단계에서는 기존 Runtime/Environment Factory를 변경하지 않고 bridge와 독립 테스트만 유지한다.
        - 다음 단계에서 실제 Virtual Broker 공급 위치를 확인한 뒤 최소 wiring 여부를 결정한다.
[Child Page] test_virtual_execution_position_bridge.py
```python
from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.virtual.execution.virtual_execution_position_bridge import VirtualExecutionPositionBridge
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter


class StubBroker:
    def __init__(self, report):
        self.report = report

    def submit(self, command):
        return self.report


def command():
    return BrokerOrderCommand(
        client_order_id="o1", instrument_id="K200-C-350", side="BUY", quantity=3, order_type="LIMIT"
    )


def report(execution_id="e1"):
    return ExecutionReport(
        client_order_id="o1", broker_order_id="b1", execution_id=execution_id,
        status="FILLED", filled_quantity=3, remaining_quantity=0,
        execution_price=Decimal("101"), execution_timestamp=None,
    )


def test_one_execution_is_applied_once():
    position = VirtualPositionAggregate("K200-C-350")
    broker = StubBroker(report())
    bridge = VirtualExecutionPositionBridge(
        broker, ExecutionEventDeduplicator(), VirtualPositionFillAdapter(position)
    )
    bridge.submit(command())
    bridge.submit(command())
    assert position.snapshot()["K200-C-350"].qty == 3


def test_distinct_execution_events_are_each_applied():
    position = VirtualPositionAggregate("K200-C-350")
    broker = StubBroker(report("e1"))
    bridge = VirtualExecutionPositionBridge(
        broker, ExecutionEventDeduplicator(), VirtualPositionFillAdapter(position)
    )
    bridge.submit(command())
    broker.report = report("e2")
    bridge.submit(command())
    assert position.snapshot()["K200-C-350"].qty == 6
```
실제 pytest 실행은 아직 수행하지 않았다.
[Child Page] vssf_command_context_provider.py
```python
from dataclasses import dataclass
from decimal import Decimal

from contracts.types import BrokerOrderCommand
from shared.contracts.canonical import (
    CanonicalAssetType, CanonicalOptionType, CanonicalOrderCommand, CanonicalOrderSide,
)

class VSSFCommandContextError(ValueError):
    """Raised when a Standard order cannot be losslessly converted for VSSF."""

@dataclass(frozen=True)
class CanonicalVSSFCommandContextProvider:
    """Concrete Standard BrokerOrderCommand -> Reference CanonicalOrderCommand adapter."""

    def build_command(self, order: BrokerOrderCommand) -> CanonicalOrderCommand:
        identity = order.instrument_identity
        if not order.client_order_id:
            raise VSSFCommandContextError("CLIENT_ORDER_ID_REQUIRED")
        if not order.track_id:
            raise VSSFCommandContextError("TRACK_ID_REQUIRED")
        if order.quantity <= 0:
            raise VSSFCommandContextError("QUANTITY_REQUIRED")
        if order.requested_price is None:
            raise VSSFCommandContextError("REQUESTED_PRICE_REQUIRED")
        if order.asset_type != CanonicalAssetType.OPTION.value:
            raise VSSFCommandContextError("OPTION_ASSET_TYPE_REQUIRED")
        if order.side not in {CanonicalOrderSide.BUY.value, CanonicalOrderSide.SELL.value}:
            raise VSSFCommandContextError("CANONICAL_SIDE_REQUIRED")
        if identity is None:
            raise VSSFCommandContextError("OPTION_IDENTITY_REQUIRED")
        if identity.instrument_id != order.instrument_id:
            raise VSSFCommandContextError("INSTRUMENT_IDENTITY_MISMATCH")
        if not identity.symbol:
            raise VSSFCommandContextError("OPTION_SYMBOL_REQUIRED")
        if not identity.expiry:
            raise VSSFCommandContextError("OPTION_EXPIRY_REQUIRED")
        if identity.option_type not in {
            CanonicalOptionType.CALL.value, CanonicalOptionType.PUT.value,
        }:
            raise VSSFCommandContextError("CANONICAL_OPTION_TYPE_REQUIRED")
        if identity.strike is None or identity.strike <= Decimal("0"):
            raise VSSFCommandContextError("OPTION_STRIKE_REQUIRED")
        if not order.tag_id:
            raise VSSFCommandContextError("TAG_ID_REQUIRED")

        return CanonicalOrderCommand(
            client_order_id=order.client_order_id,
            track_id=order.track_id,
            asset_type=CanonicalAssetType(order.asset_type),
            side=CanonicalOrderSide(order.side),
            qty=order.quantity,
            price=float(order.requested_price),
            option_type=CanonicalOptionType(identity.option_type),
            strike=float(identity.strike),
            symbol=identity.symbol,
            expiry=identity.expiry,
            tag_id=order.tag_id,
        )
```
## 계약
        - 최신 Reference CanonicalOrderCommand 생성자와 직접 대조했다.
        - Standard 문자열 값은 Reference Enum으로 명시 정규화한다.
        - Decimal 가격/행사가는 Reference DTO의 float 계약에 맞춘다.
        - identity 역조회/synthetic identity 생성은 하지 않는다.
        - 허용되지 않는 side/option_type도 fail-closed한다.
[Child Page] test_vssf_command_context_provider.py
```python
from decimal import Decimal
import pytest

from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from shared.contracts.canonical import (
    CanonicalAssetType, CanonicalOptionType, CanonicalOrderSide,
)
from environments.virtual.execution.vssf_command_context_provider import (
    CanonicalVSSFCommandContextProvider, VSSFCommandContextError,
)

def order() -> BrokerOrderCommand:
    identity = OptionInstrumentIdentity(
        instrument_id="AUTH-OPTION-1", symbol="KOSPI200",
        expiry="202609", option_type="CALL", strike=Decimal("350.0"),
    )
    return BrokerOrderCommand(
        client_order_id="ORD-1", instrument_id=identity.instrument_id,
        side="BUY", quantity=2, order_type="LIMIT",
        instrument_identity=identity, asset_type="OPTION",
        requested_price=Decimal("1.25"), track_id="TRACK-1", tag_id="TAG-1",
    )

def test_build_command_matches_reference_canonical_contract():
    result = CanonicalVSSFCommandContextProvider().build_command(order())
    assert result.client_order_id == "ORD-1"
    assert result.track_id == "TRACK-1"
    assert result.asset_type is CanonicalAssetType.OPTION
    assert result.side is CanonicalOrderSide.BUY
    assert result.qty == 2
    assert result.price == 1.25
    assert result.symbol == "KOSPI200"
    assert result.expiry == "202609"
    assert result.option_type is CanonicalOptionType.CALL
    assert result.strike == 350.0
    assert result.tag_id == "TAG-1"

def test_missing_identity_fails_closed():
    bad = order()
    bad = BrokerOrderCommand(**{**bad.__dict__, "instrument_identity": None})
    with pytest.raises(VSSFCommandContextError, match="OPTION_IDENTITY_REQUIRED"):
        CanonicalVSSFCommandContextProvider().build_command(bad)

def test_instrument_id_mismatch_fails_closed():
    bad = order()
    bad = BrokerOrderCommand(**{**bad.__dict__, "instrument_id": "OTHER"})
    with pytest.raises(VSSFCommandContextError, match="INSTRUMENT_IDENTITY_MISMATCH"):
        CanonicalVSSFCommandContextProvider().build_command(bad)

def test_invalid_reference_enum_values_fail_closed():
    bad_side = BrokerOrderCommand(**{**order().__dict__, "side": "HOLD"})
    with pytest.raises(VSSFCommandContextError, match="CANONICAL_SIDE_REQUIRED"):
        CanonicalVSSFCommandContextProvider().build_command(bad_side)

    bad_identity = OptionInstrumentIdentity(
        instrument_id="AUTH-OPTION-1", symbol="KOSPI200",
        expiry="202609", option_type="OTHER", strike=Decimal("350.0"),
    )
    bad_option_type = BrokerOrderCommand(
        **{**order().__dict__, "instrument_identity": bad_identity}
    )
    with pytest.raises(VSSFCommandContextError, match="CANONICAL_OPTION_TYPE_REQUIRED"):
        CanonicalVSSFCommandContextProvider().build_command(bad_option_type)
```
## 검증 기준
        - 최신 Reference Canonical DTO의 Enum/float 필드까지 정확히 대조한다.
        - identity 누락·instrument_id 불일치·허용되지 않는 enum 값은 모두 fail-closed한다.
        - identity 역조회 없이 Standard에서 이미 보존된 authoritative identity만 사용한다.

[Child Page] README.md
Virtual Trading owns all synthetic market behavior and VSSF-derived broker/account/position/execution behavior.
High-Speed will reuse this bundle and replace only clock/replay/scenario policies.
Paper/Live must not import these implementation modules.
Baseline stress scenarios, margin, PnL, ledger, reconciliation and recovery are migrated incrementally without changing the Standard Core contract.

[Child Page] ENVIRONMENT_BUNDLE.md
## Ownership
    - Market: synthetic VMS-derived source
    - Clock: Virtual clock contract implementation
    - Broker: VSSF-derived virtual broker
    - Account/Position: virtual state
    - Execution: virtual execution policy
    - Reconciliation/Recovery: virtual environment responsibility
## Isolation
Virtual implementation may use synthetic data, but that data must never satisfy Paper/Live external-data evidence.
## Feature preservation
The baseline's stress scenarios, market simulation, VSSF margin/PnL/ledger, reconciliation and recovery are migration targets. They are not replaced with arbitrary simplified business rules.

[Child Page] VIRTUAL_CONTRACT_MAPPING_SOURCE.md
## 목적
Scenario/Replay configuration이 scenario_contract_key → shrn_iscd의 explicit mapping을 authoritative input으로 공급하는 최소 형식을 고정한다.
## 지원 형식
```plain text
contract_mappings:
  - scenario_contract_key: <Scenario/Replay external key>
    shrn_iscd: <existing authoritative OptionMaster short code>
```
또는 loader에 mapping entry 목록을 직접 전달할 수 있다.
## ownership
    - 실제 값의 owner: Scenario/Replay configuration
    - materialization owner: Application Composition Root
    - identity authority: 동일 composition scope의 OptionMaster registry
    - validation: VirtualContractResolver
## 금지
    - symbol/expiry/strike/type 기반 추론
    - 기본 shrn_iscd
    - mapping 자동 생성
    - registry 복제
    - 존재하지 않는 KIS identity 생성
## composition 흐름
Scenario/Replay configuration
→ VirtualContractMappingLoader
→ dict[str, VirtualContractMapping]
→ VirtualCompositionDependencies.contract_mappings
→ VirtualContractResolver
→ authoritative OptionMaster registry validation
## 현재 상태
실제 production/replay mapping 값은 authoritative source가 제공되지 않았으므로 이 문서는 형식만 정의하며 fixture 또는 가짜 shrn_iscd를 포함하지 않는다.