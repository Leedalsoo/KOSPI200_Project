# KOSPI200 Project200

KOSPI200 선물·옵션 자동매매 시스템 개발 프로젝트다. 현재 개발·검증은 Virtual Trading, KIS VTS, Control Tower, Strategy 1~9 및 REAL_VTS 기반 E2E를 중심으로 진행한다. **실제 KIS Live 주문은 실행하지 않는다.**

- 작업 규칙과 지속 기준: [AGENTS.md](AGENTS.md)
- 최신 통합 정책 기준: Notion 질문과답변 **No.1278 — Strategy 1~9 KIS 단일 출처 최신 통합판**
- No.1274는 원본 전략 기준표이며, 최신 통합 정책이나 현재 검증 완료의 증거가 아니다.
- 문서 기준: 현재 대화의 지시와 최신 확정 Decision Log를 우선하며, 실제 상태는 코드·데이터·새 검증 evidence로 확인한다.

## 1. 표준 실행 구조

**Market Data Source → Runtime Input → Strategy → Decision → Risk → OMS/Order Router → Broker → Execution → Position/Margin/PnL → Control Tower Read Model**

Control Tower는 감독·운영·read-model 계층이며 정상적인 주문 생성이나 전략 로직을 소유하지 않는다.

| 경로 | 역할 |
|---|---|
| `contracts/` | 표준 계약·DTO·Port |
| `core/` | 환경 독립 Domain·Strategy·Risk·OMS |
| `application/` | Orchestration·Composition·Hub |
| `environments/` | Virtual/Paper/Live/High-Speed 구현 |
| `infrastructure/` | KIS 등 외부 Adapter/Source |
| `interfaces/` | Control Tower/API/UI |
| `tests/` | 회귀·통합 검증 |

## 2. Strategy 1~9 / Common Analytics

Strategy 1~9는 독립적인 Strategy Plugin/Registry 경계를 유지한다. 공통 시장지표와 계산은 Common Analytics가 소유하고 표준 `AnalyticsSnapshot`으로 제공한다. Strategy는 이를 소비하며 전략 고유의 진입·청산·헤지·상태전이·포지션 규칙을 담당한다.

Authoritative source가 없는 값은 고정값, 0/False, 추정값 또는 synthetic 값으로 채워 정상 신호를 만들지 않는다. 필수 데이터, 계약 identity, timestamp, capability 또는 provenance가 누락·불일치·미검증이면 fail-closed로 `BLOCKED`/`UNAVAILABLE` 처리한다.

## 3. KIS 데이터 출처와 REAL_VTS

**런타임 시장 데이터와 계약 기준정보의 권위 출처는 KIS API 및 공식 KIS 종목 마스터다.** KRX 데이터나 교차 매핑을 런타임 기준값 또는 필수 fallback으로 사용하지 않는다. KIS가 필수 항목을 제공하지 않거나 응답이 누락·오류·오래됨·상충하면 임의 보정 없이 해당 입력을 차단한다.

KIS VTS 모의계좌에서 수집한 실제 시장데이터는 **REAL_VTS 원본**으로 취급한다. REAL_VTS는 Live 데이터가 아니며 Live E2E PASS를 의미하지 않는다.

운영 저장 루트:

`data/kis_market_data_restart/YYYY-MM-DD/`

날짜별 partition은 누적되는 실제 시장 데이터 stream의 저장 단위다. 기존 데이터를 덮어쓰지 않고 timestamp와 provenance를 보존한다.

REST와 WebSocket은 독립적인 수집 경계다.

- REST: 시장관측/Historical Store 원본
- WebSocket: raw frame 원본
- transport 간 source/provenance와 timestamp를 혼용하지 않는다.
- WebSocket 연결 성공만으로 frame 수신 PASS를 선언하지 않는다.
- Collector manifest/lifecycle 상태는 실제 raw/canonical evidence와 일치해야 한다.

## 4. Replay / E2E 검증

기본 검증 경로:

**Source → Runtime Input → Strategy Signal → Decision → Risk → OMS/Router → Virtual Execution → Position/PnL → Regression**

각 실행은 독립 Run ID와 독립 execution/position/strategy state를 사용한다. 이전 run의 주문·체결·포지션·PnL·strategy state를 다음 run에 재사용하지 않는다. High-Speed Replay도 원본 event timestamp의 순서와 시간관계를 보존한다.

REAL_VTS, DERIVED_SCENARIO, SYNTHETIC, VIRTUAL_EXECUTION provenance는 명확히 구분한다. 실제 signal이 관찰되지 않은 전략은 signal-driven execution lifecycle PASS를 선언하지 않는다. 테스트 fixture나 단위 테스트 PASS만으로 production 기능의 PASS를 선언하지 않는다.

## 5. Control Tower / Position / P&L

표준 read-model 경로:

**Authoritative Runtime / Execution / Position Read Model → Option Program Read Model → Control Tower API → UI**

UI는 Strategy/Core를 직접 호출하거나 누락된 데이터를 임의 생성하지 않는다.

Filled에서 UI까지의 연결:

**ExecutionReport → Position Group → Strategy Trade P/L → Strategy Card P/L**

Runtime execution과 Control Tower Read Model은 동일한 authoritative execution/position-group 상태를 바라보아야 한다. Account P/L과 Strategy Trade P/L은 의미가 다를 수 있으므로 임의로 동일하게 맞추지 않는다. Position open/closed와 Trade Ledger 상태가 불일치하면 별도 회계/read-model 검증 대상으로 취급한다.

## 6. 자동 E2E / Scheduler

기본 scenario pattern:

**trend_up → trend_down → mean_revert → high_volatility → low_volatility → shock**

Replay와 UI smoke 결과는 별도로 기록한다. Replay FAIL이어도 UI smoke를 실행한다. UI smoke FAIL이면 다음 pattern으로 회전하고, Replay만 FAIL이며 UI smoke가 PASS이면 같은 pattern을 재시도한다.

현재 scheduled UI smoke는 HTTP/API/UI contract 검증이며, 동일 replay와 runtime state를 대상으로 하는 실제 브라우저 DOM Playwright 검증과는 구분한다.

## 7. 옵션 위험 검사 상태

옵션 헤지 위험 설정 초안은 `config/risk/option-hedge-risk.v1.json`, 검증 모델은 `core/risk/option_hedge_risk_config.py`에 있다. **현재 설정은 `DISABLED_UNTIL_RUNTIME_INTEGRATION`이며 실제 주문 경로의 위험 차단 기능으로 간주하지 않는다.**

미완료 작업에는 다음이 포함된다.

- authoritative 매수호가·승수·수량·수수료·슬리피지를 반영한 Runtime 프리미엄 검사
- 정확한 레그별 만기 payoff/max-loss 계산
- 미청산 포지션과 실제 체결 원장을 연결한 중복 없는 계좌 전체 위험 집계
- 부분체결·거절·청산·만기 및 입력 누락/오류 회귀 검증
- Strategy 1 헤지 구조와 Strategy 3·4·5 선물 레그의 경제적 목적·위험 한도 확정

기존 공통 RiskConfig의 일일 손실 한도와 증거금 한도를 옵션 프리미엄/최대손실 한도로 재해석하지 않는다. 임시 설정 금액은 최종 운용 한도가 아니다.

## 8. 현재 검증 상태와 미완료 항목

**프로젝트 전체의 Strategy 1~9 Full E2E 또는 Live 준비 완료를 의미하는 PASS는 확인된 것으로 간주하지 않는다.** No.1278의 fail-closed 기준에 따라 증거가 확보되기 전까지 다음 항목은 미완료로 유지한다.

- Strategy 1~9 전체의 KIS 원천 → 입력 → 신호/계획 → 최종 admission lineage
- REAL_VTS signal → execution → Position/PnL 전체 경로
- 동일 3개월 replay와 동일 runtime state를 대상으로 한 실제 browser DOM Playwright 검증
- Strategy Trade P/L / Account P/L / Position open·closed 의미의 완전한 회계 정합성
- Collector manifest/lifecycle과 실제 raw/canonical evidence의 완전한 정합성
- KIS Live credential, capability 및 실제 Live E2E
- 옵션 위험 검사 Runtime enforcement 및 관련 회귀 검증

오프라인 검증 PASS나 VTS 결과는 Live 준비 완료를 증명하지 않는다. 전략별 lineage 증거가 없는 연결은 `NOT PROVEN`/`BLOCKED`로 유지한다.

## 9. Git 및 변경 관리

- `.env`, credential, token은 commit하지 않는다.
- 사용자 작업 중인 unrelated 변경을 임의로 수정하거나 함께 commit하지 않는다.
- 일회성 로그, cache 및 폐기된 Legacy 산출물은 저장소에 남기지 않는다.
- 변경 후 focused test와 필요한 E2E를 실행하고, `git diff --check` 및 `git status`를 확인한다.
- commit/push 후 원격 `Project200` HEAD가 해당 commit SHA를 가리키는지 확인한다.

README는 프로젝트 개요와 현재 검증 상태를 요약한다. 상세 작업 규칙은 [AGENTS.md](AGENTS.md), 실제 결정 상태와 실행 기록은 Notion의 최신 확정 Decision Log 및 질문과답변을 기준으로 한다.
