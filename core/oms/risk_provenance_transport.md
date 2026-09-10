## 목적

No.129에서 확정한 StrategySignalEnvelope parallel transport를 실제 Risk 결과와 Position Logic / Order Intent 경계까지 연결하기 위한 최소 전달계약을 정의한다. 기존 CanonicalStrategySignal[] → DecisionArbiter → RiskGate → OrderRouter 실행 의미는 변경하지 않는다.

## 원격 Exp_Detail_1 실제 흐름

현재 program_runtime.py의 실제 주문 경로는 다음과 같다.

CanonicalStrategySignal → DecisionArbiter → approved_sig → CanonicalOrderCommand → RiskGate.admit_order() → RiskEvaluationResult → effective_cmd → OrderRouter.register_and_route()

RiskGate는 RiskEvaluationResult를 last_evaluation_result에 보관한다. 결과에는 decision, is_approved, original_qty, approved_qty, reduced_command, rejection_reason, token이 있다.

현재 Runtime은 allow_reduction을 명시하지 않으므로 기본값 False로 동작한다. 따라서 현재 실행에서는 REDUCE를 새로 활성화하지 않는다.

## provenance가 실제로 연결될 수 있는 안정 지점

### 1. Signal identity

CanonicalStrategySignal.signal_id가 Arbiter 입력과 결과 신호에 그대로 유지된다. Arbiter는 이 값을 우선순위/정렬의 최종 tie-break 및 결과 재연결 key로 사용할 수 있다.

### 2. Command identity

Runtime은 승인된 signal을 CanonicalOrderCommand로 만들면서 client_order_id를 생성한다. 이 시점에 client_order_id → signal_id 매핑을 별도로 기록하는 것이 가장 안전하다.

문자열의 일부를 다시 파싱하여 signal_id를 복원하지 않는다. 현재 문자열 형식은 호환성상 보존하되 provenance 식별의 권위값으로 승격하지 않는다.

### 3. Risk quantity

Risk 통과 후 실제 실행 대상은 effective_cmd다.

- ALLOW: approved_qty를 사용하며 effective_cmd is cmd.

- REDUCE: reduced_command.qty가 최종 수량이며 client_order_id는 유지된다.

- DENY: OrderIntent를 생성하지 않는다.

따라서 Position Logic / Order Intent로 전달할 quantity의 권위값은 strategy signal의 원래 qty가 아니라 Risk 결과를 반영한 effective_cmd.qty다.

## 최소 provenance index

권장되는 parallel transport 상태는 다음 두 인덱스다.

```python
signal_provenance_by_id: dict[str, StrategySignalEnvelope]
order_provenance_by_client_id: dict[str, StrategySignalEnvelope]
```

연결 순서는 다음과 같다.

StrategySignalEnvelope.signal_id

→ Arbiter approved signal의 signal_id

→ 생성된 CanonicalOrderCommand.client_order_id와 envelope 연결

→ RiskGate

→ effective_cmd.client_order_id로 동일 envelope 재조회

→ Risk 승인 수량을 적용한 Position Logic / Order Intent 입력 생성

REDUCE에서도 client_order_id가 유지되므로 동일 연결을 유지할 수 있다.

## Adapter 책임

Adapter는 다음만 수행한다.

1. Envelope를 signal_id로 index한다.

1. 승인된 signal과 provenance를 signal_id로 연결한다.

1. CanonicalOrderCommand 생성 시 client_order_id → envelope 연결을 만든다.

1. Risk 결과가 승인된 경우 effective_cmd.client_order_id로 provenance를 재조회한다.

1. Risk의 최종 실행 수량을 effective_cmd.qty에서 확인한다.

1. explicit declared_order_purpose / declared_order_type만 Position Logic의 입력 후보로 전달한다.

1. DENY 또는 provenance 불일치 시 fail-closed한다.

## Adapter가 하지 않는 것

- Arbiter priority / sorting / clash 재계산

- signal qty와 Risk qty의 재계산

- action → order_purpose 추론

- track_id / tag_id → order_purpose 추론

- side / position direction → order_purpose 추론

- missing purpose/type의 기본값 생성

- Risk REDUCE 활성화

- CanonicalOrderCommand 구조 변경

- client_order_id 문자열 parsing으로 signal_id 복원

## 권장 최소 API 형태

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class RiskProvenanceLink:
    signal_id: str
    client_order_id: str
    envelope: StrategySignalEnvelope


def link_approved_signal_to_order(
    envelope: StrategySignalEnvelope,
    client_order_id: str,
) -> RiskProvenanceLink:
    if envelope.signal_id == "":
        raise ValueError("SIGNAL_ID_REQUIRED")
    if not client_order_id:
        raise ValueError("CLIENT_ORDER_ID_REQUIRED")
    return RiskProvenanceLink(
        signal_id=envelope.signal_id,
        client_order_id=client_order_id,
        envelope=envelope,
    )
```

실제 Risk 결과를 OrderIntent로 변환할 때는 기존 risk_order_intent_adapter.py의 원칙을 그대로 적용한다. 즉 ALLOW는 approved_qty, REDUCE는 reduced_command.qty를 사용하고, DENY는 실패시킨다. 이 문서는 그 수량 결정 로직을 복제하지 않고 provenance 연결만 담당한다.

## Position Logic 경계

No.006 및 No.043의 표준 흐름에 따라 Position Logic은 Risk 이후의 명시적 실행 의미를 다룬다. Strategy provenance의 declared_order_purpose/type는 관찰·보존된 원본 값이지 자동 확정된 표준 OrderPurpose/OrderType가 아니다.

따라서 다음 조건을 모두 만족할 때만 ExplicitPositionExecutionIntent 후보로 전달한다.

- provenance가 해당 signal_id에 정확히 연결됨

- 승인된 client_order_id와 연결됨

- 명시적 order_purpose가 존재함

- order_type이 존재한다면 명시값 그대로 전달

purpose가 없는 Track1~8 또는 purpose가 없는 Track9 신호는 빈 값을 유지한다. action 이름만으로 purpose를 만들어내지 않는다.

## 현재 Runtime을 변경하지 않는 단계적 적용

1. 현재 raw_signals_collected: List[CanonicalStrategySignal]는 그대로 유지한다.

1. Envelope는 parallel list/index로만 보존한다.

1. Arbiter는 기존 Canonical list를 그대로 받는다.

1. approved signal이 생긴 후 signal_id → envelope를 조회한다.

1. CanonicalOrderCommand 생성 직후 client_order_id → envelope를 연결한다.

1. RiskGate는 현재 그대로 호출한다.

1. Risk 승인 후 effective_cmd.client_order_id로 동일 provenance를 조회한다.

1. 이후 Position Logic / OrderIntent 단계에서만 explicit execution intent를 해석한다.

## Fail-closed 조건

다음은 주문 Intent로 진행시키지 않는다.

- 동일 signal_id에 여러 envelope가 존재

- approved signal의 signal_id가 provenance index에 없음

- client_order_id가 provenance link에 없음

- Risk가 DENY

- Risk REDUCE인데 reduced_command가 없거나 수량이 approved_qty와 불일치

- Risk 승인 수량이 0 이하

- explicit purpose가 필요한 Position Logic 단계에서 purpose가 없음

## 결론

현재 Runtime에서 provenance를 Risk 이후까지 보존하는 가장 작은 변경 단위는 signal_id를 1차 연결키로 하고, 주문 생성 시점에 client_order_id를 2차 실행 추적키로 고정하는 parallel provenance index다. Risk는 수량의 권위자로 유지하고, effective_cmd가 Position Logic / Order Intent로 넘어가는 실행 데이터의 기준이 된다. Canonical Contract, DecisionArbiter, RiskGate, OrderRouter의 현재 의미는 이 단계에서 변경하지 않는다.

## 근거

- No.006: Market State → Strategy → Signal → Decision → Risk Validation → Position Logic → Order Intent

- No.043: Signal은 전략 판단, Risk는 허용/거부/수량 조정, Position Logic은 포지션 차이 계산, Order Intent는 Broker 호출과 분리

- No.129: Envelope는 기존 Canonical 실행 리스트를 대체하지 않는 parallel transport

- 원격 Exp_Detail_1의 program_runtime.py, risk_engine.py, order_router.py 실제 코드 기준