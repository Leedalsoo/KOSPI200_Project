# 목적

No.123에서 확인된 Track 1~9의 실행 provenance와 현재 Canonical Runtime 사이의 전달 단절을 보존 관점에서 정리한다.

## 정정된 핵심 사실

Track9를 포함한 전략 코드에는 일부 signal에 명시적인 order_purpose/order_type 정보가 존재할 수 있으나, 이것이 모든 Track에 공통된 것은 아니다. 따라서 존재하는 명시값은 보존하고, 존재하지 않는 값은 추론하지 않는다.

## 보존 원칙

- strategy action은 원문 provenance로 보존한다.

- strategy가 명시한 order_purpose가 있으면 별도 declared 값으로 보존한다.

- strategy가 명시한 order_type이 있으면 별도 declared 값으로 보존한다.

- action/track/tag/side/position 방향만으로 purpose를 생성하지 않는다.

- legacy DTO 기본값을 현재 의미로 승격하지 않는다.

- Position Logic에서 explicit execution intent가 공급될 때만 Standard OrderPurpose로 확정한다.

## 다음 전달계약

Strategy → Execution Provenance → Canonical/Intermediate → Risk → Position Logic → Explicit Execution Intent → OrderIntent

여기서 provenance는 관찰·보존 데이터, execution intent는 실행을 위해 명시적으로 결정된 데이터로 분리한다. 이 둘을 하나의 enum으로 합치지 않는다.

## 보호 범위

원격 Exp_Detail_1은 변경하지 않는다. 기존 전략 규칙을 재작성하거나 action을 임의의 ENTRY/EXIT/HEDGE로 변환하지 않는다.

## 다음 단계

실제 DecisionArbiter → CanonicalOrderCommand 생성 지점을 추적하여 provenance가 어느 경계에서 소실되는지 확인하고, 기존 Runtime을 변경하지 않는 최소 전달 지점을 결정한다.