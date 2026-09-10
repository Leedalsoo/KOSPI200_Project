## Current Reference

```plain text
main.py / TradingSystem
  ├─ VirtualMarketSimulatorRuntime
  │      ↓ CanonicalMarketTick
  ├─ OptionProgramRuntime
  │      ├─ Strategy / Sensor / Signal
  │      ├─ Decision / Risk
  │      └─ OMS → CanonicalOrderCommand
  ├─ Broker Adapter
  │      ↓ Ack / ExecutionReport
  ├─ VirtualSecuritiesFirmRuntime
  │      ├─ Account / Position
  │      ├─ Ledger / PnL / Margin
  │      └─ Settlement / Reconciliation
  ├─ WAL / Recovery
  └─ Web UI / WebSocket
```

## Target Migration

```plain text
Control Tower
    ↓
Runtime Controller
    ↓
Environment Factory
    ↓
Environment Bundle
    ├─ Market Data
    ├─ Clock
    ├─ Broker
    ├─ Account
    └─ Execution
    ↓
Standard Contracts
    ↓
Standard Option Core
    ├─ Strategy
    ├─ Signal
    ├─ Decision
    ├─ Risk
    ├─ Position
    └─ OMS
```

기능은 유지하되 현재 main.py의 직접 조립 책임은 Target 구조로 분해한다.