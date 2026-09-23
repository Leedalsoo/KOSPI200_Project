# KOSPI200 Project200

## 목적
KOSPI200 선물·옵션 자동매매 시스템을 구축한다. Standard Core를 중심으로 High-Speed, Virtual, Paper, Live 환경을 교체·검증하며, 증권사 종속 없이 여러 broker를 동일한 Standard Broker API 뒤에 연결할 수 있는 broker-agnostic 구조를 목표로 한다.

## 현재 개발 기준
- 기본 검증 환경: Virtual Trading
- 실행 흐름: 시장 데이터 → Runtime Input → Strategy → Decision → Risk → OMS/Router → Broker → Execution → Position/Margin/PnL → Control Tower Read Model
- 전략 공통 계산은 Common Analytics가 소유하며 Strategy는 전략 고유 의사결정만 담당한다.
- Control Tower: 감독·운영 계층이며 정상 주문 생성의 주 경로가 아니다.
- Real KIS 주문: 현재 실행하지 않으며 외부 인증·실주문 검증은 BLOCKED로 관리한다.
- KIS 모의투자(VTS) 시장데이터 수집은 일별로 상시 운영하며, 실제 시장데이터를 실거래 전 Virtual/Replay 검증 자산으로 축적한다.
- Multi-Broker 설계는 확정됐으나 LS증권 등 제2 broker의 실제 연동 코드·credential 처리는 사용자 승인 전까지 작성하지 않는다.

## 저장소 구조
- `contracts/` 표준 계약·DTO·port
- `core/` 환경 독립 domain/strategy/risk/OMS
- `application/` orchestration/composition
- `environments/` 실행 환경 구현
- `infrastructure/` KIS/KRX 등 외부 source adapter
- `interfaces/` Control Tower/API/UI
- `tests/` 실행 가능한 현재 회귀·통합 검증
- `docs/`, `scripts/`, `shared/`, `support/`, `verification/` 보조 문서·운영 스크립트·공용 유틸리티
- 저장소 루트의 `ARCHITECTURE.md` 등 개별 스펙 문서는 해당 경계의 세부 설계를 다룬다.

## 데이터·계약 경계
- KRX Marketplace는 계약 선택의 authoritative source이며 Option Master, expiry, strike, option type 등 계약 identity를 추정하지 않는다.
- KIS Index Option Master는 KIS broker symbol reconciliation의 authoritative source로 사용한다.
- 시장데이터는 source/provenance를 보존하고 거래일별 partition으로 저장한다.
- Virtual 시장데이터 경계는 authoritative source 수집·정규화 → Historical Market Store → Virtual Exchange → Virtual Broker → Virtual Broker API → Option Program이다.
- Replay/Scenario/Synthetic 결과는 실제 시장 원본과 명확히 구분한다.

## 장기 백그라운드 수집
Daily Session Orchestrator가 KST 거래일을 기준으로 readiness/smoke, 장중 반복 수집, heartbeat, manifest 및 날짜 partition을 관리한다.

KRX authoritative Option Master는 날짜별 snapshot을 선택하며, 대상 날짜에 필요한 계약/만기가 현재 snapshot으로 설명되지 않으면 임의 fallback 대신 `BLOCKED` 또는 refresh-required로 fail-closed 한다. Broker master로 KRX 계약 선택을 대체하지 않는다.

축적한 VTS 실제 시장데이터는 여러 거래일·만기·계약·시장상황에 대해 1x Replay와 가속 Replay로 반복 검증한다. 실제 원본을 변형한 Scenario/Synthetic 데이터는 별도의 provenance로 관리한다.

## 실행·검증 원칙
- Windows에서 Python 검증은 `py`를 사용한다.
- 실제 실행 결과와 exit code를 기준으로 PASS / FAIL / BLOCKED를 독립적으로 판정한다.
- authoritative source가 없으면 0, False, 고정값, 추정값 또는 synthetic 값으로 정상 runtime을 채우지 않는다.
- Live credential 및 실제 market-data frame이 없으면 Live E2E는 BLOCKED다.
- 실제 KIS 주문은 어떤 개발·검증 단계에서도 실행하지 않는다.

## 작업 기준
상세 작업 지침은 `AGENTS.md`를 따른다.

현재 상태·완료 Track·우선순위·최신 검증 수치의 단일 기준은 `PROJECT_STATUS.md`가 가리키는 Notion `질문과답변`의 최신 `[No.xxx 답변내용요약]` 기록이다. 이 README에는 특정 테스트 숫자, checkpoint, 완료 Track 또는 임시 우선순위를 고정하지 않는다.

의미 있는 구현·정리·검증은 Notion `질문과답변`에 기록한다. 과거 단계별 Process 문서와 일회성 검증 파일은 저장소에 유지하지 않는다.

`.env` 및 credential은 Git에 기록하지 않는다.
