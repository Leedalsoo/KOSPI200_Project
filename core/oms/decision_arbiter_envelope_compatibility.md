# 목적

No.128에서 확정한 DecisionArbiter 호출 직전 Envelope 경계를 실제 program_runtime.py의 데이터 흐름에 대입하여, 기존 List[CanonicalStrategySignal] 기반 Risk/Order 경로를 변경하지 않고 provenance를 보존할 수 있는 최소 transport insertion point를 정의한다.

## 현재 Runtime 기준

원격 Exp_Detail_1의 현재 흐름은 다음과 같다.

Track 1~9 raw signal dict → CanonicalStrategySignal → SignalGenerator validation → raw_signals_collected → DecisionArbiter → RiskGate → OrderRouter

Canonical 생성 시 CanonicalStrategySignal에는 signal_id, track_id, asset_type, side, qty, price, option_type, strike, tag_id 등이 들어가지만 raw dictionary의 action, reason, 전략별 metadata 및 일부 명시적인 order_purpose/order_type은 별도 보존되지 않는다.

## 최소 삽입 지점

가장 작은 의미 보존 지점은 각 raw signal이 유효한 CanonicalStrategySignal로 변환·검증된 직후다.

권장 논리:

raw sig dict

→ CanonicalStrategySignal 생성

→ SignalGenerator validation

→ StrategySignalEnvelope(signal=c_sig, provenance=raw sig에서 추출)

→ 기존 Canonical 리스트에는 envelope.signal만 공급

→ 기존 DecisionArbiter/Risk/Order 경로 유지

즉, Envelope는 Canonical 리스트를 대체하지 않고 provenance 보존용 병렬 운반 객체로 사용한다.

## Adapter 책임

Adapter는 다음 두 가지 역할만 가진다.

1. raw signal과 Canonical signal 사이의 provenance를 연결한다.

1. 기존 Arbiter 입력이 요구하는 CanonicalStrategySignal만 추출한다.

Adapter가 해서는 안 되는 것:

- qty 변경

- price 변경

- side 변경

- asset_type/strike/option_type 변경

- priority 재계산

- clash 재판정

- signal 정렬 변경

- order_purpose 추론

- order_type 추론

- Risk 승인 수량 적용

## 중복·식별 안전성

Envelope를 다시 연결할 때 signal_id를 식별자로 사용한다. 동일 tick 내에서 동일 signal_id가 둘 이상이면 provenance 재연결이 모호하므로 fail-closed 해야 한다.

기존 Runtime이 생성하는 SIG-{seq}-{Track}-{local_seq} 규칙은 현재 각 strategy의 local sequence와 track을 포함하므로, Adapter는 값을 새로 만들지 않고 기존 signal_id를 그대로 사용한다.

## 권장 최소 API

```python
from typing import Iterable, List, Tuple


def unwrap_strategy_signal_envelopes(
    envelopes: Iterable[StrategySignalEnvelope],
) -> List[CanonicalStrategySignal]:
    return [envelope.signal for envelope in envelopes]


def index_strategy_signal_envelopes(
    envelopes: Iterable[StrategySignalEnvelope],
) -> dict[str, StrategySignalEnvelope]:
    indexed: dict[str, StrategySignalEnvelope] = {}
    for envelope in envelopes:
        signal_id = envelope.signal_id
        if signal_id in indexed:
            raise ValueError(f"DUPLICATE_SIGNAL_ID: {signal_id}")
        indexed[signal_id] = envelope
    return indexed
```

위 API는 Arbiter의 알고리즘을 복제하지 않는다. unwrap은 기존 입력 형태를 제공하고 index는 결과 provenance 재연결을 위한 식별자 검증만 수행한다.

## 중요: Runtime에 즉시 삽입하지 않는 이유

현재 Runtime은 raw_signals_collected 자체를 Risk 및 이후 주문 생성 경로의 입력으로 사용한다. 따라서 이 리스트를 Envelope 리스트로 직접 변경하면 downstream 계약을 동시에 변경해야 한다.

따라서 1차 구현에서는 다음 구조가 안전하다.

CanonicalStrategySignal[] = 기존 실행 경로의 authoritative runtime list

StrategySignalEnvelope[] = provenance 보존용 parallel list/index

이렇게 하면 기존 Strategy → SignalGenerator → Arbiter → RiskGate → OrderRouter의 실행 의미를 유지하면서 향후 Position Logic에서 provenance를 참조할 수 있다.

## order_purpose 전달 원칙

Envelope에 보존된 declared_order_purpose는 즉시 Standard OrderPurpose로 승격하지 않는다.

- 명시값이 있으면 provenance로 보존

- 없으면 None

- action/track/tag/side/position 방향으로 추론 금지

- Position Logic에서 explicit execution intent를 결정할 때 검증된 명시값을 입력 후보로 사용

Track9의 일부 명시 purpose도 이 원칙에 따라 보존한다.

## 결론

CanonicalStrategySignal을 변경하지 않고, 기존 Runtime의 Canonical 리스트를 그대로 유지하면서 별도의 StrategySignalEnvelope parallel transport를 두는 것이 현재 시점의 최소·안전한 삽입 방식이다.

실제 Runtime 수정 전에는 Envelope가 Risk 결과와 연결되는 이후 경계에서 signal_id/수량 provenance/order purpose provenance가 정확히 유지되는지를 별도 설계해야 한다.

## 보호 범위

- 원격 Exp_Detail_1 수정 없음

- 터미널 테스트 없음

- 기존 Arbiter 알고리즘 복제·재구현 없음

- Legacy OrderRequest 기본값 승격 없음

- order_purpose 및 order_type 추론 없음