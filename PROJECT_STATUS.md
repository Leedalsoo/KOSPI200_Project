# PROJECT STATUS

## 역할
이 문서는 현재 프로젝트의 상태를 고정하는 단일 상태 저장소가 아니다. 최신 상태·검증 결과·우선순위는 Notion `질문과답변`의 최신 `[No.xxx 답변내용요약]`을 기준으로 하며, 실제 코드를 최우선 실행 증거로 사용한다.

## 현재 기준
- 기본 통합 환경: Virtual Trading
- 실제 KIS 주문: 개발·검증 단계에서 실행하지 않음
- 현재 검증의 authoritative 순서: 현재 코드 → 확정 Decision Log → `AGENTS.md` → 현재 실제 데이터/source → 새 검증
- Windows Python 실행: `py`
- Git 기준 브랜치: `Project200`
- credential과 `.env`: Git에 포함하지 않음

## 현재 테스트 구조
- `tests/strategy/test_strategy1.py` ~ `test_strategy9.py`: Strategy 1~9 현재 핵심 계약 검증
- 공통 테스트: 현재 필요한 architecture, identity, risk, execution, Control Tower, High-Speed 경계 보호
- `verification/current_strategy_replay.py`: 현재 REAL_VTS production path 검증
- pytest PASS는 실제 Strategy E2E PASS와 동일하지 않음

## 현재 데이터/검증 경계
현재 REAL_VTS 기준은 `data/kis_market_data_restart/YYYY-MM-DD/`의 실제 관측 데이터다. Synthetic/Scenario/Replay 결과는 실제 시장 데이터와 별도 provenance로 취급한다.

REAL_VTS 구간에서 실제 signal이 관찰되지 않으면 해당 Strategy의 전체 lifecycle을 PASS로 판정하지 않는다. target tick 미달, runtime error 또는 authoritative input 부재는 BLOCKED/INCOMPLETE로 처리한다.

## 문서 관리
- 작업 기준: `AGENTS.md`
- 계약/아키텍처 문서: 각 경계 문서와 `contracts/`
- 테스트 과정 기록: `TEST_HISTORY.md`
- 미래 설계: `docs/`
- `graft/`: 작업 효율화를 위한 보조 작업 구조이며 현재 정식 검증 근거와 분리한다.
