## 1. 고정 실행 방향

Control Tower UI

→ Runtime Controller

→ Environment Hub / Factory

→ Environment Bundle

→ Standard Contracts

→ Standard Option Core

## 2. Standard Option Core

포함:

- Domain Model

- Strategy Framework + 9 Strategies

- Sensor/Signal

- Decision

- Risk

- Position Logic

- Order Intent

- OMS Core

- Option Contract/DTE Domain Logic

- 환경 독립 Runtime Logic

제외:

- KIS API/Auth

- VMS/VSSF 구현체

- UI/WebSocket

- 특정 Clock

- DB/파일/네트워크 저장 구현

- 특정 Environment 상태

규칙: Core는 자신이 High-Speed/Virtual/Paper/Live 중 어디서 실행되는지 알지 못한다.

## 3. Strategy Boundary

Strategy Input = Canonical Market State + Strategy Configuration + Domain Context.

Strategy는 Broker, Account API, KIS, VMS, VSSF, UI를 직접 참조하지 않는다.

Core 내부 흐름:

Market State → Strategy → Signal → Decision → Risk → Position Context → Order Intent

## 4. Environment Bundle

각 Environment는 다음 구현 묶음을 제공한다:

- Market Data

- Clock / Time Policy

- Broker

- Account

- Execution

- Runtime Policy

High-Speed = 독립 Core가 아니라 Virtual Trading의 시장/시간/실행 정책을 가속한 Bundle.

Paper/Live = 동일 Core에 서로 다른 실제 증권사 Adapter Bundle.

## 5. Application Boundary

Runtime Controller:

- Select / Start / Stop / Restart

- lifecycle orchestration

- environment-neutral status

Environment Hub/Factory:

- Environment Bundle 생성

- Contract 구현체 조립

- 환경 등록/선택

Controller는 KIS/VMS/VSSF 구현체를 직접 import하지 않는다.

## 6. UI Boundary

UI는 Runtime Controller Contract만 호출한다.

UI가 직접 접근 금지:

- VMS

- VSSF

- KIS Adapter

- 내부 Broker 객체

UI DTO:

EnvironmentType, LifecycleState, ConnectionState, SafetyState, MarketStatus, PositionSummary, PnLSummary, RiskStatus, Warning.

## 7. Dependency Rule

interfaces → application → contracts → core

environment implementations → contracts

infrastructure implementations → contracts

Core → Environment/UI/Infrastructure import 금지.