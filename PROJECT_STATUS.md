# PROJECT STATUS

## 문서 역할
이 문서는 현재 프로젝트의 상세 상태를 고정하는 문서가 아니다.
작업 원칙, 상태 기록의 위치, 검증 규칙만 제공한다.
상태 숫자나 완료된 Track 목록을 다음 작업의 사실 기준으로 사용하지 않는다.

## 현재 상태의 단일 기준
최신 테스트 통과 수, Track별 완료/진행/BLOCKED 상태,
현재 작업 우선순위와 최신 commit/checkpoint는
Notion `질문과답변`의 최신 `[No.xxx 답변내용요약]` 및 총괄 상태 기록을 기준으로 한다.
이 문서에는 그 값을 복제하지 않는다.
작업자는 작업 시작 시 지정된 Notion 기록과 원격 `Project200`의 실제 코드를 함께 확인한다.
실제 코드와 오래된 문서의 상태 설명이 다르면 실제 코드와 실행 증거를 우선한다.

## 프로젝트 목적과 실행 경계
현재 상태와 작업 우선순위는 이 파일에 기록하지 않는다.
KOSPI200 선물·옵션 자동매매 시스템을 구축한다.
기본 통합 검증 환경은 Virtual Trading이다.

표준 실행 경로:
시장 데이터 → 전략 입력 → 전략 → Decision → Risk → OMS/Router
→ Broker → Execution → Position/Margin/PnL → Control Tower Read Model

Virtual 환경에서는 Synthetic/Scenario/Replay를 사용할 수 있지만
실제 시장 데이터 또는 Live 검증으로 표현하지 않는다.
Real KIS 주문은 실행하지 않는다.
Live credential 및 실제 market-data frame이 없으면 Live E2E는 BLOCKED다.

## 검증 원칙
코드 존재만으로 PASS를 선언하지 않는다.
실제 실행 결과와 exit code를 근거로 PASS / FAIL / BLOCKED를 독립적으로 판정한다.
authoritative source가 없으면 임의의 0, False, 고정값, 추정값 또는 synthetic 값으로
정상 runtime을 채우지 않고 fail-closed 한다.

## 표준 경계
`contracts/` → 표준 계약·DTO·port
`core/` → 환경 독립 domain·strategy·risk·OMS 규칙
`application/` → orchestration·composition·Hub
`environments/` → Virtual/Paper/Live/High-Speed 구현
`infrastructure/` → KIS/KRX 등 외부 adapter/source
`interfaces/` → Control Tower 및 외부 API/UI
`tests/` → 회귀·통합 검증
Legacy 구현은 새 표준 경로에 이름만 바꾸어 재연결하지 않는다.
필요한 기능은 현재 표준 경계에 맞게 명시적으로 이관한다.

## 반복 실행 격리
반복 테스트는 독립된 Run ID와 새 Environment Bundle/VSSF account/
position/execution/strategy state를 사용한다.
이전 run의 주문·체결·포지션·PnL·strategy state를 다음 run에 재사용하지 않는다.

## 검증 절차
영향 범위 확인 → focused pytest → 필요한 Virtual E2E
→ `py -m pytest -q` → `git diff --check` → project200_gate
→ `git status` → 원격 HEAD 확인 → Notion 기록
Python은 Windows launcher `py`로 실행한다.

## Git 관리
원격 기준 브랜치는 `Project200`이다.
commit/push 전 변경 범위와 테스트 결과를 확인한다.
무관한 untracked 파일은 commit에 포함하지 않는다.
`.env` 및 credential은 절대로 commit하지 않는다.
push 후 원격 `Project200` HEAD가 commit SHA와 일치하는지 확인한다.

## 상세 작업 기록
구현·검증 결과와 최신 우선순위는 Notion `질문과답변`에
`[No.xxx 답변내용요약]` 형식으로 기록한다.
이 문서에는 단계별 통과 숫자, 특정 commit, 완료 Track 목록, 임시 우선순위를 고정하지 않는다.
문서 변경 자체도 실제 코드와 검증 결과를 확인한 뒤 commit한다.
