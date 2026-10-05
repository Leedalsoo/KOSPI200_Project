# TEST_HISTORY — 현재 테스트 기준 및 과거 정리 기록

## 현재 기준
이 저장소의 테스트는 과거 작업 과정의 보존물이 아니라 현재 production code와 현재 확정 계약을 보호하는 최소 회귀 안전망으로 관리한다.

검증 판단 순서:
현재 코드 → 현재 확정 Decision Log → AGENTS.md → 현재 실제 데이터/source → 새로 작성한 검증

과거 테스트 결과나 과거 문서의 PASS/BLOCKED 상태는 현재 기능의 증거로 재사용하지 않는다.

## 현재 테스트 구조
- tests/strategy/test_strategy1.py ~ test_strategy9.py: Strategy 1~9별 현재 핵심 계약 검증, 각 2개
- 공통 테스트: 현재 필요한 architecture / Control Tower / High-Speed / Option Master identity / risk fail-closed / runtime identity / virtual execution·position provenance 경계
- verification/current_strategy_replay.py: REAL_VTS 실제 production path 검증. pytest PASS와 별도 판정
- 현재 Git 추적 Python 테스트 파일: 22개

## 2026-10-05 대규모 테스트 정리
과거 개발·검증 과정에서 생성된 다수의 pytest 파일은 현재 기준의 authoritative regression asset으로 간주하지 않았다. 과거 날짜, synthetic scenario, migration/replay 가정, 폐기된 execution proposal, 중복 E2E harness 및 obsolete adapter 테스트는 현재 검증에서 제외했다.

필요한 동작은 현재 production code와 현재 확정 계약을 기준으로 tests/strategy/ 및 최소 공통 테스트로 새로 검증한다.

## 문서 정리 원칙
과거 조사·설계 과정의 기록을 현재 계약 문서처럼 유지하지 않는다. 현재 코드와 계약을 설명하는 문서만 정식 기준으로 유지하고, 일회성 조사·비교·process notes는 삭제하거나 필요한 내용만 현재 계약 문서에 반영한다.
