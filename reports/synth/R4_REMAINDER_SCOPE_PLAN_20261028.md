# R4 잔여 검증 영향 범위 및 테스트 계획 (2026-10-28)

상태: PLAN ONLY / IMPLEMENTATION NOT AUTHORIZED BY THIS PLAN

기준 branch: `cleanup/p2-quarantine-20261026`
기준 HEAD: `657b573123ec43495c86da8712b9a6278bd9a746`
작업 폴더: `C:\Users\white\Desktop\MovingProject\KOSPI200_Project`

## 1. 근거 및 제약

- 원격 `AGENTS.md`, 통합 점검 지시문 v1, 공식 과제 큐, Current Baseline, 최신 확정 Decision Log 및 Q&A No.1360–1362를 다시 확인했다.
- 최신 관련 확정 Decision Log는 No.1176 (2026-10-22). No.1175의 SYNTHETIC 독립 재생은 입력 경계 검증 전용이며 REAL_VTS/Live 검증으로 간주하지 않는다는 제한을 유지한다.
- No.1362의 동일 환경 결정론 결과는 의미 결과 비교에 한정된다. ClockProvider 주입으로 시스템 시계 독립성을 검증하지 않았으며 전체 Replay의 signal/approved/routed/filled는 모두 0이다.
- 이 작업은 영향 범위 및 테스트 계획 작성만이다. 코드 수정, 테스트 실행, 합성 데이터 생성/변경, Git stage/commit/push는 수행하지 않는다.
- 08:29–16:01 KST 운영 가드 동안 Collector·수집 코드·scheduler를 변경/중지/재시작하지 않는다. 오늘 REAL_VTS raw는 열거나 해시하지 않는다. KIS API, Live 및 실제 주문은 사용하지 않는다.
- 기존 dirty worktree와 미추적 파일은 유지한다. HEAD는 `657b573`, `origin/Project200`도 동일 SHA였다. 이번 계획 외 파일을 건드리거나 정리하지 않는다.

## 2. 현재 코드 관찰

### Clock / deterministic replay
- `contracts/clock.py`: `ClockProvider.now()`, `monotonic()`, `sleep_policy()`.
- `environments/high_speed/replay_runner.py`: `clock` 주입이 이미 있고 replay pacing 및 elapsed timer가 clock을 사용한다. 기본 clock은 `datetime.now()`, `time.perf_counter()`, `time.sleep()`을 감싼다. `speed=inf`에서는 sleep하지 않는다.
- `environments/high_speed/virtual_runtime_replay.py`: clock을 `SyntheticRuntimeSources` 및 replay runner에 전달한다. Run ID는 명시 전달 시 고정 가능하며 기본값은 UUID.
- `environments/high_speed/synthetic_runtime_sources.py`: clock 주입이 있지만 tick이 없는 경우의 두 fallback에서 clock 미주입 시 `datetime.now()`를 사용한다. 실제 Replay tick 경로에서는 `set_tick()`이 먼저 호출되므로 fallback이 호출되지 않는다고 단정하지 말고 테스트로 확인해야 한다.
- `application/composition/automated_virtual_trading_loop.py`: `as_of`는 tick의 source timestamp에서 파싱된다. Replay clock이 runtime loop, Decision/Risk/OMS/Virtual Broker의 모든 time dependency를 자동으로 대체한다고 가정할 수 없다. 양성 경로를 테스트하기 전 해당 경계의 timestamp/timeout 호출을 별도 정적 조사한다.
- 현재 `tests/scripts/test_virtual_runtime_replay_clock_contract.py`는 pacing, infinite speed no-sleep, invalid speed fail-closed를 확인하지만 전체 runtime 의미 결과의 시계 독립성은 확인하지 않는다.

### Positive order path
- `HighSpeedVirtualRuntimeReplayRunner`는 기존 Virtual Runtime bootstrap과 `attach_standard_automated_loop`를 사용하고, tick을 publish한 뒤 `loop.last_result`에서 counts를 수집한다.
- `AutomatedVirtualTradingLoop.on_tick()`은 StrategyHub → Strategy-to-Decision arbitration → execution plan → Risk/Router → broker/execution → report/position accounting 순서를 포함한다.
- Single-leg path는 `route_from_runtime_authoritative_sources` / `StandardOrderRouter` / Virtual Broker adapter를 통과한다. Multi-leg path는 `VirtualMultiLegExecutionBridge.execute()`의 모든 레그 사전검사 후 risk/route/Virtual execution을 사용한다.
- 현재 집중된 freshness/missing-quote 테스트는 차단 경로에 초점이 있다. No.1362 full replay에서도 signal/order/fill이 0이므로 positive runtime lifecycle의 증거는 없다.
- 합성 contract identity는 `SYNTHETIC_CONTRACT:` namespace에 남아야 하며 Standard ID 승격을 금지한다. 합성 실행은 validation-only Virtual Execution 증거로만 기록한다.

## 3. 제안 영향 파일 범위

### A. Clock-independent determinism
1. `tests/scripts/test_virtual_runtime_replay_clock_contract.py` — existing tests 유지, clock contract coverage 확장.
2. 신규 후보 `tests/scripts/test_virtual_runtime_replay_determinism.py` — isolated repeat-run semantic comparison.
3. 조건부 검토 대상(테스트 실패로 gap이 증명될 때만): `environments/high_speed/replay_runner.py`, `environments/high_speed/virtual_runtime_replay.py`, `environments/high_speed/synthetic_runtime_sources.py`.
4. `contracts/clock.py`와 `environments/virtual/clock.py`는 기존 계약/구현 재사용 우선. 새 clock abstraction을 추가하지 않는다.

### B. Positive runtime order-boundary path
1. 신규 후보 `tests/application/composition/test_r4_positive_runtime_order_lifecycle.py` (최종 경로는 현재 테스트 구조와 import contract 재확인 후 결정).
2. 필요 시 별도 test-only fixture/helper in `tests/`; dataset fixture는 기존 synthetic generator/schema/MarketData interface로 생성하며 runtime에 직접 quote/order/fill을 주입하지 않는다.
3. 테스트 대상 production path(우선 read-only): `application/composition/automated_virtual_runtime_factory.py`, `application/composition/automated_virtual_trading_loop.py`, `application/composition/runtime_authoritative_risk_router_adapter.py`, `application/composition/virtual_multi_leg_execution.py`, `core/decision/`, `core/risk/`, `core/oms/`, `environments/virtual/`, `contracts/types.py`.
4. Production source edits are not pre-authorized by this plan. If the existing composition cannot accept a test-only Strategy Plugin through its normal StrategyHub seam, stop and submit a precise source-file scope for separate approval rather than monkeypatching Decision/Risk/Router/Fill or changing production strategy behavior.

## 4. Clock-independence test plan

### Fixtures
- Fake Clock A and Fake Clock B must have deliberately different wall-clock origins and monotonic origins. Both must record `sleep_policy` calls and advance monotonic consistently.
- Same validation-only dataset, seed, generator version/config hash, fixed Run ID, strategy configuration and fresh isolated runtime state per run.
- Use the same source tick timestamps; no `datetime.now()` values may be inserted into market data, UI, logs, or expected output to make the test pass.

### Cases
- C1: Same input + fixed Run ID + different FakeClock wall-clock origins; semantic output is identical.
- C2: Different monotonic base offsets; elapsed duration may be measured independently but semantic output is identical.
- C3: Finite speed verifies pacing is delegated only to injected `sleep_policy`; no system sleep is invoked in the deterministic test.
- C4: `speed=inf` invokes no sleep and preserves event order.
- C5: Tickless source fallback uses injected clock; clock-less deterministic mode must either be rejected explicitly or prove the fallback cannot be reached. Do not silently allow wall-clock fallback in a declared deterministic mode.
- C6: Fixed Run ID is explicit; do not change the production UUID default.
- C7: Compare stable semantic projection: event order/count, first/last source timestamps, signal/decision/rejection counts, approved/routed/filled/rejected counts, execution IDs, order/fill reports, position lots and P&L. Exclude only nondeterministic telemetry (elapsed/throughput) from equality, while separately asserting it is finite/non-negative.
- C8: Repeat twice from newly composed runtime state and ensure no order, fill, position, P&L or strategy state leaks between runs.

### Pass criteria
- Two independent fresh runs produce identical semantic projections and stable execution IDs for the same fixed run identity.
- No un-injected wall-clock/sleep call is observed on the deterministic replay path.
- Input order and source timestamps are preserved; `speed=inf` does not sleep.
- If any runtime semantic depends on `datetime.now()`, UUID generation, process state or nondeterministic collection ordering, record FAIL/BLOCKED and isolate the source before changing code.

## 5. Positive Decision → Risk → OMS/Router → Fill test plan

### Fixture/runtime seam
- Use a dedicated test-only Strategy Plugin that is registered through the normal StrategyHub/strategy-result interface and emits one deterministic, explicitly identified EXECUTION signal only after required fixture inputs are available. Do not patch the Decision arbiter, RiskGate, Router, broker adapter, or fill report to force a pass.
- Supply a minimal two-contract validation-only synthetic event fixture through the existing synthetic dataset adapter/market-data publishing path. The test strategy may emit a multi-leg plan only after both exact synthetic contract quotes are available. All rows retain `synthetic=true`, generator version, seed, DERIVED_SCENARIO provenance and validation-only identity. No production Standard IDs.
- If normal StrategyHub registration cannot accept a test plugin without production edits, first produce a narrower design and obtain separate approval. Do not directly inject a canonical order into the log/UI or bypass Strategy → Decision.

### Cases
- P1 positive single-leg lifecycle: Strategy Plugin → Decision approved → Risk admitted → OMS/Router called → Virtual Broker submitted → Virtual ExecutionReport has positive filled quantity and execution ID → position/lot and P&L read model update.
- P2 positive multi-leg lifecycle: both required quotes and exact identities available; group risk preflight passes; all required legs are prepared before first submission; verify per-leg provenance (`run_id/group_id/leg_id/client_order_id/execution_id`) and group/position read-model consistency.
- P3 negative control: remove one leg quote; assert zero broker submissions and no fills.
- P4 negative control: UNKNOWN/STALE/CAPABILITY_CONFLICT freshness; assert Risk and Router are not called.
- P5 partial/reject/cancel control: retain actual PARTIAL/BLOCKED/RECONCILIATION_REQUIRED state and never treat request as fill/cancel confirmation.
- P6 repeat same fixture in two fresh runtimes; stable event/decision/order/fill lineage and no cross-run state bleed.
- P7 verify Virtual Broker/Execution only; assert no KIS API, Live endpoint or external broker is invoked.

### Required evidence
- Stage counters and correlated IDs at Strategy result, Decision, Risk, OMS/Router, broker submission, ExecutionReport, position lot and P&L.
- Assertions require actual downstream calls/reports; a manually constructed `AutomatedTickResult` or fabricated log row is not evidence.
- Positive-path test is plumbing evidence only. It does not prove a production strategy emits signals, synthetic profitability, REAL_VTS performance or Live readiness.

## 6. Test order and stop conditions

1. Read-only baseline/source scope and current test inventory (completed for this plan).
2. Implement/extend clock tests only after separate scope approval; run focused clock tests.
3. Implement test-only StrategyHub fixture and positive single-leg Virtual lifecycle; run focused test.
4. Extend to multi-leg positive lifecycle and negative controls; run focused tests.
5. Run relevant existing regression set: `tests/scripts/test_virtual_runtime_replay_clock_contract.py`, `tests/scripts/test_virtual_runtime_replay_quote_isolation.py`, `tests/application/composition/test_fresh06_bridge_fake_broker_e2e.py`, `tests/application/composition/test_fresh11_caller_edge_matrix_e2e.py`, `tests/application/composition/test_freshness_impl_paths.py`, `tests/core/oms/test_order_router_freshness_guard.py`, `tests/core/oms/test_freshness_impl_fill_cancel_race.py`, `tests/core/oms/test_fresh09_cancel_replace_reconcile_e2e.py`, `tests/core/oms/test_fresh09_cold_start_recovery_offline.py`.
6. Only after focused tests, run full `py -m pytest -q`, compile affected files, `git diff --check`, inspect diff/status and graphify update if source code changes are approved.
7. Stop after two consecutive occurrences of the same error. No commit/push without separate approval.

## 7. Explicit non-goals

- No change to strategy trading rules, risk thresholds, order sequencing, wait/cancel behavior or one-order-at-a-time behavior.
- No modification of today's REAL_VTS raw files, collectors, collector code, scheduler or KIS request behavior.
- No KIS API, account/position/margin endpoint, Live API, actual order, token or `.env` access.
- No claim of production signal, profitability, REAL_VTS E2E or Live PASS from a test-only fixture.
- No production source edit, dataset generation, Git stage/commit/push in this planning task.

## 8. Approval boundary

This document is a scope/test plan only. Next action requires explicit approval of the source/test file scope before any code edit or test execution. Recommended approval phrase: `승인 R4 잔여검증 범위`.
