No.125에서 확인한 실제 Runtime의 provenance 소실 지점을 기준으로, 기존 CanonicalStrategySignal의 의미와 현재 주문 경로를 변경하지 않으면서 Strategy의 추가 실행 provenance를 보존하는 최소 전달 구조를 정의한다.

## 실제 확인 결과

program_runtime.py에서 각 Track의 전략 결과 sig를 CanonicalStrategySignal로 field-by-field 변환한다. 현재 변환되는 값은 signal_id, track_id, asset_type, side, qty, price, option_type, strike, tag_id이며, 전략 dictionary에 존재할 수 있는 action, reason, entry_reason, exit_reason, order_purpose, order_type은 Canonical DTO에 전달되지 않는다.

따라서 provenance의 최초 명시적 소실 경계는 다음과 같다.

```plain text
Strategy signal dict
        ↓
program_runtime.py CanonicalStrategySignal 변환
        ↓
CanonicalStrategySignal
```

DecisionArbiter는 이미 생성된 CanonicalStrategySignal을 중재하므로 이 이전 단계에서 사라진 값을 복원할 책임이 없다.

## 최소 보존 구조

기존 Canonical DTO를 즉시 확장하지 않고 별도의 provenance wrapper/intermediate를 사용한다.

```plain text
Strategy
  ↓
CanonicalStrategySignal + ExecutionProvenance
  ↓
StrategySignalEnvelope
  ↓
DecisionArbiter
  ↓
Risk
  ↓
Position Logic
  ↓
ExplicitPositionExecutionIntent
  ↓
OrderIntent
```

## 보존 규칙

- 기존 Canonical field의 의미를 변경하지 않는다.

- Strategy가 실제 명시한 order_purpose만 declared_order_purpose로 보존한다.

- Strategy가 실제 명시한 order_type만 declared_order_type로 보존한다.

- 값이 없으면 None으로 보존한다.

- action, track_id, tag_id, side, Position 방향으로 order_purpose를 추론하지 않는다.

- provenance와 최종 execution intent를 동일 객체/enum으로 취급하지 않는다.

- 기존 LIMIT 실행 호환성 정책은 purpose 결정과 분리한다.

## Wrapper 설계 원칙

StrategySignalEnvelope는 최소한 다음 두 영역을 보존해야 한다.

1. signal: 기존 CanonicalStrategySignal

1. provenance: ExecutionProvenance

Provenance에는 전략별 추가 정보가 존재할 수 있으므로 전략별 metadata를 보존할 수 있어야 한다. 다만 현재 Runtime에서 실제 사용되지 않는 값을 새 의미로 변환해서는 안 된다.

## Runtime 연결 원칙

현재 DecisionArbiter와 CanonicalOrderCommand → RiskGate → OrderRouter 경로는 그대로 유지한다. Wrapper를 실제 Runtime에 연결할 때도 기존 주문 수량, 가격, side, asset 및 주문 ID 생성 규칙을 변경하지 않는다.

특히 order_purpose가 없는 Track의 신호에 대해 ENTRY/EXIT/HEDGE 등의 값을 자동 생성하지 않는다.

## 다음 검증 대상

Track 1~9 각각의 실제 signal dictionary가 제공하는 provenance key를 전수 대조하여 Wrapper가 필요한 최소 필드를 확정한다. 그 결과에 따라 실제 Runtime 변경 여부와 변경 범위를 결정한다.

## 보호 범위

- 원격 Git Exp_Detail_1 변경 없음

- 원격 브랜치 터미널 테스트 없음

- 기존 Strategy action 의미 변경 없음

- legacy OrderRequest 기본값을 승격하지 않음