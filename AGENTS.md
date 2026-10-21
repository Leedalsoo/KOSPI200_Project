# AGENTS.md — KOSPI200 Project200 현재 작업 기준

## 1. 문서의 역할과 현재 기준

이 문서는 **현재 작업에 필요한 지속 기준만** 정의한다. 완료된 과거 작업의 상세 수치, 특정 실행 결과, 과거 BLOCKED/PASS 판정, 일회성 우선순위, 폐기된 기준은 기록하지 않는다.

프로젝트를 다시 참조할 때의 우선순위는 다음과 같다.

1. 현재 대화의 직접 지시
2. Notion `결정로그`의 최신 `상태=확정` 항목
3. 이 `AGENTS.md`
4. 현재 코드·실제 데이터/source·새 검증 결과

Notion `질문과답변`은 작업 연속성 및 실행 기록의 기준이다. 과거 Q&A/Decision Log는 변경 이력이나 원문 증거가 필요할 때만 참고한다.

### 새 전략 명세와 과거 기록의 경계

- Strategy 1~9의 과거 명세·분석·설계표·검증 결과·Q&A는 새 전략의 요구사항, 승인 또는 구현 지시로 사용하지 않는다. 과거 기록은 특정 사실·원문·테스트 증거가 필요할 때만 역사적 참고 자료로 활용하고, 현재 코드·최신 확정 기준·새 검증과 대조한다. 과거 PASS 결과를 현재 검증 결과로 재사용하지 않는다.
- 새 전략의 실행 기준은 별도로 작성하고 검증한 뒤 사용자가 승인한 버전의 명세다. 초안·코드 분석·기존 테스트는 승인된 명세가 아니다.
- 전략 코드화 전에 공통 lifecycle/state machine, 레그별 주문·부분체결·미체결·재가격·취소·만기·손익·계좌 위험·오류 복구를 명세하고, 완전성 체크리스트·상태 전이표·코드-명세-테스트 추적표·시나리오 검증을 완료한다.
- 상태·시세·체결·포지션이 불명확하거나 authoritative input이 누락/오래된 경우 임의 추정으로 주문하지 않고 fail-closed 및 BLOCKED/UNAVAILABLE 처리한다.
- 전략/아키텍처/데이터 기준 변경은 commit/push 전에 사용자 사전 승인을 받는다. Decision Log는 삭제하지 않고 폐기 시 상태를 `폐기됨`으로 변경해 근거를 남긴다. 다른 Notion 페이지 삭제는 사전 승인을 받는다.

현재 개발 단계는 **수집기 v2 재구성·검증**이다. 런타임 데이터 기준은 KIS API만 사용하며 KRX는 런타임 소스가 아니다. VTS 전용이고 KIS Live 및 주문·정정·취소·계좌·잔고·증거금 API는 명시 승인 전까지 금지한다. 장중 운영 가드 08:29~16:01에는 수집기와 수집 코드를 수정·중지·재시작하지 않는다. 모의 REST 요청 간격은 최소 1.25초다.

---

## 2. 절대 안전 기준

- 실제 KIS Live 주문을 실행하지 않는다.
- Live credential과 실제 Live market-data frame 증거가 없으면 Live E2E PASS를 선언하지 않는다.
- KIS VTS 모의계좌 자격정보와 Live 자격정보를 혼용하지 않는다.
- credential, token, `.env` 내용을 로그·Notion·Git에 기록하지 않는다.
- authoritative source가 없는 값은 고정값, 0/False, 추정값, synthetic 값으로 정상 runtime을 가장하지 않는다. 필요한 경우 `UNAVAILABLE` 또는 `BLOCKED`로 종료한다.
- Mock/Synthetic/DERIVED_SCENARIO 결과를 REAL_VTS 또는 Live 검증 결과로 표현하지 않는다.
- 검증할 수 없는 결과를 PASS로 표현하지 않는다.
- 실제 데이터·계정·파일의 손상/유실 가능성이 있거나 credential 노출 가능성이 있으면 즉시 중단하고 보고한다.
- 같은 오류가 연속 두 번 발생하면 동일한 우회 시도를 반복하지 않고 원인을 재분석한다.

---

## 3. 현재 표준 실행 경로

표준 실행 경로는 다음 경계를 유지한다.

**Market Data Source → Runtime Input → Strategy → Decision → Risk → OMS/Order Router → Broker → Execution → Position/Margin/PnL → Control Tower Read Model**

Control Tower는 감독·운영·read-model 계층이며 정상적인 주문 생성이나 전략 로직을 소유하지 않는다.

표준 코드 경계:

- `contracts/` — 표준 계약·DTO·port
- `core/` — 환경 독립 domain·strategy·risk·OMS 규칙
- `application/` — orchestration·composition·Hub
- `environments/` — Virtual/Paper/Live/High-Speed 구현
- `infrastructure/` — KIS/KRX 등 외부 adapter/source
- `interfaces/` — Control Tower 및 외부 API/UI
- `tests/` — 실행 가능한 회귀·통합 검증

Legacy 구현을 새 표준 경계에 다시 연결하지 않는다. 필요한 기능은 현재 표준 경계로 명시적으로 이관하고, 이관 완료 후 호출자가 없는 Legacy 구현은 별도 검토 후 제거한다.

---

## 4. Strategy / Common Analytics 기준

Strategy 1~9는 각각 독립적인 Strategy Plugin/Registry 경계를 유지한다.

공통 시장지표와 공통 계산은 Common Analytics가 소유하고 표준 `AnalyticsSnapshot`으로 제공한다. Strategy는 명시된 Strategy Plugin Contract를 통해 이를 소비하며 동일 의미의 공통 계산을 Strategy 내부에서 다시 만들지 않는다.

Strategy가 소유하는 범위는 전략 고유의 진입·청산·헤지·상태전이·포지션 규칙이다.

공통 계산 또는 Runtime Input의 authoritative source가 없으면 임의의 대체값으로 정상 신호를 만들지 않는다.

---

## 5. Source / Instrument / Broker 계약

시장데이터 경계는 다음과 같다.

**Broker Adapter / Historical Provider / Other Provider → MarketDataHub → Runtime / Strategy**

Option Master, Quote, OrderBook, Execution에서 사용하는 계약 identity는 authoritative source의 동일한 계약 identity를 따라야 한다.

종목 identity, expiry, strike, option type, broker symbol, contract multiplier는 authoritative source 없이 추정하지 않는다.

quote/mark와 fill price를 혼용하지 않는다.

Broker Adapter는 broker별 authentication, rate limit, transport, symbol mapping, capability를 내부에 격리하고 Standard Core에 broker-specific 구현을 유출하지 않는다.

Virtual 환경은 다음 경계를 따른다.

**Virtual Exchange → Virtual Broker → Virtual Broker API → Option Program**

향후 다른 broker를 연결할 때도 동일한 표준 Port를 사용한다.

---

## 6. Multi-Leg Execution / Provenance

표준 Multi-Leg 실행 경계는 다음과 같다.

**MultiLegExecutionPlan → ExecutionLeg → OrderIntent → Risk → OMS/Order Router → Broker → ExecutionReport**

각 execution leg에는 다음 provenance를 보존한다.

`strategy_id → group_id → leg_id → client_order_id → execution_id`

Position provenance는 run_id, instrument identity, strategy/group/leg, client_order_id, execution_id, position role, remaining quantity를 보존한다.

partial close는 FIFO로 처리하고 reversal은 기존 lot을 먼저 소진한 뒤 초과분만 신규 lot으로 처리한다.

Insurance role은 필요한 경우 명시적으로 구분한다.

---

## 7. REAL_VTS 데이터 기준

KIS VTS 모의계좌에서 수집한 실제 시장데이터는 **REAL_VTS 원본 데이터**로 취급한다. 이는 Live 데이터가 아니며 Live E2E PASS를 의미하지 않는다.

현재 운영 저장 루트는 다음으로 고정한다.

`data/kis_market_data_restart/YYYYMMDD/`

거래일별 partition의 raw/canonical observation, manifest, status, heartbeat 및 관련 evidence는 source/provenance와 함께 보존한다.

REST와 WebSocket은 서로 다른 수집 경계로 유지한다.

- REST: 시장관측/Historical Store 원본
- WebSocket: raw frame 원본
- 두 transport의 provenance와 timestamp를 섞지 않는다.
- WebSocket 연결 성공만으로 frame 수신 PASS를 선언하지 않는다.
- REST/WS 비교는 각 source time과 received/collected time을 구분하여 동일 KST 장중 시간축에서 실제 frame evidence로 판단한다.
- 한 transport의 시작/종료 시각만으로 다른 transport의 품질이나 시장 종료를 추정하지 않는다.

KIS VTS Collector의 manifest 상태는 실제 raw/canonical evidence와 일치해야 한다. manifest와 실제 evidence가 불일치하면 collector lifecycle/상태 기록 문제로 분류하여 별도로 검증한다.


### KIS 단일 기준 및 공통 데이터 계약 (확정 정책)
- REST와 WebSocket의 실제 KIS 응답은 KIS adapter에서 검증·정규화하고, Strategy 1~9 및 공통 Analytics/Runtime이 동일한 canonical data model을 사용한다. 전략별로 원본 응답을 직접 파싱하거나 별도 계약 identity/만기/달력을 만들지 않는다.
- 데이터 누락, API 오류, identity 불일치, 오래된 데이터, 파싱 실패, 시간 역전 또는 검증 실패를 0/False/고정값/요일 추정/다른 출처 값으로 보정하지 않는다. 영향받는 계약·입력만 차단하고 상태와 원인을 명시한다.
- 관측값마다 원본 응답 또는 원본 frame, API/TR·transport 식별자, KIS 환경(VTS/Live), 수신 시각, 원본 source timestamp(제공 시), canonical schema/data version, master snapshot version/hash, 검증 결과와 실패 사유를 보존한다. 비밀키·토큰은 저장하지 않는다.
- 달력·만기·종목 identity·가격·호가·거래량을 제공하는 KIS API 경로는 항목별 capability matrix와 실제 응답으로 검증한다. KIS가 해당 항목을 제공하지 않는 경우 KRX로 우회하지 않고 `BLOCKED`/`UNAVAILABLE`로 보고한다.
- 이 정책은 시장 관측 데이터와 런타임 계약 기준정보의 출처 정책이다. 거래소 규칙(예: tick size/가격제한)은 관측 데이터와 분리된 규칙 명세로 취급하며, 해당 규칙의 출처·버전·적용 여부를 별도 검증한다. 이 항목은 KIS API에서 제공되는 시장 데이터라고 간주하지 않는다.



런타임 시장 데이터와 계약 기준정보의 유일한 외부 브로커 기준은 **KIS API/공식 KIS 종목 마스터**다. KRX 데이터·KRX 웹/API·KRX 캐시·KRX↔KIS 교차 매핑은 런타임 기준값, 필수 fallback 또는 계약 identity 보정에 사용하지 않는다. KIS가 필수 필드를 제공하지 않거나 응답이 누락·오류·오래됨·상충하면 임의 추정·보정·다른 출처 대체 없이 해당 계약/입력을 `UNAVAILABLE` 또는 `BLOCKED`로 처리하고 주문 경로를 차단한다.
---

## 8. REAL_VTS 연속 Replay / E2E

REAL_VTS는 특정 이틀이나 특정 파일로 고정하지 않고 **날짜별 partition이 이어지는 누적 연속 stream**으로 취급한다.

새 거래일 데이터가 수집되면 기존 데이터를 교체하지 않고 timestamp 순서로 누적하여 검증한다.

기본 검증 순서는 다음과 같다.

**Source → Runtime Input → Strategy Signal → Decision → Risk → OMS/Router → Virtual Execution → Position/PnL → Regression**

Strategy 1~9는 가능한 authoritative input 범위에서 각각 독립적으로 검증한다.

- 실제 signal이 관찰되지 않은 전략은 signal-driven execution lifecycle PASS를 선언하지 않는다.
- 실제 signal이 발생한 경우에만 Decision/Risk/OMS/Execution/Position/PnL의 해당 lifecycle을 실제 evidence로 연결하여 검증한다.
- 실제 signal을 만들기 위해 fixed/zero/false/synthetic/inferred authoritative input을 주입하지 않는다.
- 각 실행은 독립 Run ID와 독립적인 execution/position/strategy state를 사용한다.
- 이전 run의 주문·체결·포지션·PnL·strategy state를 다음 run에 재사용하지 않는다.
- High-Speed Replay은 실시간 의미가 필요한 경우를 제외하고 가속 실행을 기본으로 하며 원본 event timestamp의 순서와 시간관계를 보존한다.

REAL_VTS, DERIVED_SCENARIO, SYNTHETIC, VIRTUAL_EXECUTION provenance를 명확히 구분한다.

---

## 9. 현재 Control Tower 기준

Control Tower는 현재 다음 구조를 유지한다.

- 6개 운영 탭
- Strategy 1~9
- 3×3 동일 크기 Strategy Grid
- Strategy별 독립 Composition Graph
- Strategy Control의 USE / ENTRY / EXIT
- Strategy Trade P/L과 Account P/L의 분리
- 각 Strategy 카드의 월별 계약 Trade P/L: ENTRY → CLOSE/EXPIRY
- 카드 하단의 Strategy Integrated P/L
- Graph에서는 BUY/SELL trade value와 계약 구조를 표시하고 P/L을 계산하지 않는다.

UI는 직접 Strategy/Core를 호출하지 않는다.

표준 경로는 다음과 같다.

**Authoritative Runtime / Execution / Position Read Model → Option Program Read Model → Control Tower API → UI**

authoritative read model이 없으면 임의 데이터를 만들어 UI에 표시하지 않고 `UNAVAILABLE` 또는 `BLOCKED`로 표현한다.

---

## 10. 현재 Filled → Position → Trade P/L → UI 기준

실제 KIS VTS에서 발생한 Filled execution은 다음 경계를 통해 Control Tower에 반영되어야 한다.

**ExecutionReport → Position Group → Strategy Trade P/L → Strategy Card P/L**

Runtime execution과 Control Tower Read Model은 동일한 authoritative execution/position-group 상태를 바라보아야 한다. 서로 다른 bridge/registry instance를 만들어 execution state와 read model state가 분리되지 않도록 한다.

Strategy Trade P/L은 실제 execution/group provenance를 기반으로 계산한다. Account P/L과 Strategy Trade P/L은 의미가 다를 수 있으므로 임의로 동일한 값으로 맞추지 않는다.

Position의 open/closed 상태와 Trade Ledger의 CLOSE/EXPIRY 상태가 불일치하면 이를 정상으로 간주하지 않고 accounting/read-model semantics를 별도로 조사한다.

현재 Strategy 7의 실제 VTS Filled → Position → Strategy Trade P/L → Control Tower 연결은 확보된 검증 범위에 포함되지만, 이를 Strategy 1~9 전체의 Full E2E PASS로 확대 해석하지 않는다.

---

## 11. 3개월 자동 E2E / Scheduler 기준

3개월 자동 검증은 독립적인 Run ID와 결과 파일을 사용하고 순차 실행한다.

Scenario pattern은 다음 순서로 순환한다.

**trend_up → trend_down → mean_revert → high_volatility → low_volatility → shock**

Scheduled replay와 Control Tower smoke는 별도 결과로 기록한다.

현재 판정 규칙:

- Replay PASS + UI smoke PASS → 최종 PASS
- Replay FAIL → 최종 FAIL
- UI smoke FAIL → 최종 FAIL
- Replay가 FAIL이어도 UI smoke는 실행한다.
- UI smoke가 FAIL이면 다음 pattern으로 회전한다.
- Replay만 FAIL이고 UI smoke가 PASS이면 같은 pattern을 재시도한다.

현재 자동 UI smoke는 HTTP/API/정적 UI contract를 검증한다. **동일한 3개월 replay 실행 상태를 실제 브라우저 DOM Playwright로 직접 검증하는 것은 별도 미완료 항목**이며, 이를 현재 scheduler PASS와 동일한 증거로 취급하지 않는다.

Scheduler의 기존 실행 주기/큐잉 설정은 명시적인 변경 지시가 없는 한 임의로 변경하지 않는다.

---

## 12. P/L 및 실행 검증 원칙

테스트 파일의 PASS는 production 기능의 실제 동작 PASS와 동일하지 않다.

테스트 fixture/mock/expected value/assertion을 PASS를 만들기 위해 변경한 경우 해당 결과를 실제 기능 검증 evidence로 사용하지 않는다.

각 Strategy의 검증에서는 필요에 따라 다음을 분리하여 기록한다.

1. 테스트 결과
2. 실제 production execution path
3. REAL_VTS source/replay evidence
4. Runtime Input
5. 실제 Signal 또는 `NO_SIGNAL_OBSERVED`
6. Decision/Risk/OMS/Router
7. Virtual Execution/Fill
8. Position/PnL

Execution evidence가 없으면 Position/PnL을 추정하지 않는다.

---

## 13. Hub / Architecture 기준

- Strategy Hub: Strategy Registry/Orchestrator 및 strategy selection/lifecycle
- Runtime Hub: Runtime loop와 Strategy → Decision → Risk → OMS/Router
- Environment Hub: Environment Bundle lifecycle
- Run/Scenario Hub: RunContext, scenario/replay 선택, 독립 실행 상태
- Control Tower Hub: UI/API에 runtime status와 environment/운영 명령 제공

Strategy는 StrategyContext를 사용하며 KIS, VirtualBroker, Control Tower, Scenario Store를 직접 호출하지 않는다.

Hub 간 통신은 공개 `contracts/` 또는 명시된 application port를 사용한다. 새로운 private attribute 의존을 표준 경계로 추가하지 않는다.

Calendar의 거래일/휴장일 및 previous/next trading boundary 계산은 공통 MarketCalendarHub/MarketCalendarSnapshot 경계를 사용한다.

전략별 execution 특례가 계속 증가하면 Composition Root에 if-chain을 추가하는 대신 Strategy별 resolver/registry 경계로 분리하는 방향을 우선한다.

---

## 14. Architecture / Dependency 검증

`ARCHITECTURE_LINT_SPEC.md`에 정의된 dependency 규칙은 실행 가능한 검사로 유지한다.

현재 표준 경계를 벗어나는 import/dependency를 새로 추가하지 않는다.

변경 전 영향 범위를 확인하고, 변경 후 실제 diff의 영향 범위와 dependency 상태를 다시 확인한다.

Graft를 사용할 수 있으면 보조적인 코드 탐색·영향 분석에 사용한다. Graft 결과는 코드·AGENTS·Notion·실행 결과를 대체하는 authoritative evidence가 아니다.

Graft가 없거나 stale/실패해도 직접 코드 탐색과 테스트로 검증한다. Graft cache 및 일회성 분석 산출물은 commit하지 않는다.

---

## 15. 검증 절차

모든 검증은 현재 증거를 기준으로 한다.

기본 순서:

**Current Baseline → 최신 활성 Decision Log → AGENTS.md → 현재 코드/실제 데이터/source → 새 검증**

실행 전후 다음을 확인한다.

- `git status`
- 변경 파일 범위
- 실제 실행 명령과 exit code
- focused test
- 필요한 Virtual/REAL_VTS E2E
- `git diff --check`
- project gate가 필요한 경우 gate 실행
- 원격 branch HEAD

Windows Python 실행은 `py`를 사용한다.

판정은 반드시 실제 evidence에 따라 `PASS / FAIL / BLOCKED`로 구분한다.

---

## 16. 작업·Git 기준

작업 폴더에는 현재 구현과 유지에 필요한 파일만 둔다.

일회성 verification runner, 실행 로그, 검증 JSON, cache, 폐기된 Legacy UI 등은 저장소에 commit하지 않는다. 필요한 실행 결과는 지정된 verification 결과 영역과 Notion 기록 정책에 따라 관리한다.

`.env`와 credential은 절대로 commit하지 않는다.

작업은 다음 흐름을 따른다.

**현재 기준 확인 → 실제 코드/데이터 확인 → 영향 범위 확인 → 변경 → 검증 → diff/status 확인 → commit → push → 원격 HEAD 확인 → Notion 기록**

사용자가 명시적으로 작업을 지시한 경우 일반적인 코드·아키텍처·데이터 처리·검증 변경은 진행할 수 있다.

Commit/push 전에는 변경 범위가 의도한 것인지 확인한다. 사용자 작업 중인 unrelated 변경은 건드리거나 함께 commit하지 않는다.

Push 후 반드시 원격 `Project200` HEAD가 해당 commit SHA를 가리키는지 확인한다.

---

## 17. 현재 미완료 사항과 옵션 헤지 작업 상태

현재 작업 단계는 수집기 v2 재구성·검증이다. 2026-10-21 기준 S9 KIS master/expiry/quote 입력 경로의 로컬 검증 후보가 있으나, 이를 실제 Runtime/E2E PASS 또는 전략 구현 완료로 승격하지 않는다.

전체 프로젝트에서 실제 증거가 확보될 때까지 다음 항목은 완료로 승격하지 않는다.

- Strategy 1~9 전체의 REAL_VTS signal → execution → Position/PnL Full E2E
- 동일 3개월 replay 실행과 동일 runtime state를 대상으로 한 실제 browser DOM Playwright 자동 검증
- Strategy Trade P/L과 Account P/L 및 Position open/closed semantics의 완전한 회계 의미 정합성
- KIS VTS Collector manifest/lifecycle 상태와 실제 evidence의 완전한 정합성
- KIS Live credential 및 실제 Live E2E
- 옵션 실제 매수호가·승수·수량·수수료·슬리피지를 반영한 Runtime 프리미엄 검사
- 레그별 만기 손익·최대손실 계산과 미청산 포지션/체결 원장 기반 계좌 전체 위험 집계
- 부분체결·거절·청산·만기 시나리오를 포함한 실제 경로 회귀 검증
- Strategy 1 헤지 구조와 Strategy 3·4·5 선물 레그의 경제적 목적·위험 한도 최종 확정

기존 core/risk/risk_config.py의 max_daily_loss_krw = 10,000,000 및 max_margin_utilization_ratio = 0.85는 기존 공통 게이트로 유지한다. 이 값을 옵션 프리미엄 예산 또는 spread 최대손실 한도로 재해석하지 않는다.

옵션 헤지 설정 초안은 config/risk/option-hedge-risk.v1.json, 설정 모델은 core/risk/option_hedge_risk_config.py에 있다. 이 설정의 임시 금액과 모델 단위 테스트는 런타임 주문 차단을 입증하지 않는다. 설정은 DISABLED_UNTIL_RUNTIME_INTEGRATION 상태이며 실제 주문 경로에서 소비되는 것이 확인되기 전까지 enforcement 상태는 BLOCKED로 기록한다.

전략별 설계는 다음 원칙을 따른다.
- Strategy 1: Short PUT 보호를 위한 동일 만기·동일 option type의 Long PUT 등 defined-risk 구조를 후보로 검토한다. 실제 계약·수량·행사가 폭·비용·최대손실은 authoritative quote 계산과 별도 검증 전까지 미확정이다.
- Strategy 2 및 6~9: 기존 옵션 구조를 우선 보존하고 계약 identity, premium, payoff/max loss, 거래비용 및 계좌 전체 위험을 검증한다.
- Strategy 3: 동일 Futures identity를 사용하는 PRIMARY_ALPHA/SPREAD와 HEDGE 레그의 경제적 역할을 먼저 구분한다. 옵션으로 임의 대체하지 않는다.
- Strategy 4: 실제 옵션 position/contract와 Greeks를 제공하는 authoritative source 및 FUTURES rebalance/unwind 목적을 확인한다. Basecamp NON_EXECUTION 이벤트를 실제 옵션 체결로 취급하지 않는다.
- Strategy 5: OPTION BUY + MINI_FUTURES 5계약의 결합 목적을 별도로 확인한다. 선물 5계약을 옵션 수량으로 치환하지 않으며 기존 manifest를 승인 없이 수정하지 않는다.

공통 위험 검사 구현은 유효한 authoritative quote, contract multiplier, quantity, fees 및 conservative slippage를 사용한다. quote/expiry/identity/승수/비용/position provenance가 누락되거나 계산이 불가능하면 임의 대체하지 않고 fail-closed한다. 레그별 손익과 계좌 위험 집계는 체결 원장과 기존 미청산 포지션을 중복 계산하지 않도록 provenance 및 open quantity를 연결한다.

전략의 경제적 목적이나 위험 정책을 바꾸는 작업은 해당 설계·영향 파일·회귀 계획에 대한 명시 승인을 받은 뒤 수행한다. 현재 승인된 범위는 문서 기준 갱신 및 위 설계 방향이며, 전략 코드·manifest·실제 매매 정책을 임의로 변경하는 승인이 아니다.

## 18. 3개월 가상데이터 생성 기준 (필수)

3개월 가상데이터 생성은 가격 패턴을 흉내 내는 것보다 거래소 시장 구조와 계약 생명주기를 보존하는 것이 우선이다. 가상 가격·IV 경로는 시나리오에 따라 달라질 수 있지만 날짜, 거래일, 세션, 상품군, 계약 identity, 행사가, 만기, tick, 시간가치의 방향 및 데이터 provenance를 임의로 바꾸지 않는다.

### 18.1 기간·달력·세션
- 시작일은 선택된 authoritative Option Master 스냅샷 날짜이며 포함한다. 종료 경계는 시작일에 달력상 3개월을 더한 날짜이며 미포함이다. `date_end`는 마지막 생성 거래일, `date_end_exclusive`는 경계 날짜로 각각 명시한다.
- 거래일은 KIS 공식 API/응답으로 검증된 거래일 정보에서 결정한다. 주말 여부만으로 거래일·휴장일을 확정하지 않는다. 종료 경계 뒤의 월물 만기·롤오버를 판정하는 데 필요한 다음 연도 범위도 확인한다. KIS의 필요한 달력 정보가 없거나 출처·형식·신선도가 검증되지 않으면 KRX fallback 없이 fail-closed로 중단한다.
- KOSPI200 옵션 시간은 Asia/Seoul 기준으로 처리한다. 정규장은 08:45~15:45, 옵션 최종거래일은 15:20 종료를 적용한다. 5분 봉은 실제 세션 시작에 정렬하며, 만기 이후 바를 생성하지 않는다. 주간옵션은 각 계약의 정확한 만기일에 종료한다.
- 거래일 수, 바 수 및 이벤트 수는 달력·세션·실제 계약 커버리지에서 계산한다. 63거래일, 49,140건 등의 과거 샘플 수치를 생성 규칙의 상수로 사용하지 않는다.

### 18.2 상품·계약·만기 identity
- 일반 KOSPI200 옵션과 Mini KOSPI200 옵션을 구분하고, 이 프로젝트의 표준 옵션 데이터에는 지정된 일반 KOSPI200 상품군만 포함한다. Mini 계약 가격·행사가를 일반 계약의 spot 또는 계약으로 대체하지 않는다.
- instrument/code, 상품군, 콜/풋, 행사가, 계약월, 정확한 `YYYYMMDD` 만기 및 계약승수는 authoritative Option Master/source에서 가져온다. 계약 identity와 만기 변환은 공통 canonical expiry 경계를 사용한다.
- 월물·주간물·일물의 시작/종료 및 롤오버는 실제 거래일 달력과 authoritative 계약 마스터에 근거한다. 수집되지 않은 주간 만기, 행사 가격, instrument ID 또는 계약을 추정·복제해 coverage를 채우지 않는다. 누락된 계약은 `UNAVAILABLE`/`BLOCKED` 및 partial coverage로 명시한다.
- 초기 기초자산 가격은 동일 스냅샷 날짜에 대해 KIS 공식 API/마스터에서 검증된 정규 KOSPI200 선물 관측값을 사용하고 Mini 계약을 제외한다. KIS 응답에서 필요한 값과 날짜를 확인할 수 없거나 상충하면 KRX 데이터·고정 상수·후일 시세로 대체하지 않고 fail-closed 한다. API/TR, code, field, raw response reference/hash, snapshot version을 manifest에 남긴다.

### 18.3 가격·시간가치·시장 규칙
- 패턴 변경은 시나리오 기초자산 경로와 문서화된 IV 가정에만 영향을 준다. 금리·배당·가격 모형 등의 가정은 manifest에 명시하고, 실제 거래소 관측 가격인 것처럼 표시하지 않는다.
- 만기까지 남은 시간은 각 관측 timestamp와 계약별 정확한 만기시각을 사용해 계산한다. 고정된 spot, strike, IV 및 기타 입력 조건에서 시간 경과만으로 옵션 시간가치/이론가가 증가하지 않는다는 불변식을 테스트한다.
- 옵션 호가는 KRX tick에 맞춘다. 현재 기준: 프리미엄 10포인트 미만 0.01포인트, 10포인트 이상 0.05포인트. bid/ask는 양수이며 ask가 bid보다 커야 한다.
- KRX 옵션 가격제한(기준가격 대비 ±8%, ±15%, ±20% 단계)은 계약별 authoritative 기준가격과 해당 규칙 구현이 모두 확인될 때만 PASS 판정한다. 그 입력이 없으면 `market_rule_limitations`에 누락 사유를 명시하고 결과를 `PASS_WITH_LIMITATION`으로 기록한다. 이를 거래소 주문·체결 규칙 완전 준수 또는 실거래 가능 호가라고 표현하지 않는다.
- 모든 생성 행은 `DERIVED_SCENARIO` provenance와 Option Master/source hash를 보존한다. Synthetic/derived price는 REAL_VTS 또는 Live market data와 동일시하지 않는다.

### 18.4 생성 직후 사전검증과 스케줄러
- 각 스케줄 실행은 해당 패턴의 새 3개월 데이터 생성 후 replay 전에 validator를 실행한다. validator는 기간·달력·세션·timestamp·계약 identity·만기·source hash·초기 spot provenance·tick·시간가치·연속 ID·실제 이벤트 수 및 coverage를 확인한다.
- 생성/검증이 실패하거나 authoritative contract가 누락된 경우 전략 replay를 시작하지 않고 `BLOCKED_DATASET_VALIDATION` 또는 구체적 `UNAVAILABLE` 상태와 증거를 기록한다. 검증 결과 JSON에는 rules version, 기간, 패턴, seed, 거래일/이벤트 수, provenance, 제한사항을 남긴다.
- Scheduler는 사용자가 명시적으로 변경을 승인하지 않는 한 중단·비활성화·재등록하거나 주기를 변경하지 않는다. Task 이름과 실제 repetition interval이 다르면 이를 보고하고 별도 승인 없이 수정하지 않는다.
- 테스트는 생성 규칙의 불변식을 검증한다. 테스트 fixture나 기대값을 조정해 실제 생성·replay 실패를 PASS로 바꾸지 않는다. 데이터 validator PASS와 Strategy 1~9의 전체 E2E PASS는 서로 다른 판정이며 혼동하지 않는다.

이 규칙의 상세 계약 문서는 `docs/synthetic_3m_data_contract.md`, 생성기는 `scripts/generate_authoritative_option_synthetic_3m.py`, validator는 `scripts/validate_authoritative_option_synthetic_3m.py`, 스케줄 runner는 `verification/scheduled_3m/run_3m_pattern_e2e.ps1`이다. 이 규칙과 충돌하는 변경은 실행 전에 사용자 지시 및 최신 확정 Decision Log와 대조한다.

## 19. 옵션 헤지 위험 검사 구현 계획 (현재 작업 기준)

이 절은 옵션 헤지 관련 이전의 임시/초안 상태를 현재 기준으로 정리한다. 아래 작업이 실제 production 경로와 회귀 증거로 확인되기 전에는 완료로 표시하지 않는다.

### 19.1 필수 위험 계산
- 옵션 매수 프리미엄은 authoritative ask × 계약 multiplier × 수량으로 계산하고, 수수료와 보수적 슬리피지를 포함한다. 매도 레그는 매도 체결 가정과 비용을 별도로 반영하며 단순 net credit만으로 최대손실을 판정하지 않는다.
- 각 옵션 레그의 option type, strike, exact expiry, side, quantity, multiplier 및 authoritative quote를 검증한다. Mini KOSPI200 옵션은 일반 KOSPI200 옵션의 계약·spot 대체재로 사용하지 않는다.
- 만기 payoff는 모든 레그의 만기 손익과 수량을 결합하여 계산하고, spread/strategy의 최대손실을 별도로 산출한다. 정의된 위험 구조가 아닌 포지션은 최대손실이 제한되어 있다고 가정하지 않는다.
- 계좌 위험은 기존 미청산 position lot과 실제 체결 원장을 기준으로 산출한다. 동일 체결·잔여 수량을 포지션과 원장에서 중복 합산하지 않으며 부분 청산 이후 잔여 수량을 보존한다.
- premium, max loss, margin, bid/ask width, quote freshness, slippage, commission 및 concurrent exposure의 한도는 외부 설정에서 읽는다. 임시 숫자는 사용자 승인 전까지 최종 운용 기준이 아니며 실제 계좌 잔고/시세에서 나온 값으로 표현하지 않는다.
- 계산 입력이 누락되거나 상충하거나 오래된 경우, 계산이 실패한 경우에는 주문을 허용하지 않고 구체적 BLOCKED/UNAVAILABLE 원인을 기록한다.

### 19.2 구현 순서 및 회귀 범위
1. Strategy 1 헤지 구조와 Strategy 3·4·5 선물 레그의 목적·위험 한도를 분리해 설계하고, 미확정 항목은 사용자 결정 대상으로 보고한다.
2. 실제 매수호가·승수·수량·수수료·슬리피지 기반 프리미엄 검사 및 옵션 레그별 만기 payoff/max-loss 계산을 구현한다.
3. 기존 open positions, execution reports/fills, remaining position lots 및 trade ledger를 연결해 계좌 전체 위험을 집계한다.
4. 부분체결, 주문 거절, 부분/전체 청산, 만기 정산, 중복 체결, 누락/오래된 호가, 계산 실패를 회귀 검증한다.
5. focused tests 이후 Virtual execution path와 필요한 end-to-end evidence를 확인한다. 단위 테스트 PASS만으로 runtime enforcement PASS를 선언하지 않는다.

### 19.3 기존 기준과의 경계
- 기존 공통 RiskConfig의 일일 손실 및 증거금 한도는 의미를 바꾸지 않는다.
- Strategy 5의 append-only Risk 진단 JSONL은 관측 전용이다. 진단 저장 성공/실패로 Risk 승인·거절, 주문 라우팅 또는 포지션 수명주기를 바꾸지 않는다.
- Strategy 5의 기존 manifest와 다른 보호 경로는 별도 승인 없이 수정하지 않는다.
- KIS Live 주문은 실행하지 않는다. REAL_VTS, DERIVED_SCENARIO, SYNTHETIC 및 VIRTUAL_EXECUTION provenance를 구분한다.


## 최신 통합 기준 정합성 및 현재 작업 상태 (2026-10-21)

- 현재 단계는 사용자 지정에 따라 **수집기 v2 재구성·검증**이다. Current Baseline은 상태 대시보드이며 지시 권한이 없다. 최신 기준은 현재 대화의 직접 지시, 최신 확정 Decision Log, 이 문서 순서로 확인한다.
- 2026-10-21 19:09 KST에 Decision Log 데이터 소스를 조회했다. 최신 관련 항목은 S9 scope 충돌 기록과 Strategy 1~9 quote-only 입력 경계/독립 입력 검증 기록이다. S9 scope 충돌 Decision Log 항목은 v0.5 설계 범위 승인과 v0.6 보정 초안 상태를 반영해 `정정됨`으로 갱신했다. 재조회에서 `정정됨` 상태와 최신 본문, Q&A No.1319 링크를 확인했다. 이 문서가 Notion의 결정을 대체하지 않는다.
- Strategy 1~9의 과거 명세·검증 결과는 현재 승인이나 구현 완료의 증거가 아니다. 신규 명세의 승인된 범위와 현재 코드/실제 데이터/새 검증 결과를 대조한다. 오프라인·synthetic·quote-only 입력 경계 PASS는 실제 VTS lifecycle 또는 Live 검증 PASS가 아니다.
- KIS API 및 공식 KIS 마스터만 런타임 권위 소스로 사용한다. KRX는 런타임 데이터 소스가 아니다. 필수 데이터, identity, timestamp, capability 또는 provenance가 누락·불일치·미검증이면 fail-closed로 BLOCKED/UNAVAILABLE 처리한다.
- 이 갱신은 원격 `Project200`의 `AGENTS.md`에 남아 있던 S9 v0.4 충돌 및 단일 거래일 volume 설명을 정정한다. 명시적 사용자 승인에 따라 관련 문서만 stage/commit/push하며, 무관한 코드 변경·Graphify 산출물·미추적 파일은 커밋에 포함하지 않는다.

### 2026-10-21 S9 KIS 입력 및 범위 상태 — BLOCKED / local evidence

- **v0.5 설계 범위 승인:** 사용자의 직접 지시에 따라 v0.4 내부 상태 충돌을 새 버전 v0.5에서 명시적으로 정리했다. 파일 SHA-256 `8729F2E615EC4256550DCBC3B937BBCEBD04AAE33033B5E385045B9F94524768`. 원본 v0.4 SHA-256 `3D1060BBCDBCCF29E4FC0025559A15FFDB767C4C7C5BAAD81DB61085F37C2E24`는 변경하지 않고 보존한다. 이 승인은 설계 범위만 승인하며 Runtime 활성화·전략 구현·숫자 파라미터를 승인하지 않는다.
- **v0.6 보정 초안:** `docs/strategy_specifications/strategy_9_s1_put_insurance_spec_v0.6.md`, SHA-256 `0604AB4F9E85084384D42DDCE360D74C45E47CFEC4087B6898E49BD180205DD0`. 상태 DRAFT / VERIFYING. 사용자 검토·승인 전에는 Runtime 기준이 아니다.
- **원본 WebSocket 호가:** 20261015/20261016/20261020/20261021 네 거래일에서 `C01611880` 21,229건, `C01611882` 5,171건을 확인했다. 증거 `verification/evidence/track9_multiday_quote_quality_20261021.json`, SHA-256 `C47DEDBCE4E105605F19F34BB294D8014748D610643BF280D6845DCE11003D7B`.
- **KIS REST 거래량:** 5개 거래일에서 `C01611880`은 237, 77, 81, 34, 57이고 `C01611882`는 82, 11, 11, 7, 23이다. 증거 `verification/evidence/track9_multiday_kis_rest_daily_volume_20261021.json`, SHA-256 `DBE83BEB900A70FA869A0E5C1735BE3EB17D54094A9F6FA0D5E1B548278B72FE`. `min_volume=10`은 연구 후보일 뿐 Runtime 값은 null/unapproved다.
- spread/depth 연구 후보는 rank-4 spread <=10%, rank-3 spread <=15%, 양방향 cumulative top-five depth >=4계약이다. Source timestamp 의미와 `max_quote_age`는 미확정이며, 체결·부분체결·거절·슬리피지 및 holdout 검증 전에는 Runtime 기준으로 승인하지 않는다.
- `third_strike_insufficient_action=WAIT_AND_RECHECK`는 승인된 설계 범위 규칙이다. 동일 exact contract의 새 호가를 재확인하고 임의 가격 또는 대체 계약을 사용하지 않는다. 재시도 횟수·간격은 미확정이므로 실행 경로는 계속 BLOCKED다.
- 실제 S1 잔여 short PUT과 연결된 authoritative position/lot 및 execution provenance는 확인되지 않았다. `s1_put_link_ratio`는 null/BLOCKED다. 계좌·잔고·증거금 API는 호출하지 않는다. quote age, 최종 spread/depth, quantity rounding, initial limit price, repricing/cancel 정책도 미확정이다. 따라서 S9 Runtime 및 전략 구현은 계속 BLOCKED다.
- 2026-10-21 19:08 KST 상태 확인에서 `Project200-KIS-VTS-WebSocket-Collector` 예약 작업은 `Running`, 관련 PID 17800/13360/1228이 존재했다. `LastTaskResult=2147946720`의 의미는 미확인이다. 프로세스·스케줄러를 변경하지 않았다.
## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.

## 운영 프로토콜 (점검·과제 큐)

점검·과제 큐 관련 키워드를 처리할 때는 대화 기억이나 이전 보고만으로 현재 상태·큐를 판단하지 않는다. 매번 아래 두 Notion 페이지를 먼저 다시 읽고, 그 페이지의 절차와 현재 증거를 기준으로 진행한다.

- 통합 점검 지시문 v1: https://app.notion.com/p/3fb5f4f6eaa18107acbae513567306af?pvs=204
- 과제 큐 (현재): https://app.notion.com/p/3fb5f4f6eaa181efbccae9003d35aeee?pvs=204

적용 키워드: `상태점검`, `상태점검 간단`, `과제정리 No.xxxx`, `큐`, `승인 Qn`, `다음`, `보류 Qn`, `건너뜀 Qn`, `먼저 Qn`, `점검목록 ...`, `문턱 현황`.

- 키워드 실행 전에 두 페이지를 모두 읽는다. 어느 한 페이지라도 읽지 못하면 작업을 실행하지 말고, 읽지 못한 페이지와 오류를 보고한다.
- `상태점검`/`상태점검 간단`은 통합 점검 지시문 모드 A에 따라 직접 읽기 전용 점검을 수행하고, Q&A에 전체 결과를 기록한 뒤 재조회로 검증한다.
- `과제정리 No.xxxx`는 지정된 상태점검 페이지를 읽고 관련 현재 상태를 다시 직접 확인한 다음, 모드 B에 따라 과제를 우선순위화하고 `과제 큐 (현재)`를 갱신한다.
- `큐`는 `과제 큐 (현재)`를 다시 읽고, 읽은 시각과 각 상태별 개수를 포함해 표시한다. **과제 없음**이라고 보고할 때는 큐 URL, 읽은 시각, 상태별 개수를 반드시 함께 제시한다.
- `승인 Qn`은 큐의 해당 항목과 관련된 현재 상태를 재확인하고 승인 범위만 실행한다. 코드 수정·프로세스/스케줄 변경·삭제/이동·커밋/푸시는 해당 항목의 명시적인 `승인 Qn` 없이는 실행하지 않는다. 일반적인 작업 지시는 큐 항목 승인으로 대체하지 않는다.
- `다음`은 직전에 제안한 후보가 읽기 전용 또는 문서 작업인 경우에만 실행한다. 코드 수정·프로세스/스케줄 변경·삭제/이동·커밋/푸시 후보는 `승인 Qn`을 별도로 요구한다.
- 모드 A/B는 읽기 전용이다. 새 문제는 실행하지 않고 큐에 등록한다. 승인된 작업도 범위 밖 변경, 다른 파일, 미추적 파일을 포함하지 않는다.
- 실행 결과는 통합 점검 지시문에 지정된 Q&A 형식으로 기록하고, 재조회로 기록을 검증한다. Notion 기록이나 현재 증거를 실제로 확인하지 않았다면 완료로 보고하지 않는다.
