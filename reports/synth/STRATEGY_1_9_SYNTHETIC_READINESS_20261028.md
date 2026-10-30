# Strategy 1~9 합성 검증 준비도 감사 — 읽기 전용

- 작성일: 2026-10-28
- 상태: 정적 준비도 감사 완료 / 테스트 미실행 / 코드 미수정
- 범위: 현재 작업트리의 코드·테스트 파일 경로·명세 추적표·시나리오 계획 및 확정 Decision Log No.1176을 대조. 합성/REAL_VTS 원본 데이터는 열거나 변경하지 않았다.
- Git: `cleanup/p2-quarantine-20261026`; HEAD=`657b573123ec43495c86da8712b9a6278bd9a746`; `origin/Project200`도 같은 SHA. 시작 시 dirty/untracked가 다수 확인되어 전부 보존.

## 1. 현재 확인된 공통 결함/제약

1. `docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.4.md`는 261개 요소의 추적 skeleton이며 파일 헤더가 정확한 Test ID/evidence mapping 미완료, 검증 미통과로 명시한다. 따라서 문서 행 존재는 구현 또는 테스트 통과 증거가 아니다.
2. `docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.4.md`에는 NOT_RUN/BLOCKED 시나리오가 많다. 계획 상태를 실행 결과로 취급하지 않는다.
3. 코드 검색에서 production `FreshnessEvidence(...)` 생성자와 runtime `evaluate_freshness(...)` 호출이 연결되어 있지 않다는 R4 결과가 있다. 합성 전용 freshness verdict는 테스트 fixture에서만 사용한다. 운영 FRESH를 임의 생성하지 않는다.
4. Quote-only 경로 테스트는 `last_price`/`volume`을 추정하지 않고 routing하지 않으며 authoritative underlying 또는 양방향 quote 누락 시 BLOCKED를 기대한다.
5. 합성 threshold sweep은 `max_age` 후보 민감도만 보여준다. 300/600/900/1800초 중 어느 값도 운영 기준으로 확정하지 않았다.
6. 기존 작업트리에 수정·미추적 파일이 다수 있으므로 다음 코드 변경은 명시적으로 파일 범위를 정하고 다른 변경을 포함하지 않아야 한다.

## 2. 전략별 준비도 표

| 전략 | 현재 확인한 코드/테스트 증거 | 합성 검증 우선 항목 | 준비도/차단 |
|---|---|---|---|
| S1 Tail Defense | `core/strategy/track1_tail_defense.py`, `track1_runtime_input_provider.py`, `tests/core/test_track1_spec_alignment.py` 4개 테스트 함수; 시나리오 계획에 step-anchor U28 unresolved 기록 | ATM/strike step, 진입·추가진입 anchor, DTE4 close 이후 재진입 금지, partial/cancel race, flat-confirmation | **BLOCKED_SPEC** — step anchor 선택은 임의 가정 금지 |
| S2 Asymmetric Trap | `track2_asymmetric_trap.py`의 명시적 fail-closed 주석/thresholds; spec-alignment 3개 + PnL fail-closed 1개 테스트 함수 | 각 threshold의 below/equal/above, analytics 누락, order price/risk cap 미설정, no-signal reason | **BLOCKED_SPEC** — 승인 명세에서 미결정으로 표시한 진입/가격/위험값을 합성 결과만으로 확정하지 않음 |
| S3 Statistical Arbitrage | strategy source, analytics/runtime provider, futures/multileg adapters; spec-alignment 3개; `test_track3_spread_leg_definition_block.py`는 정의 미해결 시 차단을 확인 | z-score regime boundary, source missing, hedge identity conflict, no-trade branch, block reason | **BLOCKED_IDENTITY/SPEC** — 확정 Decision Log No.1176에 따라 authoritative mini-Futures identity/fields와 경제적 spread leg 정의 전 production resolver 금지 |
| S4 Gamma Scalping | `track4_gamma_scalping.py`, runtime input/materializer seams; spec-alignment 3개 + configured hedge cap 테스트 2개 | underlying/option quote consistency, hedge cap boundary, delta/gamma input missing, partial hedge lifecycle | **BLOCKED_INPUT/SPEC** — authoritative instrument/input과 전략별 미결정 규칙을 분리 |
| S5 Gap Divergence | `track5_gap_divergence.py`, analytics/option source; spec-alignment 3개 + option source 테스트 3개 | gap size, regime-specific z threshold, stale/zero depth, reversal, fill volume support, trailing/exit | **SYNTHETIC_AUDIT_READY** — readiness는 구현 완성/수익성 의미가 아님 |
| S6 Daily Tail Insurance | source 주석에 order-price/freshness/risk 설정 PROVISIONAL/null 명시; spec-alignment 4개 + cutoff 테스트 1개 | IV ratio 1.3 below/equal/above, sequential rank, 10-minute timeout/cancel race, 15:10 close, per-leg trail | **BLOCKED_SPEC/INPUT** — 미설정 필수값은 임시 후보로 실험 가능하지만 주문 기본값으로 승격 금지 |
| S7 Weekly Insurance | option contract source + analytics/calendar/timeout sources; spec-alignment 4개 + cutoff 1개 + option source 테스트 2개 | Monday/Thursday group isolation, rank 5/6 sequential order, ratio 1.30 boundary, 15:00 entry cutoff, expiry/session/identity | **SYNTHETIC_AUDIT_READY_WITH_BLOCKERS** — freshness, authoritative master, account risk/cancel recovery는 별도 검증 필요 |
| S8 Monthly Strangle | `track8_macro_regime_monthly_strangle.py`; spec-alignment 4개 | macro regime transitions, quantity invariant, two-leg completion, timeout split, expiry/cancel overlap, account risk | **BLOCKED_SPEC** — 이전 기준 문서가 지적한 macro scale-up과 pair plan의 정합성 및 timeout/risk 설정을 먼저 재현·확인 |
| S9 Event Overnight Insurance | `track9_event_overnight_insurance.py`, option contract source; spec-alignment 1개 + source tests 8개 + S1 put-insurance gate | opening shock 1% below/equal/above, exact expiry/DTE7 calendar, source freshness, restart/watermark, independent S1/S9 lot ownership | **SYNTHETIC_AUDIT_READY_WITH_BLOCKERS** — DTE7/authoritative source/freshness 확인 전 운영 완료로 승격 금지 |

`SYNTHETIC_AUDIT_READY`는 명세가 완결됐다는 뜻이 아니라, 현재 증거로는 합성 시나리오 설계를 시작할 수 있다는 작업 순위다. 표의 테스트 함수 개수는 경로 스캔 수치이지 실행 결과가 아니다.

## 3. 다음 수정 순서 제안

### 1순위 — 공통 input admission/freshness·provenance
- 합성-only `FreshnessEvidence` fixture와 production source evidence를 타입/경로 수준에서 분리한다.
- 정상/경계/누락/stale/future/identity conflict/capability missing을 각 상태로 판정하고, 주문 경로 fail-closed를 확인한다.
- 현재 production producer가 연결되지 않은 사실을 먼저 해결해야 S1~S9 개별 threshold 실험이 stale/missing input을 잘못 정상으로 해석하지 않는다.

### 2순위 — S5/S7/S9의 합성 입력·상태전이 감사
- 기존 contract/source 테스트가 있어 준비도가 상대적으로 높지만, 테스트 실행 및 integrated lifecycle 증거는 아직 별도 확인해야 한다.
- 전략별 입력 누락, identity, expiry, sequential order, partial fill/cancel race, per-leg position ownership를 시나리오화한다.

### 3순위 — S1/S2/S6/S8 명세 미결정값 목록 확정
- 임시 후보를 합성 민감도 실험에 쓸 수 있으나 `candidate`로만 기록한다.
- 미결정된 경제적 규칙(예: anchor, order price, timeout split, risk cap)은 합성 결과로 사용자의 투자 의도를 대신 결정하지 않는다. 별도 명세 결정이 필요하면 `BLOCKED_SPEC`로 둔다.

### 4순위 — S3/S4 identity blocker
- No.1176과 일치하게 authoritative mini-Futures identity/fields가 확보되기 전에는 production resolver/identity를 만들지 않는다.
- 이 기간에는 차단 동작, 데이터 부족 진단, source capability matrix, fixture-only contract tests만 검증 대상으로 삼는다.

### 5순위 — 전체 1~9 통합 replay
- 전략별 개별 run과 통합 run을 분리한다. 먼저 각 전략의 `NO_SIGNAL_OBSERVED`와 입력 blocker를 보고하고, 양성 lifecycle은 명시된 fixture case로 별도 증명한다.
- 고속·상세 로그 동등성은 모드 계약이 정의된 뒤 진행한다.

## 4. 다음 단계 및 승인 경계

- 이번 감사는 읽기 전용이다. `pytest`, `py_compile`, generator/replay 실행은 하지 않았다.
- 다음 실제 단계는 **공통 input admission/freshness 시나리오 테스트 범위와 정확한 파일 목록을 확정하는 작업**이다. 코드/테스트 수정 또는 테스트 실행은 공식 과제 큐의 Q 항목과 명시적 `승인 Qn`이 확인된 뒤 시작한다.
- KIS Live/계좌/주문 API, REAL_VTS 원본, collector/scheduler, deletion/move, stage/commit/push는 수행하지 않았다.
