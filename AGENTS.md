# AGENTS.md — KOSPI200 Project200 현재 작업 기준

## 1. 문서의 역할과 현재 기준

이 문서는 **현재 작업에 필요한 지속 기준만** 정의한다. 완료된 과거 작업의 상세 수치, 특정 실행 결과, 과거 BLOCKED/PASS 판정, 일회성 우선순위, 폐기된 기준은 기록하지 않는다.

프로젝트를 다시 참조할 때의 우선순위는 다음과 같다.

1. 현재 대화의 직접 지시
2. Notion `결정로그`의 최신 `상태=확정` 항목
3. 이 `AGENTS.md`
4. 현재 코드·실제 데이터/source·새 검증 결과

Notion `질문과답변`은 작업 연속성 및 실행 기록의 기준이다. 과거 Q&A/Decision Log는 변경 이력이나 원문 증거가 필요할 때만 참고한다.

현재 개발 단계는 **Control Tower / Option Program / 실제 KIS VTS 연결 / 장기 E2E 검증**이다. Virtual/VTS 검증을 중심으로 진행하며 Live KIS 주문은 실행하지 않는다.

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

`data/kis_market_data_restart/YYYY-MM-DD/`

거래일별 partition의 raw/canonical observation, manifest, status, heartbeat 및 관련 evidence는 source/provenance와 함께 보존한다.

REST와 WebSocket은 서로 다른 수집 경계로 유지한다.

- REST: 시장관측/Historical Store 원본
- WebSocket: raw frame 원본
- 두 transport의 provenance와 timestamp를 섞지 않는다.
- WebSocket 연결 성공만으로 frame 수신 PASS를 선언하지 않는다.
- REST/WS 비교는 각 source time과 received/collected time을 구분하여 동일 KST 장중 시간축에서 실제 frame evidence로 판단한다.
- 한 transport의 시작/종료 시각만으로 다른 transport의 품질이나 시장 종료를 추정하지 않는다.

KIS VTS Collector의 manifest 상태는 실제 raw/canonical evidence와 일치해야 한다. manifest와 실제 evidence가 불일치하면 collector lifecycle/상태 기록 문제로 분류하여 별도로 검증한다.

Calendar authoritative source를 확인할 수 없으면 휴장으로 추정하지 않고 `UNKNOWN`으로 기록한다. `UNKNOWN` 상태에서 주문 endpoint를 호출하지 않는다.

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

## 17. 현재 미완료 사항의 표현 기준

현재 완료된 한정적 검증을 전체 시스템 완료로 확대하지 않는다.

현재 중요한 미완료 범주는 다음과 같다.

- Strategy 1~9 전체의 REAL_VTS signal → execution → Position/PnL Full E2E
- 동일 3개월 replay 실행과 동일 runtime state를 대상으로 한 실제 browser DOM Playwright 자동 검증
- Strategy Trade P/L과 Account P/L 및 Position open/closed semantics의 완전한 회계 의미 정합성
- KIS VTS Collector manifest/lifecycle 상태와 실제 evidence의 완전한 정합성
- KIS Live credential 및 실제 Live E2E

이 항목들은 실제 증거가 확보될 때까지 PASS로 승격하지 않는다.
