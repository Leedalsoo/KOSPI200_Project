## 목적

No.110 다음 단계로 Reference Baseline의 실제 주문 생성 경로를 재대조하여 Standard OrderIntentExecutionInput의 각 필드가 어디에서 authoritative하게 공급되는지 확정한다.

## Reference Baseline 추적 결과

기준 브랜치: Exp_Detail_1

실제 경로:

Track 1~9 → CanonicalStrategySignal → DecisionArbiter → CanonicalOrderCommand → RiskGate → OrderRouter → Environment

### quantity

- 초기 공급원: 각 Strategy 결과의 sig["qty"]

- CanonicalStrategySignal.qty → CanonicalOrderCommand.qty로 전달

- RiskEngine은 승인 단계에서 한도/증거금 조건에 따라 qty를 감소시킬 수 있음

- 따라서 Standard 경계에서는 전략 제안 수량과 Risk/Position 승인 후 실행 수량을 동일한 authoritative source로 취급하면 안 됨

### requested_price

- 초기 공급원: Strategy 결과의 sig["price"]

- 누락 시 Reference Runtime은 tick.last_price fallback을 사용

- 최종 CanonicalOrderCommand.price는 주문 요청가격 의미

- 실제 체결가격은 별도 ExecutionReport에서 생성됨

- Standard 구조에서는 synthetic fallback을 새로 만들지 않고, 실제 가격 공급원이 명시되지 않으면 validation failure 또는 upstream contract gap으로 처리

### asset_type

- Reference Runtime이 Strategy signal의 asset/type에서 OPTION/FUTURES를 분류하여 공급

- Standard OrderIntentExecutionInput.asset_type의 실제 upstream source는 Strategy/Signal domain 분류임

### track_id / tag_id

- track_id: Strategy identity에서 공급

- tag_id: Strategy signal에서 공급하며 RiskEngine의 특수 정책 식별에도 사용

- provenance로 보존 가능

### order_type

- Reference CanonicalOrderCommand에는 독립 필드가 없음

- 따라서 현재 Baseline에서 authoritative 공급원을 확인할 수 없음

### order_purpose

- Reference CanonicalOrderCommand에는 독립 필드가 없음

- 일부 track_id/tag_id가 목적을 암시하지만 표준 order_purpose의 authoritative source로 승격할 근거는 없음

## 핵심 판정

Reference Baseline에는 No.006의 표준 흐름에 명시된 독립적인 Position Logic → Order Intent 실행 의미 공급 단계가 아직 존재하지 않는다.

따라서 다음을 금지한다.

- Baseline에 없는 order_type/order_purpose 기본값 생성

- track_id/tag_id를 임의로 order_purpose로 변환

- Strategy qty를 Risk 승인 후 실행 qty로 무조건 간주

- requested_price와 execution price 혼합

## Standard 구현에 대한 영향

현재 OrderIntentFactory의 OrderIntentExecutionInput은 계약상 필요한 실행 의미를 명시하지만, 모든 필드가 Reference Baseline의 기존 공급원으로 이미 충족되는 것은 아니다.

현재 확인된 authoritative 공급 상태:

- quantity: 부분 확인 — Strategy 제안값 존재, Risk 최종값은 별도 승인 결과

- requested_price: 부분 확인 — Strategy price 존재, legacy fallback은 Standard로 이식하지 않음

- asset_type: 확인

- track_id/tag_id: 확인

- order_type: 공급원 없음

- order_purpose: 공급원 없음

## 다음 구현 기준

다음 단계에서는 새로운 synthetic Position Logic을 임의 생성하지 않는다.

먼저 Standard Core에서 Position/Execution Policy Contract가 실제로 어떤 계층의 책임이어야 하는지 확정하고, order_type/order_purpose 및 Risk 승인 후 quantity를 공급하는 최소 계약을 설계한다.