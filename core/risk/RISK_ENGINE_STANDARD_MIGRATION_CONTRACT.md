## 목적

Reference option_program/risk_control/risk_engine.py를 OptionProject Standard Core로 이식하기 위한 최소 경계를 고정한다. Reference 코드를 그대로 복사하지 않고, 이미 확정된 Standard 입력 DTO와 책임 분리를 유지한다.

## Reference 실제 의존성 대조

- CanonicalOrderCommand: client_order_id, track_id, asset_type, side, qty, price, option_type, strike, symbol, expiry, tag_id를 제공하며 get_instrument_key()를 가진다.

- CanonicalAccountSummary: Reference RiskEngine이 직접 요구하는 total_balance, realized_pnl, used_margin, free_margin을 제공한다.

- RiskApprovalToken: Reference는 shared.core.contracts.RiskApprovalToken을 사용하며 order_id(UUID), timestamp_ns, signature 필드를 가진다. Standard Core는 이 Legacy 타입을 직접 import하지 않는다.

- MarginEngine.calculate_order_margin(command): OPTION은 price * qty * 250000, 단 price >= 50이면 2.5 fallback; FUTURES는 price * qty * 250000 * 0.10이다.

- RiskSensorSnapshot: is_margin_diet_required 및 reason 등을 RiskEngine에 전달한다.

## Standard 연결 경계

### 입력

1. 주문: Standard CanonicalOrderCommand를 그대로 전달한다.

1. 계좌: AccountSnapshot -> RiskAccountInput 명시적 adapter를 사용한다.
    - cash -> total_balance
    - realized_pnl -> realized_pnl
    - margin_used -> used_margin
    - available_cash -> free_margin

1. 포지션: authoritative PositionManager.positions의 symbol -> {qty, avg_price, side}를 PositionManager -> RiskPositionInput adapter로 전달한다. PositionSnapshot에서 side를 추론하지 않는다.

1. 센서: RiskSensorSnapshot을 RiskEngine 입력으로 유지한다.

## 최소 이식 대상

1. RiskConfig

1. RiskSensor의 scan_risk() 순수 판정 로직

1. RiskEvaluationResult

1. RiskEngine의 kill switch / daily loss / instrument limit / margin / margin diet / approval-token 판정 로직

1. RiskGate의 admit_order() 단일 진입점과 last_evaluation_result

## 의도적으로 이식하지 않는 것

- OrderType, OrderPurpose 등 Risk가 책임지지 않는 intent 정보

- Legacy shared.core.contracts 직접 import

- Legacy CanonicalAccountSummary 직접 의존

- PositionSnapshot에 side를 추가하는 변경

- Runtime/OMS 연결

- Reference PositionManager의 내부 FIFO 구현 복사

## 중요한 정합성 확인

Reference RiskEngine은 calculate_expected_position()에서 반대 방향 주문을 단순 수량 차감/반전으로 계산한다. 실제 PositionManager는 FIFO attribution이 있으면 lot 기준으로 처리한다. 따라서 RiskEngine은 PositionManager의 FIFO를 재구현하지 않고, pre-trade capacity 계산에 필요한 authoritative aggregate side/qty만 사용한다.

## 현재 보류 경계

RiskEngine 판정 로직 자체는 Standard 입력 계약으로 이식 가능하다. 다만 승인 토큰은 Standard 전용 RiskApprovalToken 계약이 아직 별도로 확정되지 않았으므로 Legacy 타입을 직접 가져오지 않는다. 다음 구현 단계에서 Standard token DTO를 최소 계약으로 확정한 뒤 RiskEngine/RiskGate를 구현한다.

## 검증 기준

- Reference Exp_Detail_1은 읽기 전용.

- Reference 소스 대조 결과만으로 pytest PASS를 주장하지 않는다.

- 구현 후 ALLOW, REDUCE, DENY, kill switch, daily loss, position limit, free margin, margin ratio, margin diet, token 발행 경로를 독립 테스트한다.