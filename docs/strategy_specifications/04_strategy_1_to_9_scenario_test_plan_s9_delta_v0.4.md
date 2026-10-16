# Strategy 1~9 시나리오 테스트 계획 — S9 delta v0.3

- 상태: 계획 초안 / NOT_RUN / 미승인
- 기존 04_strategy_1_to_9_scenario_test_plan_v0.2.md 보존.
- 테스트/REAL_VTS 수집을 실행하지 않았다.
- 필수 증거: spec/config version/hash, dataset provenance, exact expiry YYYYMMDD, quote/position timestamps, group/leg/order/execution IDs, fills, fees/multiplier, S1/S9 lots, account risk snapshot, logs and final state.

## S9 시나리오

| ID | 유형 | 입력/조건 | 기대 결과 | 상태 |
|---|---|---|---|---|
| TP-S9-N01 | 정상 | S1 short PUT > 0, config/quotes/risk valid, 4th liquid | 4th LIMIT only; filled qty only | NOT_RUN |
| TP-S9-N02 | 정상 | S1 short PUT appears | S1 snapshot triggers sizing; no fixed monthly-time dependency | NOT_RUN |
| TP-S9-N03 | 정상/경계 | S1 PUT qty rises/falls | target qty changes by link ratio; actual changes only after fills | NOT_RUN |
| TP-S9-N04 | 정상 | 4th strike quote present and min_volume met | rank 4, exact YYYYMMDD identity | NOT_RUN |
| TP-S9-B01 | 경계 | 4th volume equals min_volume | predeclared equality rule; unresolved means BLOCKED | NOT_RUN |
| TP-S9-B02 | 경계 | 4th no quote/volume or 30-min timeout | cancel 4th; no 3rd until cancel confirmed and late-fill reconciled | NOT_RUN |
| TP-S9-E01 | 예외 | 4th partially fills then timeout | reconcile actual partial; no duplicate full-size 3rd order | NOT_RUN |
| TP-S9-E02 | 예외 | fill arrives after cancel request but before confirmation | no 3rd order; update exposure/reconcile | NOT_RUN |
| TP-S9-E03 | 예외 | cancel state pending/unknown | no 3rd; RECONCILIATION_REQUIRED | NOT_RUN |
| TP-S9-E04 | 예외 | 3rd also lacks liquidity/quote | fail closed; U30 candidates BLOCK_FOR_SESSION/WAIT_AND_RECHECK | BLOCKED |
| TP-S9-N05 | 정상 | fill price/qty/multiplier/fees available | actual cost derived; no monthly cap invented | NOT_RUN |
| TP-S9-N06 | 검증 | TP candidate 2x/3x/5x | compare net P&L, max giveback, crash coverage, slippage; no candidate selected | NOT_RUN |
| TP-S9-B03 | 경계 | same instrument price equals prior buy ×1.30 | rebuy boundary uses prior buy price, not exit price | NOT_RUN |
| TP-S9-E05 | 예외 | S1 target drops while S9 buy pending | cancel/reconcile pending buy before sizing reduction | NOT_RUN |
| TP-S9-N07 | 정상 | TP exit flat; same contract valid and price <= prior buy ×1.30 | same exact instrument rebuy after preflight | NOT_RUN |
| TP-S9-B04 | 경계 | expiry formats differ | canonical exact YYYYMMDD; ambiguous expiry BLOCKED | NOT_RUN |
| TP-S9-B05 | 경계 | S9 DTE7 roll then S1 closes short PUT at DTE4 | expose U35; do not infer policy | BLOCKED |
| TP-S9-E06 | 예외 | next monthly expiry not listed at DTE7 | BLOCKED; U34 required | BLOCKED |
| TP-S9-E07 | 예외 | stale/missing S1 position, quote, volume, multiplier or config null | no entry/resize/rebuy/roll; UNAVAILABLE/BLOCKED | NOT_RUN |
| TP-S9-R01 | 복구 | restart with order pending or position open | reconcile broker orders/fills/positions and S1 exposure before resume | NOT_RUN |
| TP-S9-R02 | 복구 | restart after TP before rebuy state persisted | restore prior buy price/instrument/eligibility; no duplicate order | NOT_RUN |
| TP-S9-E08 | 예외 | S1 qty decrease and TP trigger simultaneously | user-approved priority only; otherwise BLOCKED | BLOCKED |
| TP-S9-E09 | 예외 | late fill after cancel confirmation | reconcile late fill before fallback/reset | NOT_RUN |
| TP-S9-E10 | 예외 | S9 add buy partially fills while S1 exposure shrinks | include pending worst-case exposure; prevent over-insurance | NOT_RUN |

## Cross-strategy interaction scenarios

| ID | Interaction | Condition | Expected result | Status |
|---|---|---|---|---|
| TP-X01-S9 | account premium/margin | S1~S9 request orders; S9 has no monthly cap | account capital/margin/max-loss still blocks oversubscription | BLOCKED |
| TP-X02-S9 | S1/S9 linked lots | same contract appears in strategy/account views | distinct strategy attribution; account exposure counted once | NOT_RUN |
| TP-X03-S9 | S1 DTE4 vs S9 DTE7 | S1 closes all short PUT after S9 rolls | S9 target becomes zero under link rule; no inferred hold policy | BLOCKED |
| TP-X04-S9 | overlapping insurance | S1 base strangle and S9 OTM PUT cover same tail event | aggregate stress model; no double-credit | BLOCKED |
| TP-X05-S9 | grouped execution | partial close/late fill/cancel race | reconcile per-leg fills and positions before reset/resume | NOT_RUN |

## Validation protocol — values not selected
1. Split REAL_VTS trading dates into non-overlapping tuning and holdout periods; record dataset IDs and config hash.
2. For take_profit_multiple compare 2x/3x/5x using net P&L after fees, maximum giveback, crash coverage time, exit slippage, drawdown and missed protection.
3. For min_volume compare candidate thresholds using spread/depth/quote age, quote gaps, fill/partial/reject ratio, slippage and fallback frequency; volume alone is insufficient.
4. For s1_put_link_ratio compare candidate ratios using premium spend, stress offset of S1 short PUT losses, account drawdown, margin, target-vs-actual quantity and double-count risk. Do not infer ratio from delta-equivalent conversion.
5. Predeclare sample windows and acceptance criteria; tuning choice is not final until holdout passes and user separately approves.
6. No tests, simulation, REAL_VTS collection, commit/push or KIS Live order was performed.

## S9 user decision scenarios (planning IDs; NOT_RUN)
| Plan ID | Scenario | Expected behavior | Evidence | State |
|---|---|---|---|---|
| TP-S9-EXIT-01 | Per-lot stop | If fresh premium <= 50% of that lot's actual entry fill price, close only that lot's remaining qty; other lots remain managed independently | lot entry fill, mark timestamp, close order/fills, reconciled positions | NOT_RUN |
| TP-S9-EXIT-02 | 2x trigger then 10% trailing | At >=2.00x entry, arm high-water tracking; no immediate fixed-target exit; after peak, >=10% peak drawdown closes that lot | price/peak series, trigger, close fills, persisted watermark | NOT_RUN |
| TP-S9-LIFE-03 | S1 reaches flat before S9 DTE7 | Do not auto-close S9 solely because S1 exposure is zero; retain S9 independently until lot stop/trailing or DTE7 rollover | S1 flat evidence, S9 inventory, expiry identity, lifecycle events | NOT_RUN |
| TP-S9-LIFE-04 | Stop/trailing before DTE7 | Close affected lot before rollover; never roll a lot with a confirmed exit in progress; reconcile actual fills first | event ordering, orders/fills, remaining lots, rollover plan | NOT_RUN |
| TP-S9-LIFE-05 | Restart with trailing armed | Restore lot-specific entry and high-water mark; if missing/stale, block trading pending reconciliation | persisted state, quote freshness, restart logs | NOT_RUN |

- Decision: S5-specific uncertainty IDs are S5-U16…S5-U20; S1 U16…U29 are preserved. DTE7 calendar/trading-day semantics and exact rollover execution timing remain unresolved. No tests were run.

## Additional DTE7 / quote / restart scenarios (planning only; NOT_RUN)
| Plan ID | Scenario | Expected result | Evidence | State |
|---|---|---|---|---|
| TP-S9-CAL-01 | Weekend/holiday and DTE7 boundary | KRX calendar session dates determine DTE; no calendar-day guess or off-by-one | calendar hash, exact expiry, included sessions, computed DTE | NOT_RUN |
| TP-S9-CAL-02 | Calendar unavailable or disagrees with contract master | UNKNOWN/BLOCKED; no inferred rollover | source/cache provenance and block reason | NOT_RUN |
| TP-S9-QUOTE-01 | Missing source timestamp / unknown timestamp semantics | BLOCKED; no entry, fallback, rebuy or rollover | raw quote, receive time, age calculation, decision log | NOT_RUN |
| TP-S9-QUOTE-02 | Stale quote, clock skew, disconnect gap, wrong expiry | BLOCKED pending fresh same-contract quote/reconciliation | source/receive timestamps, contract identity, freshness config hash | NOT_RUN |
| TP-S9-REC-01 | Restart with multiple lots and trailing armed | Restore per-lot fills, residual qty and high-water mark; reconcile before action | persisted snapshot vs broker executions/positions | NOT_RUN |
| TP-S9-REC-02 | Partial/late fill or cancel race after restart | Apply execution IDs once; block fallback until order/fill/position views agree | order history, execution IDs, position snapshot | NOT_RUN |
| TP-S9-REC-03 | Duplicate execution event or corrupted snapshot | Idempotent fills; fail closed on corruption/mismatch | applied execution IDs and reconciliation result | NOT_RUN |

Detailed acceptance requirements: `05_strategy_9_dte7_quote_restart_validation_addendum_v0.1.md`.


## DTE7 calendar boundary — deterministic test contract (definition pass 1; NOT_RUN)
Test oracle: at 11:00:00 Asia/Seoul on decision date D, count KRX-open derivatives sessions strictly after D and through exact expiry E inclusive. DTE7 fires only when this count equals 7. D is excluded; E is included only when the exact contract/calendar confirms E is a trading session. Missing/conflicting calendar or expiry data => UNKNOWN/BLOCKED. This convention is a testable interpretation of “trading days”; confirm product-specific semantics before runtime activation.

| Plan ID | Test | Expected result |
|---|---|---|
| TP-S9-CAL-03 | Seven open sessions after D through E | DTE=7; evaluate at 11:00 KST |
| TP-S9-CAL-04 | Decision date advances one open session | DTE decrements by one; no trigger at DTE=6 |
| TP-S9-CAL-05 | Weekend and KRX holiday in interval | Non-session dates are not counted |
| TP-S9-CAL-06 | E absent from KRX session set / expiry conflict | UNKNOWN/BLOCKED |
| TP-S9-CAL-07 | Calendar source unavailable; verified cache available | Cache may be used with provenance/version/hash |
| TP-S9-CAL-08 | Both calendar and verified cache unavailable or conflict | UNKNOWN/BLOCKED |
| TP-S9-CAL-09 | Next contract not listed at 11:00, lists later | WAITING_FOR_LISTING; re-run preflight after listing, no speculative order |
| TP-S9-CAL-10 | DTE is 8 or 6 | No DTE7 trigger |

Evidence must include session dates/count, exact expiry YYYYMMDD, KRX calendar version/hash, contract-master snapshot ID, 11:00 KST timestamp, computed DTE and decision outcome. Fixture-only unit tests must not call the order adapter. All cases remain NOT_RUN until executed.

---
## v0.4 — S9 D-4 and liquidity scenarios
1. Four trading sessions remain at 11:00 KST → forced-exit lifecycle; three/five remain → no off-by-one trigger.
2. Holiday/invalid expiry/unknown calendar → BLOCKED, no guessed DTE.
3. S1 and S9 simultaneous close → S1 first, S9 next; S1 pending cannot block S9 indefinitely.
4. Third strike fails liquidity/freshness gate → wait and recheck same contract; no arbitrary price; cutoff during wait aborts new entry.
5. D-4 exit order partially fills or late fill arrives during cancel → continue reconciliation until flat; never revert to DTE7 rollover.
Scenarios NOT_RUN pending authoritative calendar/expiry and REAL_VTS quote/order/fill evidence.
