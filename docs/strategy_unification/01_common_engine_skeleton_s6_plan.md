# Phase 2 — Strategy Evaluation Parity + S6 Candidate Engine

**Status:** implementation candidate only; no production route switch.
**Baseline:** tag `baseline-current-implementation-20261011` → `e343c1dbb5abecee81e15a4b72b9a0330e302b47`.
**Task start HEAD:** `4d160b8e1e789c15ee90685433e667bf3c68c832` on `Project200`.
**Evidence wording:** results below are *strategy evaluation boundary parity* only. They are not Virtual execution, order/fill/P&L equivalence, or a Golden baseline.

## 1. D1 — two independent equivalence layers

1. **Strategy evaluation boundary parity:** identical `StrategyContext` inputs and callback sequences are sent to the legacy `Track6DailyTailInsurance` and the opt-in candidate. Compare every `Signal` dataclass field, every `execution_proposal` field, `NON_EXECUTION` event payload, every `Track6State` field, private pending flags, callback transitions, and reset output. Test fixtures are explicit unit inputs, not REAL_VTS evidence.
2. **Execution Golden baseline:** requires authoritative executable quote coverage for the selected CALL strike `1107.5`. This remains **BLOCKED**. No order/fill/lot/P&L equality is claimed.

DERIVED_SCENARIO is a separate provenance and may only supplement strategy evaluation parity. It must never be labelled REAL_VTS. The existing three-month replay path does not expose a bounded ≤5,000-event invocation with the required strategy signal observation, so B-3 remains BLOCKED; no runner was created.

## 2. Reuse and rule-of-three

- Reuse `StrategyPlugin`, `StrategyContext`, `StrategyInput`, `AnalyticsSnapshot`, `Signal`, `StrategyExecutionProposal`, `Track6State`, and the existing `MarketSessionPolicy`.
- New code is opt-in under `core/strategy/engine/`: `phase_clock.py`, `s6_rules.py`, `s6_engine.py`, `s6_plugin.py`. The candidate is **not registered** in `standard_registry.py`, `strategy-manifest.v1.json`, or the production composition root.
- The candidate decision functions return signals, next state, and pending status; they do not call the broker, read market data, or change runtime wiring. Existing S6 input/state dataclasses are reused as contracts; no parallel signal/proposal/plan DTO was added.
- Only S6-required time comparison and rule data are extracted. Do not generalize other strategies' trailing or session rules before a second strategy (S7) is migrated.

## 3. PRESERVE list

- Strategy identity remains `track6_daily_tail_insurance` / version `1.0`; feature requirements and manifest-declared `vol_trigger_multiplier=1.3`, `insurance_qty=1` remain unchanged.
- Entry requires Decimal analytics, positive multiplier, and both listed strikes. The 15:15 pending-tranche CANCEL window and its ordering remain unchanged.
- Active evaluation order stays expiry cutoff first, then take-profit. Existing string comparison semantics for `HH:MM:SS` are preserved.
- Preserve trailing activation at 1.5× when active volatility is below 1.3 and 2.0× otherwise; retention ratios 0.90 / 0.88 / 0.85 at the original ratio boundaries; watermark update factor 1.01; take-profit suppression at `15:12:00`; `15:00:00` limit close and `15:15:00` fallback close.
- `UPDATE_TRAILING` remains `NON_EXECUTION` with the same event type/reason/payload. The candidate does not turn it into an order.
- `_exit_pending` resets only after the existing accepted close purpose reports both group complete and position flat. Rejected/incomplete/not-flat outcomes do not reset state.
- Existing S6 strategy source, factory, registry, manifest, orchestrator, collector, scheduler, environment, and active route are not modified.

## 4. B-2 — strategy branch coverage matrix

The table records whether a scripted context exercised the existing branch and whether legacy/candidate outputs matched. It is not market execution evidence.

| Branch / condition | Harness case(s) | Result |
|---|---|---|
| Inactive, volatility below trigger | `inactive_volatility_below_trigger` | PASS — no signal |
| Trigger met but multiplier or strike missing | `trigger_but_multiplier_missing`, `trigger_but_strike_missing` | PASS — no signal |
| Valid entry and proposal | `normal_buy_proposal` | PASS — `BUY_INSURANCE` |
| `base_vol <= 0` | `base_vol_nonpositive` | PASS — no signal |
| 15:15 pending-tranche cancel | `15_15_pending_cancel` | PASS — `CANCEL` |
| Active but trailing not activated | `active_trailing_not_activated` | PASS — no signal |
| Trailing activation 1.5× / 2.0× | `trailing_activation_low_vol_1_5x`, `trailing_activation_high_vol_2x` | PASS |
| Watermark zero / 1.01 factor immediately before and at boundary | `watermark_previous_high_zero`, `watermark_1_01_before_boundary`, `watermark_1_01_at_boundary` | PASS |
| `UPDATE_TRAILING` output and payload | watermark cases | PASS — emitted as `NON_EXECUTION` |
| Trailing retention ratios: 0.90 at 2.0, 0.88 at 1.3, 0.85 below 1.3 | `trailing_close_ratio_090_at_2_boundary`, `trailing_close_ratio_088_at_1_3_boundary`, `trailing_close_ratio_085_below_1_3` | PASS |
| 15:00 limit close / 15:15 fallback | `15_00_limit_close`, `15_15_fallback_close` | PASS |
| Take-profit suppression at 15:12 | `take_profit_suppressed_at_15_12` calls the existing take-profit method directly | PASS — branch covered; top-level `evaluate()` still prioritizes cutoff first |
| `_exit_pending` suppresses re-signal | `exit_pending_suppresses_resignal` | PASS |
| Each close-purpose callback, partial/not-flat, and reset | callback tests | PASS |
| `premium_spent <= 0`, missing payload/analytics, non-Decimal analytics | `premium_spent_nonpositive`, `analytics_missing_payload`, `analytics_value_not_decimal` | PASS — no signal |

## 5. B-4 — harness sensitivity

| Temporary candidate mutation | Expected detection | Result |
|---|---|---|
| Retention ratio 0.88 → 0.89 (compiled in-memory variant; no source file changed) | Semantic signal difference | PASS — DIFF detected |
| Move cutoff by one second | Boundary signal difference | PASS — DIFF detected |
| Omit a state-field update | State snapshot difference | PASS — DIFF detected |
| Change proposal `tag_id` | Proposal-field difference | PASS — DIFF detected |
| Change `UPDATE_TRAILING` condition | Signal list difference | PASS — DIFF detected |
| No mutation / same initial state and same input repeated twice | Zero diff and deterministic trace | PASS |

The serializer walks dataclass fields recursively, including the complete proposal and non-execution payload, and includes all state fields plus private plugin fields such as `_exit_pending`.

## 6. B-3 and remaining gates

- **B-3 DERIVED_SCENARIO:** BLOCKED. `verification/current_strategy_replay.py --ticks 5000` is a bounded single-strategy REAL_VTS-store replay with aggregate counters, not the requested three-month `high_volatility` / `shock` scenario path. The existing three-month runner has no bounded-event CLI option; its full dataset replay was not run. No new runner was added. `NO_SIGNAL_OBSERVED` was not asserted because no B-3 scenario replay ran.
- **Execution Golden baseline:** BLOCKED until authoritative executable quote coverage includes the selected CALL `1107.5`. No synthetic quote was added and S6 strike selection was not changed.
- **Production route switch:** not performed; requires separate explicit approval after later execution-level evidence.

## 7. Commands verified

- `py -m pytest tests\unit\test_strategy_parity_harness.py tests\strategy\test_s6_engine_candidate.py tests\strategy\test_strategy6.py tests\strategy\test_strategy_evaluation_seam.py tests\strategy\test_strategy_contract_safety.py tests\strategy\test_execution_plan_contract.py tests\architecture\test_dependency_rules.py -q -x` → **42 passed**, exit 0.
- `py -m compileall -q core/strategy verification/strategy_parity` → exit 0.
- `git diff --check` → exit 0.
- The forbidden-path diff from task-start HEAD `4d160b8e1e789c15ee90685433e667bf3c68c832` was empty at the time of inspection.

## 8. Not performed

No active S6 route switch, strategy algorithm fix, quote synthesis, collector/scheduler change, production registry/manifest change, full pytest, or 49,140-event integration test. No JSON/log/replay output is intended for commit.
