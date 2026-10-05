# TEST_HISTORY — 과거 테스트 정리 기록

## 현재 기준
이 저장소의 테스트는 과거 작업 과정의 보존물이 아니라 현재 production code와 현재 확정 계약을 보호하기 위한 최소 회귀 안전망으로 관리한다.

검증 판단 순서:
현재 코드 → 현재 확정 Decision Log → AGENTS.md → 현재 실제 데이터/source → 새로 작성한 검증

## 2026-10-05 대규모 테스트 정리
과거 개발·검증 과정에서 생성된 다수의 pytest 파일은 현재 기준의 authoritative regression asset으로 간주하지 않는다. 특히 과거 날짜, synthetic scenario, migration/replay 가정, 이미 폐기된 execution proposal, 중복 E2E harness는 현재 검증에서 제외한다.

삭제된 과거 테스트의 의미 있는 결과는 현재 기능의 증거로 재사용하지 않는다. 필요한 동작은 현재 production code를 기준으로 tests/strategy/에 새로 작성한다.

## 현재 테스트 역할
- tests/strategy/test_strategy1.py ~ test_strategy9.py: 전략별 핵심 현재 계약 2개 내외
- 공통 계약/안전/아키텍처 테스트: 전략 간 공유되는 fail-closed, identity, risk, execution, architecture 경계만 유지
- Control Tower/High-Speed 등 현재 운영 경계는 현재 계약을 직접 보호하는 경우 유지
- verification/current_strategy_replay.py: REAL_VTS 기반 실제 production path 검증. pytest PASS와 분리한다.

## 폐기 원칙
과거 테스트가 존재했다는 이유로 현재 전제가 유지되는 것으로 보지 않는다. 현재 계약이 필요하면 현재 baseline에서 새 테스트를 작성한다.

## 2026-10-05 2차 실행 — 최소 테스트 세트 재구성
- 과거 950개 수준의 테스트를 현재 기준으로 재분류하여, 전략별 새 테스트 9개 파일을 작성했다.
- Strategy 1~9 각각 2개씩, 총 18개 전략 테스트가 새로 작성되었다.
- 공통 안전망은 Architecture / Control Tower 핵심 / High-Speed 현재 환경 / Option Master identity / Risk fail-closed / Runtime identity / Virtual execution·Position provenance만 유지했다.
- 기존 역사성·synthetic·migration·중복 E2E·과거 adapter 테스트와 테스트 fixture는 RETIRE했다.
- 현재 물리적 Python 테스트 파일은 21개, pytest collection은 70개이다.
- 새 전략 테스트: 18 passed.
- 전략 + 공통 최소 회귀 세트: 70 passed, exit code 0.
- `git diff --check` 오류 없음.
- 과거 테스트 결과는 현재 기능의 증거로 재사용하지 않는다.
- REAL_VTS 5,000-tick Strategy 1~9 검증은 pytest와 별도로 `verification/current_strategy_replay.py`를 통해 수행한다.
