## 기존 기능 보존 대상

Exp_Detail_1의 option_program에 존재하는 Strategy, Sensor, Signal, Decision, Risk, Position, OMS 기능을 기능 단위로 이식한다.

## 이식 금지 방식

기존 OptionProgramRuntime 전체를 core로 이동하지 않는다.

Runtime orchestration과 Domain decision을 분리한다.

## Strategy Framework

각 Strategy는 동일 Lifecycle을 따른다:

1. Market State 수신

1. 조건 평가

1. Signal 생성

1. Decision 후보 생성

1. Risk 검증

1. Position 제약 반영

1. Order Intent 생성 또는 NO_ACTION

## 9개 Strategy 원칙

9개 전략은 환경별 구현이 아니라 하나의 Strategy Framework Plugin/Registry 아래에 둔다.

환경 변경으로 전략 코드나 파라미터 의미가 변경되면 안 된다.

## 외부 데이터 경계

Option Master Source와 Trading Calendar Source는 Infrastructure/Contract 경계에 둔다.

Core는 OptionContract와 DTE 계산 결과를 Domain 입력으로 사용한다.

Trading Calendar 실제 자동 Source가 BLOCKED인 상태를 임의 Source로 해결하지 않는다.