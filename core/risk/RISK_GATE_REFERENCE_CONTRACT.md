## 목적

Reference option_program/risk_control/risk_engine.py의 RiskSensor → RiskEngine → RiskGate 경계를 OptionProject Standard Core에 이식하기 전에 실제 입력/출력 계약을 고정한다.

## Reference 계약

- RiskConfig: max_order_qty=50, max_daily_loss_krw=10,000,000, max_margin_utilization_ratio=0.85, max_position_per_instrument=100, vol_spike_threshold_multiplier=1.30, account/position stale timeout=30s.

- RiskSensor.scan_risk(active_vol, base_vol, current_regime, account_margin_ratio, is_account_stale, is_position_stale) → RiskSensorSnapshot.

- RiskEngine.evaluate_order(command, account, positions, sensor_snapshot, allow_reduction=False) → RiskEvaluationResult.

- RiskGate.admit_order(command, account, positions, sensor_snapshot, allow_reduction=False) → (approved, token, rejection_reason)이며 last_evaluation_result를 보관한다.

- Risk 판정 순서: kill switch → qty validity/max → daily loss → instrument position limit → required/free margin → margin utilization → margin diet → approval token.

- ALLOW/REDUCE에서 최종 수량은 Risk가 결정한다. DENY는 주문 실행 객체를 만들지 않는다.

- REDUCE는 reduced_command.qty 및 approved_qty를 최종 실행 수량으로 사용한다.

## OptionProject 현재 계약과의 차이

현재 contracts/types.py의 AccountSnapshot은 balances: Mapping[str, Decimal> 중심의 환경중립 read model이고, Reference RiskEngine이 직접 요구하는 total_balance, realized_pnl, used_margin, free_margin 필드가 없다. 현재 PositionSnapshot도 Reference가 사용하는 instrument별 {side, qty} 구조와 동일하지 않다.

따라서 RiskEngine을 현재 Account/Position 계약에 맞춰 임의 변환하거나 balance key 이름을 추측하지 않는다.

## 구현 경계

1. CanonicalOrderCommand의 qty/price/side/asset/option identity/track_id/tag_id는 그대로 Risk 입력으로 전달한다.

1. Account/Position은 authoritative Standard Snapshot에서 Risk 전용 입력으로 명시적으로 변환되는 계약이 확보된 후 연결한다.

1. order_type/order_purpose를 Risk에서 추론하지 않는다. 해당 책임은 Position Execution Policy에 둔다.

1. Reference의 RiskApprovalToken은 Standard Core가 외부 Legacy contract를 직접 import하지 않도록 별도 표준 계약 확인 후 연결한다.

1. Risk 결과 이후의 OrderIntent/OMS Runtime 연결은 이번 단계에서 하지 않는다.

## 검증 기준

Reference Exp_Detail_1은 읽기 전용으로 유지한다. 독립 테스트는 OptionProject 구현을 임시 Python workspace로 materialize한 뒤 실행하며, 원격 브랜치에서 테스트/수정하지 않는다.

## RiskConfig Validation Contract

### 목적

RiskConfig는 Runtime Risk 판단 이전의 authoritative configuration boundary다. 외부 raw configuration은 이 경계에서 한 번만 normalization·validation되며, RiskEngine/RiskSensor는 검증 완료된 immutable RiskConfig를 직접 소비한다.

### Validation owner

- Owner: RiskConfig

- Consumer: RiskEngine, RiskSensor

- Consumer-side 동일 validation 재구현: 금지

- Invalid configuration: constructor 단계 fail-fast

### Field policy

<!-- Notion table block -->
| Field | Accepted input | Normalized contract | Domain rule | Error code |
| max_order_qty | int (bool 제외) | int | > 0 | MAX_ORDER_QTY_POSITIVE_INT_REQUIRED |
| max_daily_loss_krw | Decimal/int/float/string | Decimal | > 0, finite | RISK_CONFIG_DECIMAL_VALUE_* / MAX_DAILY_LOSS_KRW_POSITIVE_REQUIRED |
| max_margin_utilization_ratio | Decimal/int/float/string | Decimal | 0 < value <= 1 | RISK_CONFIG_DECIMAL_VALUE_* / MAX_MARGIN_UTILIZATION_RATIO_RANGE_REQUIRED |
| max_position_per_instrument | int (bool 제외) | int | > 0 | MAX_POSITION_PER_INSTRUMENT_POSITIVE_INT_REQUIRED |
| vol_spike_threshold_multiplier | Decimal/int/float/string | Decimal | > 0, finite | RISK_CONFIG_DECIMAL_VALUE_* / VOL_SPIKE_THRESHOLD_MULTIPLIER_POSITIVE_REQUIRED |
| margin_diet_active | bool | bool | bool only | MARGIN_DIET_ACTIVE_BOOL_REQUIRED |
| account_stale_timeout_sec | finite numeric | float | >= 0 | ACCOUNT_STALE_TIMEOUT_SEC_NONNEGATIVE_FINITE_REQUIRED |
| position_stale_timeout_sec | finite numeric | float | >= 0 | POSITION_STALE_TIMEOUT_SEC_NONNEGATIVE_FINITE_REQUIRED |

### Common numeric rules

1. None와 bool은 Decimal numeric threshold 입력으로 허용하지 않는다.

1. Decimal normalization은 Decimal(str(value))를 사용하여 기존 valid int/float/string constructor compatibility를 유지한다.

1. NaN과 ±Infinity 등 non-finite 값은 허용하지 않는다.

1. 변환 불가 값은 explicit ValueError로 정규화한다.

1. Decision threshold의 authoritative representation은 Decimal이다.

### Error-code layering

- Generic input-shape/normalization failure: RISK_CONFIG_DECIMAL_VALUE_REQUIRED / INVALID / FINITE_REQUIRED

- Field semantic domain failure: 각 field별 _REQUIRED 또는 _RANGE_REQUIRED

- 목적: 호출자는 numeric 형식 문제와 해당 Risk parameter의 업무 범위 위반을 구분할 수 있다.

### Margin ratio upper bound

max_margin_utilization_ratio의 현재 의미는 RiskEngine의 margin utilization threshold이며 0 < ratio <= 1로 계약한다. 향후 실제 leverage/margin model의 authoritative source가 ratio가 1을 초과하는 별도 업무 의미를 요구할 경우에만 해당 field의 domain policy를 재판정한다. 근거 없는 선제 확장은 하지 않는다.

### Runtime boundary

External raw config input → RiskConfig normalization/validation → valid immutable RiskConfig → RiskEngine/RiskSensor direct consumption

이 문서는 RiskSensor → RiskEngine → RiskGate 책임 경계 및 기존 RiskConfig 기본값을 정의한 RISK_GATE_REFERENCE_CONTRACT의 보완 계약이며, Risk 판정 순서나 전략 의미를 변경하지 않는다.