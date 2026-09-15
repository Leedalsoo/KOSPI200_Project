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
