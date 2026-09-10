# 최종 아키텍처

## 레이어

```plain text
interfaces → application → contracts → core
environment implementations → contracts
infrastructure implementations → contracts
```

## Standard Option Core

Domain Model, Strategy, Signal, Decision, Risk, Position Logic, Order Intent, OMS Core, Contract/DTE Logic, 환경 독립 Runtime Logic.

## Environment Bundle

Market Data, Clock/Time Policy, Broker, Account, Execution, Runtime Policy.

## 데이터 흐름

```plain text
Market Data → Canonical Market State → Strategy → Signal → Decision → Risk → Position → Order Intent → Execution Contract → Environment Adapter
```