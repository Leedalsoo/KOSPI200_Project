# KOSPI200 Project200

KOSPI200 선물·옵션 자동매매 시스템 개발 프로젝트다. 현재 개발·검증의 중심은 **Virtual Trading / KIS VTS / Control Tower / Strategy 1~9 / REAL_VTS 기반 E2E**이며, Live 주문은 실행하지 않는다.

상세 작업 기준은 [AGENTS.md](AGENTS.md)를 따른다.

## 1. 현재 표준 실행 구조

**Market Data Source → Runtime Input → Strategy → Decision → Risk → OMS/Order Router → Broker → Execution → Position/Margin/PnL → Control Tower Read Model**

Control Tower는 감독·운영·read-model 계층이며 정상적인 주문 생성이나 전략 로직을 소유하지 않는다.

| 경로 | 역할 |
|---|---|
| `contracts/` | 표준 계약·DTO·Port |
| `core/` | 환경 독립 Domain·Strategy·Risk·OMS |
| `application/` | Orchestration·Composition·Hub |
| `environments/` | Virtual/Paper/Live/High-Speed 구현 |
| `infrastructure/` | KIS/KRX 등 외부 Adapter/Source |
| `interfaces/` | Control Tower/API/UI |
| `tests/` | 회귀·통합 검증 |

## 2. Strategy 기준

Strategy 1~9는 독립적인 Strategy Plugin/Registry 경계를 유지한다.

공통 시장지표와 계산은 Common Analytics가 소유하고 표준 `AnalyticsSnapshot`으로 제공한다. Strategy는 이를 소비하고 전략 고유의 진입·청산·헤지·상태전이·포지션 규칙을 담당한다.

Authoritative source가 없는 값을 고정값, 0/False, 추정값 또는 synthetic 값으로 채워 정상 신호를 만들지 않는다.

## 3. KIS VTS / REAL_VTS 데이터

KIS VTS 모의계좌에서 수집한 실제 시장데이터는 **REAL_VTS 원본**으로 취급한다. REAL_VTS는 Live 데이터가 아니며 Live E2E PASS를 의미하지 않는다.

현재 운영 저장 루트:

`data/kis_market_data_restart/YYYY-MM-DD/`

날짜별 partition은 독립적인 테스트 데이터셋이 아니라 누적되는 실제 시장 데이터 stream의 저장 단위다.

REST와 WebSocket은 독립적인 수집 경계로 유지한다.

- REST: 시장관측/Historical Store 원본
- WebSocket: raw frame 원본
- source/provenance와 timestamp를 transport 간 혼용하지 않는다.
- WebSocket 연결 성공만으로 frame 수신 PASS를 선언하지 않는다.
- manifest와 실제 raw/canonical evidence가 다르면 collector lifecycle 문제로 별도 조사한다.

## 4. Replay / E2E 검증

Strategy 1~9는 가능한 authoritative input 범위에서 독립적으로 검증한다.

**Source → Runtime Input → Strategy Signal → Decision → Risk → OMS/Router → Virtual Execution → Position/PnL → Regression**

실제 signal이 관찰되지 않은 전략은 signal-driven execution lifecycle PASS를 선언하지 않는다.

REAL_VTS, DERIVED_SCENARIO, SYNTHETIC, VIRTUAL_EXECUTION provenance는 서로 구분한다.

각 실행은 독립 Run ID와 독립적인 execution/position/strategy state를 사용한다.

High-Speed Replay은 필요에 따라 가속 실행하되 원본 event timestamp의 순서와 시간관계를 보존한다.

## 5. Control Tower

현재 UI는 다음 구조를 유지한다.

- 6개 운영 탭
- Strategy 1~9
- 3×3 동일 크기 Strategy Grid
- Strategy별 독립 Composition Graph
- Strategy Control의 USE / ENTRY / EXIT
- Strategy Trade P/L과 Account P/L 분리
- Strategy 카드의 월별 Trade P/L: ENTRY → CLOSE/EXPIRY
- 카드 하단의 Strategy Integrated P/L
- Graph에서는 BUY/SELL trade value와 계약 구조를 표시하며 P/L을 계산하지 않음

UI 표준 경로:

**Authoritative Runtime / Execution / Position Read Model → Option Program Read Model → Control Tower API → UI**

UI가 Strategy/Core를 직접 호출하거나 없는 데이터를 임의 생성하지 않는다.

## 6. Filled → Position → Trade P/L → UI

**ExecutionReport → Position Group → Strategy Trade P/L → Strategy Card P/L**

Runtime execution과 Control Tower Read Model은 동일한 authoritative execution/position-group 상태를 바라보아야 한다.

Account P/L과 Strategy Trade P/L은 의미가 다를 수 있으므로 임의로 동일하게 맞추지 않는다. Position open/closed와 Trade Ledger 상태가 불일치하면 별도 accounting/read-model 검증 대상으로 취급한다.

현재 일부 실제 VTS 연결 증거가 확보되어 있지만 이를 Strategy 1~9 전체 Full E2E PASS로 확대하지 않는다.

## 7. 3개월 자동 E2E

자동 검증 pattern:

**trend_up → trend_down → mean_revert → high_volatility → low_volatility → shock**

판정 규칙:

- Replay PASS + UI smoke PASS → PASS
- Replay FAIL → FAIL
- UI smoke FAIL → FAIL
- Replay FAIL이어도 UI smoke는 실행
- UI smoke FAIL이면 다음 pattern으로 회전
- Replay만 FAIL이고 UI smoke가 PASS이면 같은 pattern 재시도

현재 scheduled UI smoke는 HTTP/API/UI contract를 검증한다. 동일 replay의 실제 브라우저 DOM Playwright 검증과는 구분한다.

## 8. 검증 원칙

테스트 파일의 PASS만으로 production 기능의 PASS를 선언하지 않는다.

실제 검증은 현재 코드와 실제 실행 evidence를 우선한다.

기본 참조 순서:

**Current Baseline → 최신 활성 Decision Log → AGENTS.md → 현재 코드/실제 데이터/source → 새 검증**

Windows Python 실행은 `py`를 사용한다.

판정은 실제 실행 명령, 출력, exit code 및 관련 evidence를 기준으로 **PASS / FAIL / BLOCKED**를 구분한다.

## 9. Git / 작업 기준

- `.env` 및 credential은 commit하지 않는다.
- 사용자 작업 중인 unrelated 변경은 임의로 수정하거나 함께 commit하지 않는다.
- 일회성 실행 로그, cache 및 폐기된 Legacy 산출물은 저장소에 남기지 않는다.
- 변경 후 focused test 및 필요한 E2E를 수행한다.
- `git diff --check`와 `git status`를 확인한다.
- commit/push 후 원격 `Project200` HEAD를 확인한다.

상세 작업 절차와 현재 세부 기준은 **[AGENTS.md](AGENTS.md)**를 기준으로 한다.

## 10. 현재 미완료 범주

실제 evidence가 확보될 때까지 다음 항목은 전체 PASS로 취급하지 않는다.

- Strategy 1~9 전체의 REAL_VTS signal → execution → Position/PnL Full E2E
- 동일 3개월 replay와 동일 runtime state를 대상으로 한 실제 browser DOM Playwright 자동 검증
- Strategy Trade P/L / Account P/L / Position open·closed semantics의 완전한 회계 정합성
- KIS VTS Collector manifest/lifecycle과 실제 evidence의 완전한 정합성
- KIS Live credential 및 실제 Live E2E
- 옵션 매수호가·승수·수량·수수료·슬리피지를 반영하는 Runtime 프리미엄 검사
- 옵션 레그별 만기 payoff/max-loss 및 기존 미청산 포지션·체결 원장 기반 계좌 전체 위험 집계
- 부분체결·거절·청산·만기 회귀 검증
- Strategy 1 헤지 구조와 Strategy 3·4·5 선물 레그의 경제적 목적·위험 한도 확정

## 11. 옵션 헤지 위험 검사 — 현재 계획

옵션 헤지 설정 초안은 config/risk/option-hedge-risk.v1.json, 검증 모델은 core/risk/option_hedge_risk_config.py에 있다. 현재 DISABLED_UNTIL_RUNTIME_INTEGRATION 상태이므로 실제 주문 경로의 위험 차단 기능으로 간주하지 않는다. 단위 테스트가 통과해도 Runtime enforcement PASS를 의미하지 않는다.

구현 순서는 다음과 같다.

1. Strategy 1 보호 구조와 Strategy 3·4·5 선물 레그의 경제적 목적·위험 한도를 별도 검토한다.
2. authoritative 매수호가, 계약 승수, 수량, 수수료 및 보수적 슬리피지를 포함해 프리미엄을 검사한다.
3. 각 레그의 정확한 만기·행사가·방향·수량으로 만기 payoff와 최대손실을 계산한다.
4. 기존 미청산 포지션과 실제 체결 원장을 연결해 중복 없는 계좌 전체 위험을 집계한다.
5. 부분체결·거절·청산·만기 및 입력 누락/오류 회귀를 검증한다.

기존 공통 RiskConfig의 일일 손실 한도와 증거금 한도는 그대로 유지하며 옵션 프리미엄/최대손실 한도로 재해석하지 않는다. 임시 설정 금액은 최종 운용 한도로 확정되지 않았다. authoritative 데이터가 누락되거나 계산이 불가능하면 fail-closed한다. 전략 코드·manifest·매매 정책은 전략별 설계 및 회귀 범위 승인을 거친 뒤 변경한다.

README는 프로젝트의 현재 구조와 작업 순서를 요약하고, 상세 절차는 AGENTS.md, 실제 결정 상태는 Notion의 최신 Q&A와 확정 Decision Log를 기준으로 한다.
