# R4 Replay Clock Injection — 실행 기록 (2026-10-28)

## 상태
PARTIAL / FULL_REPLAY_OUTPUT_FOUND_EXITCODE_UNVERIFIED

## 승인 및 범위
- 사용자 승인: `승인 R4 코드범위`
- 실행 도구: My_Caddy_TS1
- 브랜치: `cleanup/p2-quarantine-20261026`
- HEAD 기준: `657b573`
- 코드 변경은 승인된 Replay clock-injection 범위에 한정했다. 기존 worktree 변경은 보존했다.

## 변경
- `environments/high_speed/replay_runner.py`
  - `ClockProvider` 주입 지원.
  - replay pacing의 sleep과 elapsed timer를 주입된 clock으로 전달.
  - 기본 실행은 기존 시스템 clock/sleep 동작을 유지.
- `environments/high_speed/virtual_runtime_replay.py`
  - 선택적 clock 주입을 `SyntheticRuntimeSources`와 `HighSpeedReplayRunner`에 전달.
  - 기존 기본 UUID Run ID는 유지. 호출자가 run_id를 지정하면 고정 ID를 사용할 수 있다.
- `environments/high_speed/synthetic_runtime_sources.py`
  - 선택적 clock 주입 시 tick 이전 fallback timestamp가 해당 clock을 사용하도록 변경.
  - clock 미주입 경로의 기존 fallback은 유지.
- `tests/scripts/test_virtual_runtime_replay_clock_contract.py`
  - 주입 clock pacing, infinite speed의 무-sleep, 잘못된 speed fail-closed 검증.

## 변경 전 백업 및 SHA-256
백업 폴더: `reports/synth/r4_backup_20261028/`

| 파일 | SHA-256 | 백업 일치 |
|---|---|---|
| `environments/high_speed/replay_runner.py` | `46E50FDBCFBBD07493B898D99DB70E392A2B407A57120C478C71F27919C36F6A` | 예 |
| `environments/high_speed/virtual_runtime_replay.py` | `C2D8AEF573C3C3E075ED20DFE4E1466B86025F53CE55B420D307E05D6465BA1B` | 예 |
| `environments/high_speed/synthetic_runtime_sources.py` | `2E67C121A0CA6E021A60A2F2E8B3E8AF9BE08DA58B864F90B9159EF0F1894C19` | 예 |
| `tests/scripts/test_virtual_runtime_replay_quote_isolation.py` | `9F3A73F78633E4685E7181D8317CC89EB66C4C6F6BF7C0ED1328F34A3DAA1ABC` | 예 |

## 검증 결과
- `py -m py_compile environments/high_speed/replay_runner.py environments/high_speed/virtual_runtime_replay.py environments/high_speed/synthetic_runtime_sources.py tests/scripts/test_virtual_runtime_replay_clock_contract.py`: exit 0.
- `py -m pytest tests/scripts/test_virtual_runtime_replay_clock_contract.py tests/scripts/test_virtual_runtime_replay_quote_isolation.py -q`: 11 passed in 0.46s.
- `py -m pytest tests/scripts -q`: 24 passed in 0.75s.
- `git diff --check`: exit 0; line-ending warnings only.
- 1,000-event validation-only replay: exit 0; EVENTS=1000, SIGNALS=0, APPROVED=0, ROUTED=0, FILLED=0, REJECTED=0, EXHAUSTED=False. Strategy 3/7/9 showed UNAVAILABLE diagnostics; this is a limited smoke only and is not E2E PASS.
- Full 53,550-event replay output was subsequently found in `reports/synth/R4_FULL_REPLAY_20261028.txt`. It reports `EVENTS=53550`, `EXHAUSTED=True`, `EVENTS_PER_SECOND=175.55`; `SIGNALS=0`, `APPROVED=0`, `ROUTED=0`, `FILLED=0`, `REJECTED=0`, `MULTI_LEG_DECISIONS=0`, empty strategy signal counts, and realized/unrealized/net P&L all `0.00`. The paired stderr file is empty. Full event exhaustion/output generation is verified, but the original process exit code was not captured.
- Dataset manifest was read (synthetic dataset only): events=53,550, 63 output files, validation_status=PASS_WITH_LIMITATION, identity_source_status=BLOCKED_IDENTITY_OWNER_UNRESOLVED, production_runtime_eligible=false, validation_only=true.

## Limitations / follow-up
- `py -m pytest -q`: 168 passed in 1.29s after the Replay output was recovered.
- A two-run semantic determinism check with fixed Run ID was prepared, but launch attempts did not produce output; deterministic equivalence remains BLOCKED.
- `HighSpeedReplayRunner` has no detailed-log-mode switch/contract, so high-speed vs detail-log equivalence could not be executed without additional implementation. No mode was fabricated.
- Decision→Risk→OMS/Router→Fill lifecycle remains unverified because the full replay emitted zero signals/orders/fills. `PNL_STATUS=VSSF_ACCOUNT_PNL_CONNECTED` indicates a connected read path, not profitable or nonzero execution.
- Full event exhaustion is observed, but replay process exit code and deterministic semantic equivalence remain unverified.
- No REAL_VTS raw data was opened/hashed; no collector/scheduler/KIS API/Live/orders changed.
- No Git stage/commit/push or Decision Log registration.


## R4 validation retry via Remote Desktop Commander (2026-10-28)

### Determinism comparison
- Dataset: `p5_run_20261026_trend_up_seed20261026`; fixed Run ID: `R4-DETERMINISM-CHECK-20261028`.
- Two separate runner sessions each completed two full 53,550-event runs. The first session was unintentionally duplicated after its output initially appeared empty; both sessions used separate output paths and the resulting output files are byte-identical. No dataset files were modified.
- Both runner outputs contain `DETERMINISM_EQUAL=True` and `RUNS_COMPLETED=2`. Each run exhausted all 53,550 events; `signals=0`, `approved=0`, `routed=0`, `filled=0`, `rejected=0`, `multi_leg_decisions=0`, execution IDs empty, and realized/unrealized/net P&L all zero.
- Strategy status counts were identical: Strategy 3 unavailable=53,535; Strategy 7 unavailable=53,550; Strategy 8 unavailable=1,620; Strategy 9 unavailable=53,550; other listed strategies unavailable=0.
- Both output files SHA-256: `858BB44CFA5A3A71F3A4DFFDA5370BB2A095DE0A1936145E0AA1897DD2230A79`.
- The second session exit-code artifact is `0`. The first session completed the runner and wrote both comparison markers, but its wrapper did not produce an exit-code file; that session's OS exit code remains unverified.
- Scope limitation: the runner used a fixed Run ID but did not inject a deterministic ClockProvider. The semantic comparison excludes elapsed time/throughput; this proves same-environment semantic output equality for these runs, not clock independence across environments.

### Order-boundary tests
- `py -m pytest -q tests/application/composition/test_fresh06_bridge_fake_broker_e2e.py tests/application/composition/test_fresh11_caller_edge_matrix_e2e.py tests/application/composition/test_freshness_impl_paths.py tests/core/oms/test_order_router_freshness_guard.py`: 39 passed in 0.27s, exit 0; stderr empty. Output SHA-256 `0C59882872B1B7193164CF4753C6200588635EE8BA170262BC5BA8D19853B23B`.
- `py -m pytest -q tests/core/oms/test_freshness_impl_fill_cancel_race.py tests/core/oms/test_fresh09_cancel_replace_reconcile_e2e.py tests/core/oms/test_fresh09_cold_start_recovery_offline.py`: 7 passed in 0.09s, exit 0; stderr empty. Output SHA-256 `1F263868BDA57518EB3E295A73C1D61BBBC1A46AB55CB484B5BE864E864C3F1F`.
- Offline guard/preflight and OMS fill/cancel reconciliation tests passed (46 total). However, the full replay produced zero signals, approvals, routes, or fills, so the positive runtime path `Decision → Risk → OMS/Router → Broker/Execution → Fill` remains unverified.
- High-speed/detail-log equivalence remains BLOCKED because `HighSpeedReplayRunner` has no detailed-log mode switch/contract. No mode was invented.

### Safety and change scope
- Used only the validation-only synthetic dataset. No REAL_VTS raw data, collector, scheduler, KIS API, Live endpoint, or order path was accessed or changed.
- No source-code edits, Git stage/commit/push, or Decision Log registration in this retry. The report and isolated verification logs are untracked artifacts and must not be included in a commit without separate scope review.
- Status: PARTIAL. Same-environment semantic determinism PASS; targeted offline order-boundary guard tests PASS; positive full runtime order lifecycle and detail-log equivalence remain BLOCKED.

## R4 remainder validation after explicit approval (2026-10-28)

### Clock-independent semantic replay
- Added `tests/scripts/test_virtual_runtime_replay_determinism.py`.
- Three tests passed, including two full Virtual Runtime compositions over 100 events with identical fixed Run ID but substantially different wall-clock and monotonic origins. Compared semantic report fields (event counts, signal/approval/route/fill/rejection counts, execution IDs, strategy statuses and P&L); excluded elapsed/throughput telemetry.
- The 100-event integration comparison is a bounded sample, not a full 53,550-event clock-independence proof. The compared runs did not demonstrate positive signals; positive order-path evidence is separate below.
- Tickless `SyntheticRuntimeSources.snapshot()` uses the injected clock in the test fixture.

### Positive single-leg runtime lifecycle
- Added `tests/application/composition/test_r4_positive_runtime_order_lifecycle.py`.
- A test-only strategy plugin is registered through `StrategyRegistry` and `StrategyHub`; it emits an option execution signal from the test fixture and goes through the actual runtime `on_tick`, Strategy-to-Decision arbitration, RiskGate, OMS/Router, Virtual Broker, Virtual ExecutionReport and position state.
- The test asserts exactly 1 signal, 1 approval, 1 route, 1 fill, one execution ID, and a resulting synthetic-contract position quantity of 1.
- The test supplies a deliberately labeled `R4_SYNTHETIC_FIXTURE_ONLY` FRESH verdict with fixture-only provenance because production source-time semantics are not established. This validates the positive plumbing path conditional on valid freshness evidence; it does NOT prove the production freshness evidence producer can create a valid verdict. No REAL_VTS or Live input is used.

### Test evidence
- `py -m pytest -q tests/scripts/test_virtual_runtime_replay_determinism.py`: 3 passed in 8.33s (prior focused run before the positive lifecycle test was added).
- `py -m pytest -q tests/application/composition/test_r4_positive_runtime_order_lifecycle.py`: 1 passed in 4.29s.
- Focused regression set: 72 passed in 1.03s.
- Final `py -m py_compile` for both new tests: exit 0.
- Final `git diff --check`: exit 0; only existing LF/CRLF warnings.
- Final `py -m pytest -q` after adding the positive multi-leg bridge test: 173 passed in 15.58s, exit 0.
- Clock test SHA-256: `4B797A0DDB21CBE0FDFB37A00F5AF4FDA53B572EE7D40A57ECB23789735BD60B`.
- Positive lifecycle test SHA-256: `DEDA22F29A0EAC11F47DC8E5EF065991E07689267437B1059C327DB2F881B71A`.
- Added `tests/application/composition/test_r4_positive_multileg_runtime_lifecycle.py`; focused run: 1 passed in 4.01s. It verifies 2/2 approved/routed/filled legs, two execution IDs, open position lots for both synthetic contracts, and a registered two-leg group. This test exercises the real `VirtualMultiLegExecutionBridge.execute()` path directly; it does not yet prove the full Strategy → Decision → multi-leg resolver path.
- Positive multi-leg test SHA-256: `C396B846321FC564A52508AE8A2EE452DD60C59D1D792A3024B4CB35C7F5A4BC`.

### Remaining blockers / limits
- Positive multi-leg bridge execution passes with both legs filled and group/position-lot evidence, but full Strategy → Decision → multi-leg resolver → bridge integration remains unverified. Existing multi-leg missing-quote preflight and OMS reconciliation controls remain covered by the 72-test focused regression set.
- High-speed versus detailed-log equivalence remains BLOCKED because the replay runner has no detailed-log mode switch/contract.
- No production source files were edited. The two new test files are untracked and preserved; no stage/commit/push occurred.
- Branch/HEAD remains `cleanup/p2-quarantine-20261026` / `657b573123ec43495c86da8712b9a6278bd9a746`; `origin/Project200` is unchanged and equal.
- Status: PARTIAL COMPLETE. Clock-origin semantic comparison and full-dataset (53,550-event) semantic equality PASS for the zero-signal replay path; positive single-leg, positive two-leg bridge, and integrated Strategy → Decision → test resolver → Bridge lifecycle PASS in the stated fixture scopes. Production freshness evidence producer and detailed-log equivalence remain BLOCKED; Track3 economic spread leg definition remains unresolved. The full-dataset runner's OS exit code was not captured.

## R4 continuation — integrated positive multi-leg path and full-dataset clock run (2026-10-28)

### Full Strategy → Decision → resolver → Bridge path
- Added `tests/application/composition/test_r4_strategy_decision_multileg_lifecycle.py`.
- SHA-256: `386053F8F7E9D4BBA6B20AAE8CB42D461C1462D60E92243C00A8A97E850D5515`.
- Focused test: `py -m pytest -q tests/application/composition/test_r4_strategy_decision_multileg_lifecycle.py` — 1 passed in 4.05s.
- The test registers a test-only StrategyHub plugin, publishes two independent synthetic option contract quotes, lets the real runtime `on_tick` invoke Strategy→Decision arbitration and a test-only multi-leg plan resolver, then calls the attached real VirtualMultiLegExecutionBridge. Result: signals=1, approved=1, routed=2, filled=2, two execution IDs, two synthetic position lots, and a two-leg position group.
- Freshness is explicitly marked `R4_SYNTHETIC_FIXTURE_ONLY`; this proves the positive plumbing path conditional on valid identity-matched freshness evidence. It is not production freshness evidence and does not change the unresolved Track3 economic spread definition. Latest confirmed Decision Log No.1176 (2026-10-22) explicitly keeps S3/S4 blocked until authoritative mini-Futures identity/fields are available, so no Track3 production resolver was forced.

### Full-dataset clock independence
- Created `reports/synth/r4_full_clock_independence_20261028.py` (SHA-256 `735A5EA1A9905B313616CD257237F452B12B75DDF8AA5738999AE24AE95151B8`).
- The runner completed two full 53,550-event Virtual Replay runs with the same fixed Run ID but different injected wall-clock and monotonic origins. Both reported `events=53550`, `exhausted=True`, and identical semantic output: `CLOCK_INDEPENDENCE_EQUAL=True`, `RUNS_COMPLETED=2`.
- Both runs had `signals=0`, `approved=0`, `routed=0`, `filled=0`, `rejected=0`, `multi_leg_decisions=0`, no execution IDs, and net P&L 0.0. This proves full-dataset semantic equality for the current zero-signal replay path only; positive order path is covered by separate test fixtures.
- Output file: `reports/synth/R4_FULL_CLOCK_INDEPENDENCE_20261028.txt`; SHA-256 `A33A573E79511731684CE55A47842FFC547A15910B5E7373F5E3D2FF39F4B821`.
- The process exit code was not captured by the RDC session, so OS exit status is UNVERIFIED. The printed conditions satisfy the script's success predicate (equal semantic reports, both datasets fully exhausted), but the report does not claim a captured exit code.
- The fake monotonic clock remains constant during infinite-speed runs; elapsed/throughput output is intentionally excluded and is not valid performance evidence.

### Latest tests
- Focused R4/freshness/OMS regression set including integrated multi-leg test: `63 passed in 19.28s` (before the latest fail-closed assertion was added).
- Added `test_missing_production_freshness_evidence_fails_closed_before_virtual_broker` in `tests/application/composition/test_r4_strategy_decision_multileg_lifecycle.py`. Focused file result: `2 passed in 7.43s`; it verifies a real runtime signal can be Decision-approved but missing production freshness evidence prevents routing/filling and no broker report or position is created.
- Latest full suite after this test: `175 passed in 22.24s`, exit 0.
- `py_compile` for all four R4 test/runner files: exit 0; `git diff --check`: exit 0 with existing LF/CRLF warnings.
- `git diff --check`: exit 0; existing LF/CRLF warnings only.

### Still blocked by evidence or missing contract
- Read-only source search across `application`, `core`, `infrastructure`, `environments`, and `contracts` found 0 `FreshnessEvidence(...)` constructors and 0 runtime `evaluate_freshness(...)` calls (only the contract definition). Thus no production freshness evidence producer is currently wired into the runtime. Production freshness cannot legitimately emit FRESH until source-time semantics, source capability, payload provenance, and approved age thresholds are verified. `FreshnessPolicy.source_age_enabled` defaults `False`; changing it or fabricating production evidence is out of scope and conflicts with fail-closed rules. Existing contract tests verify unknown/blocked states.
- High-speed/detail-log equivalence remains blocked because the runner has no documented detailed-log mode switch/contract. Do not invent one in this task.
- No production source edits, raw-data access/modification, collector/scheduler changes, KIS API/Live/orders, or Git stage/commit/push occurred.
