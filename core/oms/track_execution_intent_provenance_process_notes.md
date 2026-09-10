## 작업 목적

No.122의 다음 단계 지시에 따라 Exp_Detail_1의 Track 1~9 및 실제 Position 상태를 대조하여 기존 코드에 이미 존재하는 명시적 execution intent/order_purpose가 있는지 확인하고, 새 전략 규칙을 만들지 않는 범위에서 Standard Position Logic으로 보존 가능한 provenance를 판정했다.

## 대조 결과

- Track 1~8의 확인된 전략 신호 구조에는 독립적인 order_purpose 필드가 없다. action, type, qty, price, pricing_mode, tag_id 및 전략별 상태값이 중심이다.

- Track 9의 raw legacy signal에는 명시적인 order_purpose가 실제 존재한다.
    - ADD_INSURANCE: ENTRY
    - REDUCE_INSURANCE: EXIT
    - EARLY_PROFIT_TAKE: EXIT
    - REHEDGE_ENTRY: ENTRY

- 따라서 Track9의 값은 action 이름에서 추론한 값이 아니라 기존 코드가 직접 공급한 명시값이다.

- 그러나 Standard Core Track9에서는 이 purpose가 Signal 객체의 독립 필드로 보존되지 않고 action/reason payload 형태로 전환되어 있으며, CanonicalStrategySignal/CanonicalOrderCommand에도 order_purpose가 없다.

- 실제 PositionManager의 aggregate/order attribution 데이터에는 client_order_id, symbol, side, qty, avg_price 등이 있으나 order_purpose를 저장·결정하지 않는다.

## No.006 기준 판정

No.006의 Market State → Strategy → Signal → Decision → Risk Validation → Position Logic → Order Intent 경계를 유지해야 한다. 따라서 Track9의 기존 명시 purpose를 Position Logic이 새로 추론하는 것이 아니라, 명시적 provenance로 보존하여 Risk 이후 Position Logic에서 검증·최종 공급할 수 있는 전달 계약이 필요하다.

Track1~8은 현재 명시 purpose 공급원이 확인되지 않았으므로 STRATEGY_ENTRY 등의 기본값을 넣거나 action/track/tag/side를 purpose로 변환하지 않는다. purpose가 필요한 실행 Intent에서 근거가 없으면 fail-closed한다.

order_type은 별도 문제이며 기존 VSSF의 LIMIT 실행 호환 정책으로 관리한다. purpose provenance와 혼합하지 않는다.

## 구현 판단

이번 단계에서는 실제 Canonical DTO나 Runtime을 변경하지 않는다. 먼저 다음 최소 계약을 설계한다.

1. 기존 raw signal에 명시 purpose가 있는 경우 그 provenance를 잃지 않는 전달 객체/필드.

1. Risk Validation 이후 Position Logic에서 해당 명시값을 검증하고 ExplicitPositionExecutionIntent로 공급하는 경계.

1. purpose가 없는 Track은 임의 보정하지 않고 OrderIntent 단계에서 실패시키는 조건.

1. 기존 LIMIT 호환 정책은 계속 독립 유지.

## 원격 Git 및 테스트 경계

- 원격 Exp_Detail_1 수정·생성·삭제 없음.

- 원격 브랜치 대상 터미널 테스트 실행 없음.

- GitHub 정적 대조와 Notion 기준 대조만 수행.

## 다음 작업

Track9의 명시 ENTRY/EXIT를 보존할 수 있는 최소 provenance 전달 계약을 Standard Core/Canonical 경계에 설계하고, Track1~8의 미공급 상태를 fail-closed로 유지할 수 있는지 검토한다.