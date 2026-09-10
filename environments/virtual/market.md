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