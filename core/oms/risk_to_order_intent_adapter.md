## 목적

No.131~132에서 확정한 signal_id → client_order_id → effective_cmd 연결을 Standard OrderIntentExecutionInput에 안전하게 연결하는 최소 Adapter 계약이다.

## 실제 Standard Factory 계약

OrderIntentExecutionInput은 다음을 요구한다: client_order_id, quantity, requested_price, order_type, order_purpose, asset_type, track_id, tag_id. Factory는 quantity/order_type/order_purpose/asset_type 및 instrument identity를 검증하며 누락 시 실패한다.

## Adapter 입력

- RiskProvenanceLink: signal_id, client_order_id, StrategySignalEnvelope

- effective_cmd: Risk 이후 실제 실행 대상 CanonicalOrderCommand

- execution_policy_decision: Position Logic이 결정한 order_type, order_purpose

## 변환 규칙

<!-- Notion table block -->
| OrderIntentExecutionInput | 공급원 | 규칙 |
| client_order_id | effective_cmd.client_order_id | provenance link와 동일해야 함 |
| quantity | effective_cmd.qty | Risk 이후 값만 authoritative. signal qty 재사용 금지 |
| requested_price | effective_cmd.price | 현재 Canonical price를 Decimal로 보존. 별도 fallback 금지 |
| order_type | Position Execution Policy | 정책 결정값만 사용. 누락 시 Factory 전에 실패 |
| order_purpose | Position Execution Policy / explicit provenance | 명시된 값만 사용. action/track/tag/side로 추론 금지 |
| asset_type | effective_cmd.asset_type.value | Canonical 값 보존 |
| track_id | effective_cmd.track_id | Canonical provenance 보존 |
| tag_id | effective_cmd.tag_id | Canonical provenance 보존 |

## Explicit purpose 연결

Track9 등 원본 신호에 명시된 order_purpose/order_type는 StrategySignalEnvelope.provenance에 보존한다. 그러나 provenance 값 자체를 무조건 Standard 의미로 승격하지 않는다. Position Logic의 OrderPositionExecutionPolicyDecision을 통해 OrderIntent 실행 의미로 확정한 경우에만 Factory 입력으로 전달한다.

purpose가 없으면 OrderIntentExecutionInput을 생성하지 않는다. 특히 BUY=ENTRY, SELL=EXIT, Track9=HEDGE 등의 추론을 금지한다.

## order_type 호환 정책

현재 Reference 실행은 LIMIT 기반이지만 Canonical DTO의 독립 필드가 아니다. 따라서 Adapter가 임의로 Canonical에 order_type을 추가하지 않는다. Position Execution Policy가 현재 호환 정책으로 LIMIT을 명시적으로 결정한 경우에만 Factory 입력으로 전달한다. 이는 Canonical 의미 변경이 아니다.

## fail-closed 조건

- provenance link의 signal_id와 envelope signal_id 불일치

- provenance link의 client_order_id와 effective command client_order_id 불일치

- effective_cmd.qty <= 0

- order_type 없음

- order_purpose 없음

- asset_type 없음

## Adapter 책임 범위

Adapter는 의미를 새로 결정하지 않고, 이미 결정된 Risk 결과와 Position Execution Policy 결과를 Factory 계약으로 정확히 운반한다. DecisionArbiter 재실행, Risk 재계산, quantity 재계산, instrument identity 생성, purpose 추론을 하지 않는다.

## Runtime 연결 시점

현재 Runtime은 effective_cmd를 바로 OrderRouter에 전달한다. 따라서 이 Adapter를 즉시 Runtime에 삽입하면 기존 실행 경로가 바뀐다. 본 단계에서는 계약을 확정하고 실제 Runtime 삽입은 별도 단계에서 진행한다. Runtime 변경 시에도 기존 raw_signals_collected: List[CanonicalStrategySignal], Arbiter, RiskGate semantics를 유지해야 한다.

## No.133 실제 계약 대조 결과

### 1. Standard OrderIntentExecutionInput 필수 계약

- client_order_id

- quantity

- requested_price

- order_type

- order_purpose

- asset_type

- track_id

- tag_id

OrderIntentFactory는 execution input의 quantity/order_type/order_purpose/asset_type를 필수 검증하며, OPTION인 경우 OptionIdentityResolver를 통해 instrument_id를 확정한다. identity 또는 필수 execution 값이 없으면 synthetic fallback 없이 실패한다.

### 2. Risk 이후 authoritative 값

현재 Reference Runtime의 Risk 이후 실행 객체는 effective_cmd이며, 실행 수량은 effective_cmd.qty를 authoritative source로 사용한다. 따라서 Strategy signal의 qty를 다시 사용하거나 Adapter에서 Risk 결과를 재계산하지 않는다.

### 3. 안전한 필드 매핑

<!-- Notion table block -->
| OrderIntentExecutionInput | 공급 경계 | 규칙 |
| client_order_id | effective_cmd.client_order_id  • RiskProvenanceLink | 두 값이 정확히 일치해야 함 |
| quantity | effective_cmd.qty | Risk 이후 최종값만 사용, <=0 fail-closed |
| requested_price | effective_cmd.price 후보 | 실제 계약상 price 의미를 추가 확인한 뒤 연결 |
| asset_type | effective_cmd.asset_type | Canonical 값 보존 |
| track_id | effective_cmd.track_id | provenance 재작성 금지 |
| tag_id | effective_cmd.tag_id | provenance 재작성 금지 |
| order_purpose | explicit execution provenance / Position Logic | 누락 시 추론·기본값 금지 |
| order_type | explicit execution provenance / Position Execution Policy | 명시값만 전달; compatibility LIMIT은 별도 정책 경계 |

### 4. Identity 경계

현재 원격 CanonicalOrderCommand에는 별도 instrument_id가 없으며 OPTION identity를 Standard Factory가 요구한다. 따라서 지금 즉시 Factory를 Runtime에 삽입하지 않는다.

다음 단계는 실제 Track 신호의 option_type/strike/symbol/expiry 및 Futures 식별정보가 어떤 authoritative identity로 연결될 수 있는지 추적하고, OptionIdentityResolver 직전의 변환 계약을 확정하는 것이다.

### 5. 기존 프로그램 보호

- Canonical DTO 변경 없음

- DecisionArbiter 변경 없음

- RiskGate 변경 없음

- OrderRouter 변경 없음

- 기존 전략 계산/주문 실행 로직 복제 없음

- 원격 Exp_Detail_1 변경 없음