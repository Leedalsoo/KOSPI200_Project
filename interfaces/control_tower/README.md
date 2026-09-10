# Control Tower UI

## 목적

4개 Environment를 하나의 Control Tower에서 선택·조작하되 UI가 Broker/VMS/VSSF/KIS를 직접 호출하지 않는다.

## 단일 제어 경로

```plain text
UI → ControlTowerRuntimeAPI → RuntimeController → EnvironmentHub → EnvironmentBundle → Standard Contracts/Core

Live production assembly: `LiveRuntimeLifecycleCoordinator` is the authoritative technical lifecycle owner. Live Control Tower status uses the same controller through `LiveControlTowerRuntimeAPI`; UI/application lifecycle input is carried by `LiveLifecycleCommand`, and adapter-level async serialization keeps concurrent start/stop/restart requests on one coordinator command sequence.
```

## 표시 범위

- Active Environment / Runtime lifecycle

- Market status 및 stale/freshness

- Account / Position / PnL / Orders

- Risk / Kill Switch

- Permission / Live approval / Credential readiness

- High-Speed speed multiplier / Scenario

- 오류 및 실행 중단 상태

## 기능

- Environment 선택

- Start / Stop / Restart

- 상태 조회

- Safety 상태 조회

- 실행 중인 Environment가 있을 때 이중 실행 방지

## Legacy 보존 원칙

기존 option_program/control 및 web_interface의 기능은 신규 View Model로 이전 가능한 항목을 먼저 매핑한다. 기존 UI는 Phase 14 reference tracing 전까지 삭제하지 않는다.