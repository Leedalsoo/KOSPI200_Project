# AGENTS.md — KOSPI200 Project200 작업 지침

## 1. 프로젝트 목적

KOSPI200 선물·옵션 자동매매 시스템을 구축한다.
핵심 실행 경로는 시장 데이터 → 전략 입력 → 전략 → Decision → Risk → OMS/Router → Broker → Execution → Position/Margin/PnL → Control Tower Read Model이다.

Control Tower는 감독·운영 계층이다. 정상 주문을 직접 만드는 주 실행 경로가 아니며 상태 조회와 start/stop/restart, kill switch, panic halt 등의 운영 기능을 담당한다.

## 2. 환경 원칙

Standard Core를 Virtual/Paper/Live/High-Speed 환경에서 교체·검증할 수 있어야 한다.
현재 개발·통합 검증의 기본 환경은 Virtual Trading이다.
Paper/Live 외부 연결과 실제 주문은 별도 안전 조건을 충족하기 전까지 실행하지 않는다.

Real KIS 주문은 어떤 단계에서도 실행하지 않는다.

## 3. authoritative source와 fail-closed

- 코드·문서의 존재만으로 PASS를 선언하지 않는다. 실제 실행·통합 검증 증거가 있어야 한다.
- authoritative source가 없으면 `BLOCKED`, `UNAVAILABLE`, `NotImplemented`로 명시한다.
- 값이 없다고 0, False, 고정값, 임의 계산값 또는 synthetic 값으로 정상 runtime을 채우지 않는다.
- Mock/Synthetic 데이터를 실제 Live 검증으로 주장하지 않는다.
- 기존 generic 객체를 이름만 바꾸어 authoritative source로 승격하지 않는다.
- fill price를 quote/mark의 대체값으로 사용하지 않는다.
- 종목 identity, expiry, strike, option type, broker symbol, contract multiplier는 authoritative source 없이 추정하지 않는다.

## 4. 표준 코드 경계

`contracts/` → 표준 계약·DTO·port
`core/` → 환경 독립 domain·strategy·risk·OMS 규칙
`application/` → orchestration·composition·Hub
`environments/` → Virtual/Paper/Live/High-Speed 구현
`infrastructure/` → KIS/KRX 등 외부 adapter/source
`interfaces/` → Control Tower 및 외부 API/UI
`tests/` → 실행 가능한 회귀·통합 검증

Legacy 구현을 새 표준 경로에 다시 연결하지 않는다. 기능 보존이 필요하면 현재 표준 경계에 맞게 명시적으로 이관한다.

## 5. 거래소·증권사·Broker API 경계

실제 환경:

```text
KRX 실제 거래소
→ KIS 실제 증권사
→ KIS API
→ Option Program
```

Virtual 환경:

```text
Virtual Exchange (KRX-like)
→ Virtual Broker (KIS-like)
→ Virtual Broker API
→ Option Program
```

Option Program은 거래소나 증권사의 내부 구현을 직접 호출하지 않고 Standard Broker API를 사용한다. 증권사 교체는 해당 API Adapter 계층에서 처리한다.

## 6. Multi-Leg 실행과 provenance

표준 경로는 다음과 같다.

```text
MultiLegExecutionPlan
→ ExecutionLeg
→ OrderIntent
→ Risk
→ OMS / Order Router
→ Broker
→ ExecutionReport
```

각 leg에 대해 다음 provenance를 보존한다.
`strategy_id → group_id → leg_id → client_order_id → execution_id`

검증 시 모든 leg의 group_id 일치, leg/client_order 고유성, 실제 contract identity와 quote, Risk 승인, 주문 provenance, VSSF Position, 검증된 leg PnL 합산을 확인한다.

Virtual Position provenance는 lot 단위로 유지한다. `run_id`, instrument identity, strategy/group/leg, client_order_id, execution_id, position role 등의 불변 provenance와 remaining quantity를 보존하고 partial close는 FIFO, reversal은 기존 lot 소진 후 초과분만 신규 lot로 처리한다.

Insurance role은 `NONE / OVERNIGHT_INSURANCE / EVENT_INSURANCE / REHEDGE_INSURANCE` 중 명시적으로 부여하며 raw order-purpose 문자열을 사후 해석하지 않는다.

## 7. 시장데이터 및 Historical 원칙

시장데이터의 기본 경계는 다음과 같다.

```text
KIS Provider / Historical Provider / Other Provider
→ MarketDataHub
→ Runtime / Strategy
```

Virtual 시장 데이터는 다음 경계를 따른다.

```text
KRX 데이터 수집/정규화
→ Historical Market Store
→ Virtual Exchange
→ Virtual Broker
→ Virtual Broker API
→ Option Program
```

Historical Store의 source/provenance를 유지한다. 실제 KRX 데이터가 확보되지 않은 상태에서 KRX 데이터가 수집되었다고 간주하지 않는다. Replay/Scenario/Synthetic 결과도 실제 KRX 데이터와 혼동하지 않는다.

실제 KRX Historical 데이터셋이 없으면 해당 실데이터 검증은 `BLOCKED`이며, 코드 존재만으로 해결된 것으로 간주하지 않는다.

## 8. KIS Live 시장데이터 경계

KIS index-option realtime 거래/체결 TR은 `H0IOCNT0`, 호가 TR은 `H0IOASP0`를 사용한다.

VTS에서는 `H0IOASP0` 실시간 옵션호가가 지원되지 않으므로 WebSocket 연결 성공만으로 실제 옵션호가 수신 PASS를 선언하지 않는다.

Live 시장데이터 PASS에는 Live 자격증명과 실제 market-data frame 수신 증거가 모두 필요하다. 현재 Live credential이 없으면 Live market-data → Option Quote는 `BLOCKED`이다.

Live 검증 전까지 시장데이터 수신과 Virtual Execution을 주문 없이 검증한다.
## 9. Track9 현재 기준

Track9 Runtime Input 9개 중 현재 연결된 authoritative source:
- `iv_timeseries`
- `option_position_attribution`
- `insurance_position`
- `fee_ledger`
- `margin_read_model`

현재 `BLOCKED`인 잔여 source:
- `premium_attribution`
- `event_calendar`
- `event_budget`
- `risk_guard`

잔여 4개는 authoritative source를 먼저 계약 수준으로 정의하고 실제 source가 확보된 항목만 연결한다. 의미가 다른 기존 구현을 대체 source로 승격하지 않는다.

특히 TradingCalendar ≠ `event_calendar`, 일반 MarginEngine ≠ `margin_read_model`, RiskEngine kill switch/RiskApprovalReadModel ≠ Track9 `risk_guard`로 취급한다.

Track9 전체 9개 Runtime Input이 연결되기 전에는 Track9 전체 runtime PASS를 선언하지 않는다.

## 10. 현재 다음 작업 우선순위

1. Track9 잔여 4개 authoritative source 확보·계약·연결 여부 확인.
2. Track1/4/8의 남은 BLOCKED Runtime Input을 계약 → source → fail-closed 테스트 순서로 진행.
3. 실제 KRX Historical Market 데이터 확보 후 Track7 실데이터 검증 진행.
4. Legacy VSSF `position_manager.py` / `pnl_engine.py`의 `250000` 고정값 정리.
5. `CanonicalMarketTick` 중복 타입 통합 여부 재검토.
6. KIS VTS 실제 지수옵션 실시간호가 subscription 가능 여부와 KRX Data Marketplace 제공조건 확인.
7. Live credential 확보 후 `runtime_evidence_probe` 및 `project200_gate` 재검증.
## 11. Hub 경계

현재 Hub 경계는 기존 seam을 표준 공개 계약으로 감싸는 방향을 유지한다.

- Strategy Hub: Strategy Registry/Orchestrator와 strategy selection/lifecycle을 담당한다.
- Runtime Hub: Runtime loop와 Strategy → Decision → Risk → OMS/Router 연결을 소유한다.
- Environment Hub: Environment Bundle의 lifecycle을 담당한다.
- Run/Scenario Hub: `RunContext`, scenario/replay 선택, 독립 실행 상태를 담당한다.
- Control Tower Hub: UI/API에 runtime status, environment 정보, 운영 명령을 제공한다.

전략은 `StrategyContext`를 사용하며 KIS, VirtualBroker, Control Tower, Scenario Store를 직접 호출하지 않는다.
Hub 간 통신은 공개 `contracts/` 또는 명시된 application port를 사용하고 private attribute 의존을 새로 만들지 않는다.

반복 테스트는 매 실행마다 독립된 Run ID와 새 Environment Bundle/VSSF account/position/execution state를 사용한다. 이전 run의 주문·체결·포지션·PnL·strategy state를 다음 run에 재사용하지 않는다.

## 12. 현재 검증 상태

No.613 기준 최신 전체 회귀는 `626 passed`이며, Track9 focused 검증은 `37 passed`이다.

`project200_gate` 전체 판정은 Live credential 미완비에 따른 `runtime_evidence_probe` BLOCKED 때문에 FAIL일 수 있다. 이 경우 세부 gate 결과를 확인하며, 다른 항목이 모두 PASS이고 해당 항목만 Live credential 미완비로 BLOCKED이면 commit/push는 허용한다.

현재 Live credential 미완비 상태에서 Live E2E PASS를 선언하지 않는다.

## 13. 검증 절차

작업 전후 `git status`와 변경 파일을 확인한다.

```text
영향 범위 확인
→ focused pytest
→ 필요한 Virtual E2E
→ py -m pytest -q
→ git diff --check
→ project200_gate
→ git status
```

Python은 Windows launcher `py`로 실행한다. 실제 명령·출력·exit code를 기준으로 PASS/FAIL/BLOCKED를 판정한다.

FAIL 또는 BLOCKED를 PASS처럼 표현하지 않는다.
## 14. 문서·Git 관리

Notion `질문과답변`은 작업 연속성의 기준 기록이다. 의미 있는 구현·정리·검증은 `[No.xxx 답변내용요약]` 페이지에 목적, 변경 내용, 검증 명령/결과, exit code, commit SHA, push 상태, 남은 BLOCKED 사항을 기록한다.

작업 폴더에는 현재 구현과 유지에 필요한 파일만 둔다. 단계별 기록, 일회성 verification runner, 실행 로그/검증 JSON, 캐시 및 폐기된 Legacy UI는 저장소에 두지 않는다.

`.env` 및 credential은 절대로 commit하지 않는다.

commit/push는 변경 범위가 의도한 상태이고 검증이 PASS일 때 수행한다. 단, `project200_gate`의 다른 모든 항목이 PASS이고 `runtime_evidence_probe`만 Live credential 미완비로 BLOCKED인 경우는 예외로 commit/push할 수 있다. 이때도 Gate 전체 판정은 FAIL로 기록한다.

원격 기준 브랜치는 `Project200`이다. push 후 원격 HEAD가 해당 commit SHA를 가리키는지 확인한다.

## 15. 절대 금지

- 실제 KIS 주문 실행
- Live credential 또는 market-data frame이 없는 상태에서 Live E2E PASS 선언
- authoritative source가 없는 값을 임의 fallback으로 정상 runtime에 주입
- Mock/Synthetic 결과를 실제 시장 검증으로 표현
- private attribute 의존을 새로운 표준 경계로 추가
