# Risk → Order Intent Adapter

## 목적
Risk 승인 결과와 Position Execution Policy의 명시적 실행 의미를 `OrderIntentExecutionInput`으로 연결한다.

## 현재 구현
구현: `core/oms/risk_order_intent_adapter.py`

`build_order_intent_execution_input()`은 다음을 보장한다.
- `DENY` 또는 승인되지 않은 Risk 결과는 fail-closed
- `ALLOW`는 `approved_qty`만 사용
- `REDUCE`는 `reduced_command.qty`와 `approved_qty`의 provenance가 일치해야 함
- 승인 수량이 0 이하이면 실패
- `order_type`, `order_purpose`, `asset_type`, `track_id`, `tag_id`는 Position Execution Decision에서 공급
- Strategy 제안 수량을 Risk 수량의 fallback으로 사용하지 않음
- Adapter가 order type이나 order purpose를 추론하지 않음

## 실행 경계
Adapter는 Risk 결과와 Position Execution Decision을 연결할 뿐이며, Broker network I/O나 실제 주문을 수행하지 않는다.

`OrderIntentExecutionInput` 생성 이후의 실행 경로는 현재 OMS/Router 및 Environment 계층의 구현을 따른다. 이 문서는 과거 Notion 번호나 이전 Runtime 설계를 기준으로 하지 않는다.

## Fail-closed
필수 provenance, 승인 수량 또는 실행 의미가 없으면 합성값이나 기본값을 사용하지 않고 예외로 중단한다.
