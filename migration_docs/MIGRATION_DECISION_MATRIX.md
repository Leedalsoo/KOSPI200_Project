## REBUILD

- main.py composition

- Environment Hub

- Runtime Controller

- Control Tower boundary

## REFACTOR

- Strategy

- Signal

- Decision

- Risk

- Runtime

- Market Data

- Sensor

## SPLIT

- order_router

- program_runtime

- real_broker_adapter

- option master source/domain

- calendar source/domain

- recorder/replay/report components

## MOVE

- OMS FSM

- WAL

- telemetry

## EXCLUDE FROM NEW RUNTIME

- archive agent instructions

- one-off insertion utilities

- backup remnants

- obsolete compatibility paths

## BLOCKED

- unverified Trading Calendar production source

- any external API path lacking actual response evidence

This matrix governs Phase 5+. No arbitrary whole-folder copy is allowed.

## Phase 14 No.080 이후 Architecture Lock 보정

No.080 최종 제거 판정 결과 현재 Legacy 삭제 확정은 0건이다. 따라서 최종 Architecture Lock은 기존 Legacy 파일을 모두 삭제했다는 의미가 아니라, 신규 표준 구조를 최종 목표/운영 기준선으로 고정하고 Legacy는 기능 대체 증거가 확보될 때까지 보존한다는 의미로 정의한다.

### 고정 Architecture

```plain text
Control Tower UI
    ↓
Runtime Controller
    ↓
Environment Hub / Factory
    ↓
Environment Bundle
 ├── High-Speed Test
 ├── Virtual Trading
 ├── Paper Trading
 └── Live Trading
    ↓
Standard Contracts
    ↓
Standard Option Core
```

### Lock 규칙

1. Core는 Broker/VMS/VSSF/UI에 직접 의존하지 않는다.

1. Strategy는 환경별 API를 직접 호출하거나 주문을 직접 제출하지 않는다.

1. 환경 변경은 Environment Bundle 전체 교체로 처리한다.

1. High-Speed는 Virtual Environment 재사용 + Clock/Replay/Scenario 가속이다.

1. Live는 VSSF를 생성하지 않고 Credential/Safety Gate/Idempotency/Reconciliation/Recovery 경계를 사용한다.

1. 기존 Legacy는 삭제가 아니라 보존·이관 대기 상태로 관리할 수 있다.

1. Legacy 제거는 기능 완전 대체 + reference 0 + 테스트/검증 증거 + 복구 가능성을 모두 만족할 때만 허용한다.

1. KRX Trading Calendar API 미존재로 확인된 항목은 Calendar source→runtime 검증 대상에서 제외한다.

### 검증 한계

현재 원격 branch는 읽기 전용으로 취급하며 수정/생성/삭제하지 않는다. 신규 4환경 전체 실행과 terminal pytest의 직접 검증 증거가 없으므로 이를 PASS로 표시하지 않는다.