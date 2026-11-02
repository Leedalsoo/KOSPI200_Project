# Q25 A2-2 — A1-3 종료 판정 초안 및 A2-4 대장 L-15~L-19

- 작성일: 2026-11-02
- 상태: 판정표/대장 초안; A1-3 종료 선언은 보류
- PSB 판정 용어: `PSB_PASS`, `PSB_FAIL`, `UNVERIFIED`, `PLUMBING_ONLY`, `BLOCKED_*`를 구분한다.

## A1-3 증거 매핑

| 증거 | 관측 결과 | 판정 | 제한/남은 조건 |
|---|---|---|---|
| No.1375 — 53,550-event replay | fast/detailed 핵심 report 필드 일치, signals=0, orders/fills=0 | `PLUMBING_ONLY` — zero-signal report equality | 실제 StrategyHub 자연 신호 및 positive lifecycle 동등성 증거가 아님 |
| No.1376 — positive order/fill | validation-only fixture 1 event; order command 1, ExecutionReport 1, fill 1 | `PLUMBING_ONLY` | fixture 한 이벤트; 전체 replay/운영 freshness/production identity 검증 아님 |
| No.1378 — positive multi-event | 3 events; 첫 이벤트 signal/approval/route/fill 각 1; 14 비교 플래그 true | `PLUMBING_ONLY` | 3-event fixture only; strategy-level natural signal E2E 아님 |
| No.1379 — reject transition | `SUBMITTED → REJECTED`; 13 비교 플래그 true; focused tests 11 passed | `PLUMBING_ONLY` | deterministic rejecting adapter 기반 |
| No.1380 — partial fill | fill sequence 1→2→2, cumulative 1→3→5; 11 비교 플래그 true | `PLUMBING_ONLY` | test-only ExecutionReport 시퀀스 기반 |
| No.1382 — late fill race | 12 비교 플래그 true; cancel-confirm 후 late report는 `EXECUTION_BEFORE_ACK`로 거부 | `PLUMBING_ONLY` / lifecycle semantics 미확정 | fast/detailed equality만으로 late-fill business correctness를 확정하지 않음 |
| No.1386 — SQLite settlement boundary | SQLite 구현 관련 210 tests passed | A1-3 종료 근거로 사용하지 않음 | Live/SQLite 후속 활성화는 A2 완료 전 동결 |
| No.1387 A2-3-12 — S6 virtual input adapter | BUY_INSURANCE 신호 1건, 22 합성 검증 테스트 통과 | `PLUMBING_ONLY` | StandardRuntimeInputProvider 전체 Replay 미실행; report file/hash는 사용자 제공, 로컬 파일 동일성 미확인 |
| No.1387 A2-1 existing report | Strategy 6 signals=0; fast/detailed compared fields match; Freshness k sensitivity `NOT_RUN` | `BLOCKED_NO_NATURAL_SIGNAL` | 진입 게이트가 signal 평가 전에 차단. 자연 신호가 확인될 때까지 종료 불가 |

## A1-3 종료 기준

A1-3 종료는 현재 승인하지 않는다. 종료 전 필요한 증거:
1. 실제 StrategyHub Strategy 6 코드가 합성 입력으로 생성한 자연 신호(하드코딩/fixture/injected signal 제외).
2. 동일 입력에서 fast/detailed의 자연 신호 및 후속 lifecycle 동등성.
3. Freshness `k={1,2,3,6}` 민감도 실행(기본 k=2)과 결과 설명.
4. 실제 `StandardRuntimeInputProvider`를 사용하는 전체 Replay 경로 및 fail-closed 진입 게이트 회귀 검증.
5. 테스트 결과, 실제 코드 경로, provenance, 신호/주문/체결/포지션 증거를 구분해 기록.

## 대장 후보 L-15~L-19

| ID | 항목 | 상태 | 근거 / 다음 조건 |
|---|---|---|---|
| L-15 | 원격 재현성 및 전체 pytest | `PASS_LOCAL / BLOCKED_REMOTE` | clean checkout HEAD `4a00589f4e933a53b84104d6b067ab08ff6b9732`: 197 collected, 196 passed, 1 skipped, 4.89s, exit 0. 원격 branch는 아직 `d198a17`; push 별도 승인 대기 |
| L-16 | 누락 KIS WebSocket option identity resolver | `PASS_LOCAL / BLOCKED_REMOTE` | resolver는 로컬 ahead history의 `fa83a2d`에 포함; clean checkout 테스트 통과. 원격에 반영되기 전 원격 복구 완료로 보지 않음 |
| L-17 | Strategy 6 자연 신호 E2E | `BLOCKED_NO_NATURAL_SIGNAL` | 기존 S6 E2E signals=0; A2-3-12 adapter signal은 StandardRuntimeInputProvider 전체 replay 증거가 아님 |
| L-18 | Freshness 민감도 | `UNVERIFIED` | `k={1,2,3,6}` 미실행; 자연 신호 경로 도달 후 실행 |
| L-19 | 타이머 성능 기준선 | `BASELINE_ONLY` | 1,000 DERIVED_SCENARIO rows JSONL parsing + canonical tick construction: 0.02191s / 45,641.47 events/s. StrategyHub/Risk/OMS 성능으로 해석하지 않음 |

## A2-2 timer baseline 증거

- Report: `reports/synth/Q25_A2_2_TIMER_BASELINE_20261102.json`
- SHA-256: `65A2972F71E0E59A768DAA01AD99B22A395C6E96D38DDBD4BCC43FA05DDBDA73`
- 입력: 임시 `%TEMP%` 격리 디렉터리, 1,000 DERIVED_SCENARIO rows, JSONL SHA-256 `8F27AC5C28E904FAECC0258984D07BE48C50735C92C6081FA5200FE9E7E87290`.
- 종료 코드 0. 단일 측정이므로 통계적 성능 기준선/튜닝/운영 성능 보증이 아니다.

## 운영/안전 제한

- A2-0 로컬 commit/test 완료는 원격 반영 완료가 아니다. push 별도 승인 필요.
- A2-1 생성 범위는 승인됐지만 데이터 생성·생성기 실행은 별도 승인 전 금지.
- 장중 당일 raw partition 미접근, 수집기/구독/스케줄러 변경 금지.
- KIS API/계좌/Live/주문 호출 없음. SQLite 운영 활성화 및 Live settlement 후속 작업 동결.
- Strategy 3/4 제외, 전략 파라미터 최적화 금지.