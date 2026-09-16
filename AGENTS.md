# AGENTS.md — KOSPI200 Project200 작업 지침

## 1. 프로젝트 목적

KOSPI200 선물·옵션을 대상으로 하는 **자동매매 시스템**을 구축한다.
핵심은 사람이 주문 버튼을 누르는 UI가 아니라, 시장 데이터부터 전략·Risk·OMS·Broker·체결·포지션·PnL까지 이어지는 자동 실행 경로다.

표준 실행 흐름은 다음과 같다.

```text
Market Tick
→ Strategy Input
→ Strategy
→ Orchestrator
→ Signal / Execution Intent
→ Risk
→ OMS / Order Router
→ Broker
→ Execution Report
→ Position / Margin / PnL
→ Control Tower projection
```

Control Tower는 감독·운영 계층이다.
정상 주문을 직접 만드는 주 경로가 아니며 start/stop/restart, kill switch, panic halt, 상태·체결·포지션·PnL 확인을 담당한다.

## 2. 환경 원칙

동일한 Standard Core를 다음 Environment Bundle로 교체·검증할 수 있어야 한다.

1. High-Speed Test
2. Virtual Trading
3. Paper Trading
4. Live Trading

현재 개발·통합 검증의 기본 환경은 **Virtual Trading**이다.
Paper/Live의 외부 KIS 연결과 실제 주문은 별도 안전 조건을 충족하기 전까지 실행하지 않는다.

## 3. 사실성·권위 소스 원칙

- Mock/Synthetic 데이터로 실제 검증을 했다고 주장하지 않는다.
- 종목 identity, 계약 만기, strike, option type, broker symbol, contract multiplier 등은 authoritative source 없이 추정하지 않는다.
- 실제 source가 없으면 명시적으로 `BLOCKED`, `UNAVAILABLE`, `NotImplemented`로 표현한다.
- fill price를 quote/mark의 임의 대체값으로 사용하지 않는다.
- 전략 입력은 실제 Virtual Runtime source에서 공급하고 fixture fallback을 숨겨 사용하지 않는다.
- 각 leg의 `strategy_id → group_id → leg_id → client_order_id → execution_id` provenance를 보존한다.

## 4. Multi-Leg 원칙

Multi-leg 전략은 `MultiLegExecutionPlan → ExecutionLeg → OrderIntent → Risk → OMS/Router → Broker → ExecutionReport`의 표준 경로를 사용한다.

2-leg 또는 4-leg 그룹을 검증할 때 다음을 각각 확인한다.

- 모든 leg가 동일한 group_id를 가진다.
- leg_id와 client_order_id가 중복되지 않는다.
- 실제 leg별 instrument identity와 quote를 사용한다.
- Risk 승인과 주문 provenance가 leg별로 보존된다.
- 체결 후 Position은 VSSF의 권위 있는 상태를 반영한다.
- Group PnL은 검증된 leg PnL의 합으로 계산한다.

## 5. 검증 원칙

AI나 이전 작업 기록의 PASS 선언만으로 완료를 인정하지 않는다.
실제 작업 폴더에서 명령, 출력, exit code를 직접 확인한다.

기본 검증 순서는 다음과 같다.

```text
영향 범위 확인
→ focused pytest
→ 필요한 실제 Virtual E2E 실행
→ py -m pytest -q
→ git diff --check
→ project200_gate
→ git status
```

검증 결과는 `PASS / FAIL / BLOCKED`로 구분한다.
FAIL 또는 BLOCKED를 PASS처럼 표현하지 않는다.

## 6. 코드 구조 원칙

- `contracts/`: 표준 계약·DTO·port
- `core/`: domain, strategy, risk, OMS의 환경 독립 규칙
- `application/`: orchestration과 composition
- `environments/`: Virtual/Paper/Live/High-Speed 구현
- `infrastructure/`: 외부 KIS·KRX 등의 adapter/source
- `interfaces/`: Control Tower 및 외부 API/UI 경계
- `tests/`: 현재 코드에 대한 실행 가능한 회귀·통합 검증

Legacy 구현을 새 경로에 다시 연결하지 않는다.
기능 보존이 필요하면 현재 표준 경계에 맞게 명시적으로 이관한다.

## 7. 문서·파일 관리

Notion `질문과답변`이 작업 연속성의 기록이며, 작업 폴더에는 현재 구현과 유지에 필요한 문서만 둔다.
과거 단계별 작업 기록, 임시 검증 문서, 중복 테스트 설명서는 Notion 기록으로 보존하고 저장소에서는 제거한다.

다음은 저장소에 두지 않는다.
- `Process/` 단계별 작업 기록
- `.pytest_cache/` 등 실행 캐시
- 일회성 verification runner
- 실행 로그 및 생성된 검증 JSON
- 폐기된 Legacy UI

`.env`와 credential은 절대로 commit하지 않는다.
KIS master 원본처럼 현재 source로 사용되는 외부 자료는 코드에서 실제 참조 여부를 확인한 후 별도로 관리한다.

## 8. Git 규칙

작업 전후 `git status`와 변경 파일을 확인한다.
민감정보·캐시·임시파일을 commit하지 않는다.

테스트가 PASS하고 변경 범위가 의도한 상태일 때만 commit/push한다.
원격 기준 브랜치는 `Project200`이며, push 후 반드시 원격 HEAD가 해당 commit SHA를 가리키는지 확인한다.

## 9. Notion 기록 규칙

의미 있는 구현·정리·검증 작업은 Notion `질문과답변` 아래 `[No.xxx 답변내용요약]` 페이지에 기록한다.
기록에는 목적, 실제 변경 내용, 검증 명령과 결과, exit code, Git commit SHA, push 상태, 남은 BLOCKED 사항을 포함한다.

## 10. 현재 방향

현재 우선순위는 Virtual 자동매매 폐쇄루프의 사실성을 높이는 것이다.
특히 9개 Strategy Runtime Input의 authoritative source와 Multi-Leg의 instrument identity, option quote, contract multiplier, grouped Position/PnL, Control Tower provenance를 순서대로 완성·검증한다.

Real KIS 주문은 실행하지 않는다.
Virtual에서 충분한 실제 실행 증거를 확보한 뒤에만 다음 환경으로 이동한다.

## 11. 최신 검증 상태 및 Live 시장데이터 경계

2026-09-16 기준 최신 검증 결과를 다음과 같이 적용한다.

- Contract-level `Option Quote → OrderBook → Virtual Execution` 경로는 실제 코드와 테스트로 검증된 상태다.
- Virtual Multi-Leg 실행은 authoritative Option Master의 계약 identity와 계약별 `bid/ask/last`를 사용한다.
- BUY는 해당 계약의 Ask, SELL은 해당 계약의 Bid를 사용한다.
- Position/PnL mark도 동일 계약의 `last`를 사용하며 KOSPI200 기초자산 가격으로 대체하지 않는다.
- KIS 시장데이터는 `infrastructure/kis/futures_market_transport.py`의 WebSocket 경계를 통해 수신한다.
- KIS index-option realtime 거래/체결 TR은 `H0IOCNT0`, 호가 TR은 `H0IOASP0`를 사용한다.
- VTS에서는 `H0IOASP0` 실시간 옵션호가가 지원되지 않으므로 VTS WebSocket 연결 성공만으로 실제 호가 수신을 PASS 처리하지 않는다.
- Live 시장데이터를 실제로 검증하려면 Live 자격증명과 실제 market-data frame 수신 증거가 모두 필요하다.
- 현재 `.env`의 일반 KIS credential은 VTS 용도로 확인되었으며 Live credential로 간주하지 않는다.
- Live credential이 없는 상태에서는 `Live market data → Option Quote`를 `BLOCKED`로 판정한다.
- Real KIS 주문 API는 계속 금지한다. 시장데이터 수신 검증과 Virtual Execution은 주문 없이 수행한다.
- 실제 Live frame 수신 전에는 Live E2E `PASS`를 선언하지 않는다.

현재 우선 진행 경로는 다음과 같다.

```text
KIS Live WebSocket
→ authoritative Option Master identity mapping
→ contract-level Option Quote
→ contract-level OrderBook
→ Virtual Execution
→ Position / PnL
```

모든 검증은 이 AGENTS.md의 원칙에 따라 실제 작업 폴더의 명령·출력·exit code를 기준으로 판정한다.

## 12. 거래소 → 증권사 → Broker API → Option Program 구조 기준

프로젝트의 핵심 데이터 경계는 거래소와 Option Program을 직접 연결하는 구조가 아니다.
실제 환경은 다음 관계를 기준으로 한다.

```text
KRX 실제 거래소
→ KIS 실제 증권사
→ KIS API
→ Option Program
```

Virtual 환경은 이를 동일한 개념으로 모사한다.

```text
Virtual Exchange (KRX-like)
→ Virtual Broker (KIS-like)
→ Virtual Broker API
→ Option Program
```

Virtual Exchange는 KRX와 유사한 시장 데이터·체결·호가 구조를 제공한다.
Virtual Broker는 Virtual Exchange 데이터를 수신하고 계좌·증거금·주문·체결·포지션·PnL 등 증권사 데이터를 결합하여 KIS-like API로 제공한다.

Option Program은 특정 거래소나 증권사의 내부 구현을 직접 알지 않으며 Standard Broker API만 사용한다.
KIS, KIS VTS, KIS Live 또는 다른 증권사를 연결할 때는 해당 증권사 API Adapter 계층을 교체하는 것을 기본 원칙으로 한다.

따라서 다음 구조를 잘못된 직접 연결로 간주한다.

```text
Exchange → Standard Exchange Port → Option Program
Exchange → Option Program
```

목표 구조는 항상 거래소 데이터가 증권사 계층으로 들어간 뒤 증권사 API를 통해 Option Program으로 공급되는 것이다.

No.474에서 검증된 `POST /api/environment/virtual_broker/order`는 이 Broker API 경계의 기반으로 유지한다.
No.495/496의 KIS VTS 검증 결과처럼 VTS와 Live의 외부 데이터 지원 범위는 실제 증거에 따라 `PASS / BLOCKED`로 구분한다.

Real KIS 주문은 계속 실행하지 않는다. 실제 Live market-data frame 수신 전에는 Live E2E PASS를 선언하지 않는다.
