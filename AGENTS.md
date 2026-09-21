# AGENTS.md — KOSPI200 Project200 작업 기준

## 1. 프로젝트 목적
KOSPI200 선물·옵션 자동매매 시스템을 구축한다.
표준 실행 경로는 시장 데이터 → Runtime Input → Strategy → Decision → Risk → OMS/Router → Broker → Execution → Position/Margin/PnL → Control Tower Read Model이다.
Control Tower는 감독·운영 계층이며 정상 주문을 직접 만드는 주 실행 경로가 아니다.

## 2. 현재 개발 기준
기본 개발·통합 환경은 Virtual Trading이다.
Standard Core는 Virtual/Paper/Live/High-Speed 환경과 분리된 표준 계약을 사용한다.
현재 전략 계층의 공통 계산은 Common Analytics가 소유하고 Strategy는 전략 고유 의사결정만 담당한다.
Strategy 2~9의 Common Analytics 통합은 동일한 계약과 fail-closed 원칙으로 유지·검증한다.
실제 KIS 주문은 어떤 개발·검증 단계에서도 실행하지 않는다.

## 3. Common Analytics 기준
Common Analytics의 계산 결과는 표준 `AnalyticsSnapshot`으로 제공한다.
Strategy는 `AnalyticsSnapshot`과 명시된 Strategy Plugin Contract를 통해 공통 지표를 소비한다.
전략 내부에서 공통 지표를 다시 계산하거나 동일 의미의 별도 Runtime Input payload를 재생성하지 않는다.
Strategy 고유 진입·청산·헤지·상태 전이·포지션 규칙은 Strategy에 남긴다.
공통 계산의 authoritative source가 없으면 임의 계산·고정값·0/False·synthetic 값으로 대체하지 않고 `UNAVAILABLE` 또는 `BLOCKED`로 종료한다.
AnalyticsSnapshot은 immutable 경계를 유지하고 source/provenance를 보존한다.

## 4. authoritative source와 fail-closed
코드·문서의 존재만으로 PASS를 선언하지 않는다. 실제 실행·통합 검증 증거를 기준으로 판정한다.
authoritative source가 없으면 `BLOCKED`, `UNAVAILABLE`, `NotImplemented` 중 실제 상태를 명시한다.
값이 없다고 0, False, 고정값, 임의 계산값 또는 synthetic 값으로 정상 runtime을 채우지 않는다.
Mock/Synthetic 데이터를 실제 시장 검증으로 주장하지 않는다.
기존 generic 객체를 이름만 바꾸어 authoritative source로 승격하지 않는다.
종목 identity, expiry, strike, option type, broker symbol, contract multiplier는 authoritative source 없이 추정하지 않는다.
quote/mark와 fill price의 의미를 혼용하지 않는다.

## 5. 표준 코드 경계
`contracts/` → 표준 계약·DTO·port
`core/` → 환경 독립 domain·strategy·risk·OMS 규칙
`application/` → orchestration·composition·Hub
`environments/` → Virtual/Paper/Live/High-Speed 구현
`infrastructure/` → KIS/KRX 등 외부 adapter/source
`interfaces/` → Control Tower 및 외부 API/UI
`tests/` → 실행 가능한 회귀·통합 검증
Legacy 구현을 새 표준 경로에 다시 연결하지 않는다.
필요한 기능은 현재 표준 경계로 명시적으로 이관하고, 이관이 끝난 미사용 Legacy 코드는 제거한다.
## 6. 거래소·증권사·Broker API 경계
실제 환경: KRX 실제 거래소 → KIS 실제 증권사 → KIS API → Option Program
Virtual 환경: Virtual Exchange (KRX-like) → Virtual Broker (KIS-like) → Virtual Broker API → Option Program
Option Program은 거래소나 증권사의 내부 구현을 직접 호출하지 않고 Standard Broker API를 사용한다.

## 7. Multi-Leg 실행과 provenance
표준 경로는 MultiLegExecutionPlan → ExecutionLeg → OrderIntent → Risk → OMS / Order Router → Broker → ExecutionReport이다.
각 leg에 `strategy_id → group_id → leg_id → client_order_id → execution_id` provenance를 보존한다.
Virtual Position provenance는 lot 단위로 유지하고 run_id, instrument identity, strategy/group/leg, client_order_id, execution_id, position role, remaining quantity를 보존한다.
partial close는 FIFO, reversal은 기존 lot 소진 후 초과분만 신규 lot로 처리한다.
Insurance role은 `NONE / OVERNIGHT_INSURANCE / EVENT_INSURANCE / REHEDGE_INSURANCE` 중 명시적으로 부여한다.

## 8. 시장데이터·Historical·Replay
시장데이터 경계는 KIS Provider / Historical Provider / Other Provider → MarketDataHub → Runtime / Strategy이다.
Virtual 시장 데이터는 KRX 데이터 수집/정규화 → Historical Market Store → Virtual Exchange → Virtual Broker → Virtual Broker API → Option Program 경계를 따른다.
Historical Store의 source/provenance를 유지하고 거래일별 partition을 사용할 수 있어야 한다.
현재 일별 시장데이터 root는 `data/kis_market_data/YYYY-MM-DD/`이며 manifest와 상태 파일은 거래일·휴장일 모두 생성한다.
휴장일에는 시장데이터 JSONL을 생성하지 않는다.
Replay/Scenario/Synthetic 결과를 실제 KRX 데이터와 혼동하지 않는다.
실제 KRX Historical 데이터셋이 없으면 해당 실데이터 검증은 `BLOCKED`이다.

## 9. KIS Live 시장데이터 경계
KIS index-option realtime 거래/체결 TR은 `H0IOCNT0`, 호가 TR은 `H0IOASP0`를 사용한다.
VTS에서는 `H0IOASP0` 지원 범위를 실제 수신 증거로 확인하며 WebSocket 연결 성공만으로 옵션호가 수신 PASS를 선언하지 않는다.
Live 시장데이터 PASS에는 Live 자격증명과 실제 market-data frame 수신 증거가 모두 필요하다.
Live 검증 전까지 시장데이터 수신과 Virtual Execution을 주문 없이 검증한다.

## 10. VTS 실데이터 수집·Replay·E2E 검증
모의계좌에서 수집한 실제 시장데이터는 VTS E2E 검증용 원본 데이터 자산으로 축적할 수 있다.
일별 수집은 `infrastructure/kis/kis_vts_weekday_collector.py`의 Daily Session Orchestrator가 관리하며 REST 시장관측 수집기를 주 수집 경계로 사용한다.
`infrastructure/kis/kis_rest_market_observation_collector.py`는 Option Master의 `shrn_iscd`를 authoritative identity로 사용하여 Price/OrderBook을 수집한다.
`infrastructure/kis/kis_realtime_collector.py`는 WebSocket raw frame 경계이며 REST 수집과 독립적으로 동작한다. WS 연결 성공만으로 frame 수신 PASS를 선언하지 않는다.
WS가 실패하거나 approval-key timeout이 발생해도 REST 수집은 계속할 수 있으며 manifest에 `DEGRADED_REST_PRIMARY` 상태를 기록한다.
수집 데이터와 Replay 데이터의 source/provenance 및 원본/가공 여부를 명확히 보존한다.
거래일과 휴장일은 `data/kis_market_data/YYYY-MM-DD/`로 분리하며, authoritative calendar 조회 실패는 휴장으로 추정하지 않고 `UNKNOWN`으로 기록한다.
UNKNOWN 상태에서는 주문 endpoint를 호출하지 않고 read-only 시장데이터 경계만 시도할 수 있다.
원본 데이터는 실제 시간 흐름의 1배속 Replay로 먼저 검증하고, 이후 시간 압축 가속 Replay로 장시간 운용을 단시간에 반복 검증한다.
원본 데이터를 가공·변형하여 다양한 가격·변동성·호가·체결 패턴을 구성할 수 있으며, 변형 데이터는 실제 시장 원본과 명확히 구분한다.
등속과 가속 Replay를 모두 사용하고, 반복 실행마다 독립 Run ID와 상태를 사용한다.
VTS 검증은 Live 주문 검증이 아니며 실제 KIS 주문을 실행하지 않는다.
VTS 결과가 실제 Live E2E PASS를 의미하지 않으며, Live PASS에는 실제 Live credential과 실제 market-data frame 증거가 별도로 필요하다.

## 11. Runtime Input과 Strategy 정의
전략별 정의는 Notion의 사용자 요구사항과 실제 strategy 구현을 대조한다.
초기 진입 leg 방향, 사다리 조건, 만기 제한, 수량/자본 규칙, 필요한 Runtime Input을 각각 확인한다.
Runtime Input은 authoritative source에서 공급되어야 하며 source 계약과 provenance를 보존한다.
Common Analytics가 소유하는 값은 Strategy에서 중복 산출하지 않는다.
source가 없으면 정상 runtime을 가장하지 않고 fail-closed 한다.
Track별 완료·BLOCKED 상태와 입력 목록은 최신 Notion 작업 기록을 기준으로 확인한다.
## 12. Hub 경계
Strategy Hub는 Strategy Registry/Orchestrator와 strategy selection/lifecycle을 담당한다.
Runtime Hub는 Runtime loop와 Strategy → Decision → Risk → OMS/Router 연결을 소유한다.
Environment Hub는 Environment Bundle lifecycle을 담당한다.
Run/Scenario Hub는 RunContext, scenario/replay 선택, 독립 실행 상태를 담당한다.
Control Tower Hub는 UI/API에 runtime status, environment 정보, 운영 명령을 제공한다.
전략은 StrategyContext를 사용하며 KIS, VirtualBroker, Control Tower, Scenario Store를 직접 호출하지 않는다.
Hub 간 통신은 공개 `contracts/` 또는 명시된 application port를 사용하고 private attribute 의존을 새로 만들지 않는다.

## 13. 반복 실행 격리
반복 테스트는 매 실행마다 독립된 Run ID와 새 Environment Bundle/VSSF account/position/execution/strategy state를 사용한다.
이전 run의 주문·체결·포지션·PnL·strategy state를 다음 run에 재사용하지 않는다.
현재 테스트 숫자, 특정 checkpoint, 완료 Track 목록, 임시 우선순위는 이 문서에 고정하지 않고 Notion 상태 기록에서 확인한다.

## 14. Source → Runtime → Execution 검증
Authoritative source 연결은 source 계약 → composition → runtime 소비 → 실행 경계 순으로 확인한다.
Option Master, Quote, OrderBook, Execution의 계약단위와 instrument identity는 동일한 authoritative contract identity를 사용해야 한다.
Virtual Runtime에서 실제 source 연결과 Multi-Leg 실행 경계를 검증하며, source가 없는 leg는 fail-closed 한다.
Execution 결과가 없는 상태에서 Position/PnL을 추정하지 않는다.
Live credential이 준비되지 않은 경우 Live runtime evidence는 `BLOCKED`이며 Virtual 검증 결과로 대체하지 않는다.

## 15. 일별 수집 운영 기준
Daily Session Orchestrator는 KST 날짜를 기준으로 거래일·휴장일을 분리하고 `data/kis_market_data/YYYY-MM-DD/`에 날짜별 상태와 데이터를 저장한다.
거래일에는 장 시작 전 readiness/smoke를 수행하고, 장중 REST 수집을 계속하며 heartbeat를 기록한다.
휴장일에는 manifest와 상태만 생성하고 시장데이터 파일은 만들지 않는다.
동일 날짜 재시작은 기존 저장분을 보존하고 이어쓰기하며, 날짜 전환 시 새 Run ID와 날짜 partition을 사용한다.
REST 수집은 1 req/sec 제한을 준수하고 대상 계약별 결과와 라운드 소요시간을 manifest에 기록한다.
WebSocket은 보조 raw-frame 경계이며 실패·approval-key timeout이 REST 수집을 중단시키지 않는다.
토큰 값·credential 값은 로그, manifest, Notion, Git에 기록하지 않는다.
캘린더 조회 실패 또는 판정 불가를 휴장으로 단정하지 않고 `UNKNOWN`으로 기록한다.
UNKNOWN 상태에서 가능한 read-only 시장데이터 수집은 수행할 수 있으나 주문 endpoint는 호출하지 않는다.

## 16. 검증 절차
작업 시작 시 지정된 Notion 작업 기록, 원격 `Project200` 실제 코드, 로컬 working tree를 확인한다.
작업 전후 `git status`와 변경 파일을 확인한다.
TDD 변경은 테스트 작성/실패 관찰 → 최소 구현 → focused pytest → 필요한 Virtual E2E → `py -m pytest -q` → `git diff --check` → project200_gate → `git status` → 원격 HEAD 확인 → Notion 기록 순으로 진행한다.
Python은 Windows launcher `py`로 실행한다.
실제 명령·출력·exit code를 기준으로 PASS / FAIL / BLOCKED를 판정한다.
FAIL 또는 BLOCKED를 PASS처럼 표현하지 않는다.

## 17. 문서·Git 관리
Notion `질문과답변`은 작업 연속성의 기준 기록이다.
의미 있는 구현·정리·검증은 `[No.xxx 답변내용요약]` 페이지에 목적, 변경 내용, 검증 명령/결과, exit code, commit SHA, push 상태, 남은 BLOCKED 사항을 기록한다.
AGENTS.md와 PROJECT_STATUS.md에는 테스트 숫자, 특정 checkpoint, 완료 Track 목록, 임시 우선순위를 고정하지 않는다.
작업 폴더에는 현재 구현과 유지에 필요한 파일만 둔다.
단계별 기록, 일회성 verification runner, 실행 로그/검증 JSON, 캐시 및 폐기된 Legacy UI는 저장소에 두지 않는다.
`.env` 및 credential은 절대로 commit하지 않는다.
commit/push는 변경 범위가 의도한 상태이고 검증이 PASS일 때 수행한다.
단, project200_gate의 다른 모든 항목이 PASS이고 runtime_evidence_probe만 Live credential 미완비로 BLOCKED인 경우는 예외로 commit/push할 수 있다.
Push 후 원격 `Project200` HEAD가 해당 commit SHA를 가리키는지 확인한다.
## 17. 절대 금지
실제 KIS 주문 실행
Live credential 또는 market-data frame이 없는 상태에서 Live E2E PASS 선언
authoritative source가 없는 값을 임의 fallback으로 정상 runtime에 주입
Mock/Synthetic 결과를 실제 시장 검증으로 표현
private attribute 의존을 새로운 표준 경계로 추가
Legacy 경로를 새 표준 경계에 재연결
