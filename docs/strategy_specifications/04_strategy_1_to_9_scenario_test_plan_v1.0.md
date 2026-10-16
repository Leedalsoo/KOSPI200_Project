> **LATEST CANDIDATE NOTICE — 2026-10-13:** This file is the newest consolidated draft for Strategy 1–9 review. It absorbs the currently available S2/S5/S9 deltas and the S6 retry-policy clarification. Status remains DRAFT / UNVERIFIED / UNAPPROVED; scenarios and REAL_VTS replay are NOT_RUN. Older versions and delta files are retained as historical evidence, not current approval.

# Strategy 1~9 Scenario Test Plan v1.0


- Canonical consolidated draft, 2026-10-13. Status: draft / unverified / unapproved.
- Latest scenario-plan reference after this consolidation. S2/S5/S9 delta documents are preserved historical appendices; S6 v0.4 records the 2026-10-13 no-retry decision. `trading_day_boundary_table_v2.md` records exact-expiry candidates and cache-backed calendar vectors; missing monthly expiries remain UNSET/BLOCKED and all calendar scenarios remain NOT_RUN.
- Scenarios and REAL_VTS replay: NOT_RUN. This document is not implementation authorization.


- 상태: **계획 초안 / 미실행 / 미승인**
- 기준 브랜치/HEAD: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- 적용 범위: Strategy 1~9 현재 초안 명세 및 통합설계표/delta 문서 (S1·S5·S6·S7·S9 v0.3; S2·S3·S4·S8 v0.2). 전체 미승인.
- 이 문서는 테스트 계획이다. 실행 결과나 PASS를 의미하지 않는다. 미결정 투자 정책은 임의로 가정하지 않으며, 해당 시나리오는 정책 확정 전 BLOCKED로 유지한다.
- 환경: Virtual/VTS 전용. KIS Live 주문 실행 금지.
- 모든 테스트의 필수 증거: spec version, config hash, source/contract identity, as-of timestamps, group/leg/order/execution IDs, order/fill/position read model, P&L/fee ledger, stdout/log path, final result.
- 공통 테스트 원칙: 주문 ACK/취소 요청은 fill/취소 완료가 아니다. 부분체결은 레그별로 관리한다. 실제 포지션 대사 전 reset/flat 선언 금지. unknown/stale/mismatch는 fail-closed.

## A. 전략별 시나리오

| 계획 ID | 전략 | 유형 | 입력·조건·변형 | 기대 상태/결과 | 증거·판정 기준 | 실행 상태 |
|---|---|---|---|---|---|---|
| TP-S1-N01 | S1 Tail Defense | 정상 | 공식 세션·신선한 option chain/Greeks/volatility/quotes, 승인된 leg structure, 모든 leg preflight 통과 | ENTRY_PLANNED → ENTRY_WORKING; ACTIVE는 실제 fill/lot 대사 후에만 | per-leg order/fill/position + group risk snapshot | NOT_RUN |
| TP-S1-B01 | S1 | 경계 | volatility ratio = approved threshold; fence distance와 strike rounding이 tick 경계에 걸림 | 승인된 equality/rounding 규칙과 일치; 규칙 미정이면 BLOCKED | threshold input, chosen contracts, tick calculation | BLOCKED: threshold policy |
| TP-S1-E01 | S1 | 예외 | Greeks stale/missing; Option/Futures lots identity가 섞임; DTE<=4인데 fence 외 레그가 열려 있음 | 신규 주문 차단; 기존 포지션은 RECONCILIATION_REQUIRED; 내부 state 조기 reset 금지 | stale source trace, open lots before/after | NOT_RUN |
| TP-S1-R01 | S1 | 복구 | entry partial/reject/cancel race 또는 restart 중 active fence/Futures hedge가 존재 | 실제 lots/order 상태 복원 후에만 재개; flat 전 reset 금지 | restart snapshot, order/fill reconciliation log | NOT_RUN |
| TP-S2-N01 | S2 Asymmetric Trap | 정상 | 모든 BBW/volume z/OBI/basis/POC/IV features 유효, 4-leg identity·quotes·risk 통과 | 4-leg group plan; 각 레그의 상태는 독립 추적 | four contract IDs, quotes, risk preflight, fills | NOT_RUN |
| TP-S2-B01 | S2 | 경계 | z=3, abs(OBI)=0.5, basis=0.3, POC distance=1.0, active/base vol=0.85 boundary | 각 equality가 승인 규칙대로 포함/제외; 규칙 미정이면 BLOCKED | all raw metrics + boolean decisions | BLOCKED: threshold policy |
| TP-S2-E01 | S2 | 예외 | 이미 ACTIVE일 때 재평가; 한 short leg만 체결; stale option marks; close와 신규 entry 동시 신호 | 중복 entry 금지; actual short exposure 재계산; 신규진입 금지 중 EXIT_PENDING | active group count, per-leg lots, trigger priority | NOT_RUN |
| TP-S2-R01 | S2 | 복구 | trailing close 이후 short-switch timer 잔존, cancel race, restart during cooldown | timer/state가 승인된 lifecycle과 일치; duplicate close/entry 없음 | timer snapshots, group/position reconciliation | NOT_RUN |
| TP-S3-N01 | S3 Statistical Arbitrage | 정상 | 승인된 두 개의 서로 다른 tradable Futures identities, valid spread history/z/regime/cost and positive net edge | entry only when spread units/roles and group preflight pass | leg identities, spread formula, net-edge calculation | BLOCKED: spread definition |
| TP-S3-B01 | S3 | 경계 | z=entry/exit/stop thresholds; max holding boundary; volatility/regime boundary | exact threshold/elapsed-time semantics applied; call count not silently treated as seconds | raw z, regime, timestamps, elapsed time | BLOCKED: threshold/time policy |
| TP-S3-E01 | S3 | 예외 | same identity with opposite side/equal qty; missing P&L converted to zero; pending-exit branch lacks regime | invalid/zero-economic spread rejected; unavailable P&L remains UNAVAILABLE; no runtime exception | resolved legs, payload provenance, stack/log | NOT_RUN |
| TP-S3-R01 | S3 | 복구 | partial spread entry, one-leg cancel race, process restart while EXIT_PENDING | reconcile each actual leg; no silent state reset or blind retry | order/fill/position ledger and restored state | NOT_RUN |
| TP-S4-N01 | S4 Gamma Scalping | 정상 | confirmed option inventory with matching Greeks and exact Futures identity; target delta outside deadband | hedge order based on target minus actual filled Futures quantity | option lots, Greeks units, target/actual qty, fill | BLOCKED: option ownership |
| TP-S4-B01 | S4 | 경계 | delta equals deadband; target quantity reaches cap; equity equals threshold | deterministic equality/cap behavior; target and actual quantity remain separate | source values, qty conversion, cap decision | BLOCKED: units/policy |
| TP-S4-E01 | S4 | 예외 | no eligible option lots but nonzero aggregate delta; stale Greeks; simultaneous trailing and rebalance | no hedge based on unowned/stale delta; conflict priority deterministic | eligible lots, delta lineage, generated plans | NOT_RUN |
| TP-S4-R01 | S4 | 복구 | partial Futures rebalance/unwind and restart with hedge still open | restore actual Futures lots; recompute target only after option/Greeks reconciliation | actual position, order reports, state restore log | NOT_RUN |
| TP-S5-N01 | S5 Gap Divergence | 정상 | official opening reference, valid gap/expected move/regime, approved Futures role and option contract, group risk passes | entry group only under approved role/size; option/Futures legs independently reconciled | official open source, role labels, group preflight | BLOCKED: Futures role |
| TP-S5-B01 | S5 | 경계 | exactly 30-minute intraday window edge; expected_move*1.1; stop distance floor=1.0; z threshold | approved inclusive/exclusive boundary and wall-clock semantics | session timestamps, expected move, z values | BLOCKED: boundary policy |
| TP-S5-E01 | S5 | 예외 | first tick differs from official open; Futures reject while option fills; stale option quote; option stop occurs before Futures close confirmation | do not infer official open/fill/flat; preserve partial exposure and block unsafe continuation | official open provenance, per-leg fill and remaining qty | NOT_RUN |
| TP-S5-R01 | S5 | 복구 | Futures-first close partially fills; restart before option exit; expiry/session boundary during exit | no option close or group reset unless approved sequence and actual positions reconcile | exit batch, Futures remaining qty, option lots | BLOCKED: exit sequence |
| TP-S6-N01 | S6 Daily Tail Insurance | 정상 | active_vol/base_vol >= approved trigger; listed PUT/CALL quotes and budget/risk pass | pair group planned; ACTIVE only after both fills and lot reconciliation | vol inputs, option identities, premium reserve, fills | NOT_RUN |
| TP-S6-B01 | S6 | 경계 | vol ratio exactly 1.3; 15:00 limit-close start; 15:12 take-profit suppression; 15:15 fallback | session policy and terminal priority deterministic; no exact-time assumption without calendar | timestamps, pending order state, quote | BLOCKED: session policy |
| TP-S6-E01 | S6 | 예외 | one leg fills and other rejects; mark missing; premium_spent zero/invalid; previous-day position still open | no false pair ACTIVE/flat; current intrinsic proxy not treated as MTM; prior lots block new daily entry | fill/mark ledger and prior-day lots | NOT_RUN |
| TP-S6-R01 | S6 | 복구 | cancel race during 15:00 close, fallback at cutoff, restart with one leg remaining | actual remaining qty reconciled; no duplicate close; safe fallback path | cancel/fill event sequence and final positions | NOT_RUN |
| TP-S7-N01 | S7 Weekly Volatility Skew Insurance | 정상 | official new trading week, exact expiry, listed PUT/CALL pair, both quotes and budget pass | group entry only once; active after fills | calendar snapshot, exact expiry, pair fills | BLOCKED: skew thesis |
| TP-S7-B01 | S7 | 경계 | expiry date source uses YYYYMMDD vs YYYY-MM-DD; pair value drawdown exactly 20%; qty>1 | canonical expiry normalized; quantity-aware value and threshold behavior | raw expiry, normalized identity, marks and qty | BLOCKED: MTM policy |
| TP-S7-E01 | S7 | 예외 | strategy name implies skew but IV skew absent; one leg rejects; marks stale while expiry arrives | no invented skew trigger; one-sided pair handled by recovery policy; expiry still managed | feature list, per-leg state, expiry position snapshot | NOT_RUN |
| TP-S7-R01 | S7 | 복구 | new week starts while previous week position remains; restart with peak watermark | no new weekly group until previous lots reconcile; watermark restored | previous group/expiry, restored watermark, flat evidence | NOT_RUN |
| TP-S8-N01 | S8 Macro Regime Monthly Strangle | 정상 | DTE>=15, approved budget, exact monthly pair, macro regime and risk pass | initial pair group; actual quantities/cost/expiry saved after fills | exact expiry, pair quotes, budget and fills | NOT_RUN |
| TP-S8-B01 | S8 | 경계 | DTE=15 and DTE=4; budget=200,000; normal PUT ratio 1.5; trailing watermark update | DTE<=4 preserves HOLD_LONG_ATTACK unless user approves different rule; quantity rounding explicitly tested | DTE, budget, intended vs resolved legs, watermark | BLOCKED: policy |
| TP-S8-E01 | S8 | 예외 | macro add-on PUT-only signal resolves to full pair; add-on rejects; high-watermark equals current value | reject intent mismatch; no pre-fill flag update; watermark transition matches approved logic | proposal tag vs resolved plan, fills and watermark | NOT_RUN |
| TP-S8-R01 | S8 | 복구 | pending tranche cancel race, partial add-on, restart before DTE cutoff | restore base and add-on groups separately; preserve non-execution HOLD semantics | parent/group IDs, cancel reports, exact expiry | NOT_RUN |
| TP-S9-N01 | S9 Event Overnight Insurance | 정상 | entry in approved pre-close window; exact PUT/CALL contracts and premium cap; next session official open | overnight hold only after both fills; opening shock uses official source | session calendar, entry fills, official open and marks | BLOCKED: entry window |
| TP-S9-B01 | S9 | 경계 | entry time exactly start/end; opening shock exactly 1%; stabilization end timestamp | [start,end) entry window and >= window-end semantics are explicit | timestamps, shock calculation and exit reason | BLOCKED: boundary policy |
| TP-S9-E01 | S9 | 예외 | entry signal after official close; one-leg fill; no tick exactly at stabilization end; opening marks missing | after-close entry rejected; partial pair managed; missed end tick still triggers terminal policy; missing data explicit UNAVAILABLE | session evidence, open lots, event timestamps | NOT_RUN |
| TP-S9-R01 | S9 | 복구 | restart overnight with position open; next-session data delayed; previous-day entered_today flag stale | restore exact expiry/entry fills and opening window; no new entry or silent hold/reset | state restore, order/fill/position reconciliation | NOT_RUN |

## B. 전략 간 상호작용 시나리오

| 계획 ID | 상호작용 | 입력·조건 | 기대 결과 | 실행 상태 |
|---|---|---|---|---|
| TP-X01 | Account capital/premium reservation | S1~S9 simultaneously request entry with shared account capital | atomic budget reserve prevents aggregate premium/capital oversubscription | NOT_RUN |
| TP-X02 | Account max-loss override | strategy P&L and correlated stress loss push account limit | no new entry; approved risk reduction plan for existing exposure | NOT_RUN |
| TP-X03 | Shared Futures identity | S3 spread and S4/S5 hedge use same Futures identity | exposure owner/role aggregation; reject unintended offset/duplicate hedge | BLOCKED: role policy |
| TP-X04 | Option delta ownership | S1/S4 both consume option delta while another strategy owns option lots | no duplicate lot count or double hedge | NOT_RUN |
| TP-X05 | Overlapping insurance pairs | S6/S7/S8/S9 buy correlated PUT/CALL protection across expiries | account-level premium and stress correlation aggregation | NOT_RUN |
| TP-X06 | Same contract across strategies | multiple strategies own same option contract with different group IDs | lots are attributed once to account and separately to strategy owners | NOT_RUN |
| TP-X07 | Partial fill + account risk | one leg fills while another strategy entry is submitted | risk engine includes actual and worst-case pending exposure before second submit | NOT_RUN |
| TP-X08 | Cancel race | cancellation acknowledged late while fill arrives | late fill reconciled; no duplicate replacement order | NOT_RUN |
| TP-X09 | Restart with open lots | process restart with active/pending groups across strategies | reconcile all authoritative orders/fills/positions before any strategy re-entry | NOT_RUN |
| TP-X10 | Shared expiry/session boundary | multiple strategies enter terminal/expiry management simultaneously | calendar-consistent priorities and per-strategy close plans; account risk override deterministic | NOT_RUN |
| TP-X11 | P&L attribution | portfolio P&L differs from strategy-attributed P&L | strategy trailing uses only approved authoritative attribution; no portfolio proxy leakage | NOT_RUN |
| TP-X12 | Missing/stale market data | one source stale while account has open risk | new entries blocked; existing exposure managed via explicit UNAVAILABLE/reconciliation state | NOT_RUN |
| TP-X13 | Strategy 5 role change | alternative role/qty proposal compared against current Futures 5 and retired No.1168 | no automatic conversion; only approved role/structure is testable | BLOCKED: user decision |
| TP-X14 | Strategy 8 add-on | PUT-only overlay and base pair share expiry/contract | overlay plan changes only incremental approved quantity; no accidental full-pair recreation | NOT_RUN |
| TP-X15 | Trigger priority collision | max-loss, expiry, trailing, rebalance and entry occur in one evaluation | approved deterministic priority; terminal exit suppresses entry/rebuild | NOT_RUN |
| TP-X16 | Editable config reload | config version changes while positions are open | new config applies only under approved effective-time rule; existing positions retain config provenance | NOT_RUN |

## C. Entry criteria to start execution

1. User-approved version/scope exists for each strategy under test; unresolved thesis/leg-role choices are not guessed.
2. Every planned case maps to an exact test ID, fixture, source/contract identity and expected state.
3. Virtual/VTS execution path and data provenance are confirmed; Live endpoint is disabled.
4. Account capital/premium/max-loss numbers and configuration enforcement are separately approved.
5. Partial/reject/cancel-race/restart test harness records per-leg orders/fills/positions and group-level risk.
6. Test command, run ID, stdout/log, artifacts, and expected-vs-actual comparison are captured.
7. Only after actual logs are reviewed may a case be marked PASS/FAIL/BLOCKED. This plan currently has no executed test results.
# S1 scenario plan amendment v0.2 — direct user intent
- State: draft / unverified / unapproved / NOT_RUN.
- Controlling spec: strategy_1_tail_defense_spec_v0.3.md.
- IDs below are planning IDs, not executable pytest node IDs.

| Plan ID | Scenario | Preconditions/input | Expected behavior | Evidence | Run state |
|---|---|---|---|---|---|
| TP-S1-U01 | Rise/fall short accumulation using previous reference point | Valid approved config/REAL_VTS; policy now user-confirmed; actual execution remains disabled pending approval and implementation | On each +2.5pt crossing SELL PUT at previous reference - 7.5pt; on each -2.5pt crossing SELL CALL at previous reference + 7.5pt; then refresh reference to new ATM. Examples: 100→102.5 PUT 92.5; 102.5→105 PUT 95; 105→107.5 PUT 97.5. Actual+pending worst-case short exposure never exceeds 10 | ATM path, old/new reference, strike calculation, option identity, orders/fills, exposure snapshots, config hash | NOT_RUN |
| TP-S1-U02 | Retracement approaches nearest short strike | Actual short lots and non-null trigger distance selected only after REAL_VTS tuning/approval | 1:1 option hedge candidate for linked residual qty; no Futures hedge or duplicate hedge | short lot provenance, distance, target qty, candidate, risk preflight | NOT_RUN |
| TP-S1-U03 | Hedge quote gap then candidate fallback | First quote unavailable; alternative exists; 30-minute timer | LIMIT reservation for one candidate; after 30 minutes cancel; descend only after cancel terminal, leaves=0 and reconciliation | timestamps, order IDs, cancel ack, candidate quotes, fills | NOT_RUN |
| TP-S1-U04 | Fill during cancellation | Hedge order cancel-pending; delayed execution arrives | Do not submit next candidate; apply late fill; recompute hedge need and reconcile | event sequence, cancel state, cumulative fill/leaves, lineage | NOT_RUN |
| TP-S1-U05 | Combined short cap reaches 10 | CALL+PUT actual shorts plus pending worst-case exposure reaches 10 | Stop new shorts; preserve positions; hedge buys excluded from short count but subject to account risk | open lots, pending leaves, cap calc, risk decision | NOT_RUN |
| TP-S1-U06 | Hedge release at ±5.0pt | Linked hedge open; authoritative ATM crosses threshold away from short strike | Close actual remaining linked hedge qty; no reset until flat; short remains separate | price/strike distance, close plan, fills, open lots | NOT_RUN |
| TP-S1-U07 | Full close at DTE 4 | Exact expiry and approved DTE semantics; short, hedge and base CALL/PUT lots exist | Group terminal plan covers every remaining S1 lot; no new entry; lifecycle completes only after flat | expiry source, DTE calc, group/leg plan, fills, fees, flat snapshot | NOT_RUN |
| TP-S1-U08 | Flat market / no additional movement | Active positions, no approved short trigger crossed | No special trade; preserve positions and lifecycle | input snapshot, no-signal reason, unchanged lots/state | NOT_RUN |
| TP-S1-U09 | Partial fill | Any base/short/hedge/close leg partial or rejected | Independent per-leg state; recalculate actual exposure; no all-or-none assumption; block unsafe continuation until reconciled | per-leg order/fill/leaves, group state, position snapshot | NOT_RUN |
| TP-S1-U10 | Monthly boundary | DTE4 close complete; next monthly cycle not started | Preserve flat-confirmed old group; wait idle about 3–4 days after DTE4 flat until the next monthly cycle starts; do not re-enter early; no blind re-entry | calendar, flat snapshot, state transitions, config version | NOT_RUN |

| TP-S1-U11 | Multiple short_step_pt crossings and reference refresh | Multi-step REAL_VTS or derived scenario with documented provenance; policy itself is resolved, execution is not authorized by this plan | Process each crossing against the immediately previous reference point; calculate strike from that point; then refresh reference to the newly reached ATM. Upward crossings produce PUT strikes 92.5, 95, 97.5 for 100→102.5→105→107.5; downward crossings use the symmetric CALL formula | Ordered index/ATM path, each old/new reference, strike, direction, timestamps, config version/hash | NOT_RUN (policy resolved; implementation/replay unverified) |

Shared assertions:
1. PROVISIONAL config, null trigger, missing/stale source, unknown expiry or invalid identity blocks new orders.
2. Exact YYYYMMDD expiry and authoritative multiplier are used.
3. Each order/fill/position preserves run/group/leg/order/execution/config provenance.
4. Cancel request is not cancel completion; cancel race blocks candidate descent.
5. No lifecycle reset until all required lots are authoritatively flat.
6. REAL_VTS tuning and validation periods are separate; compare hedge_trigger_distance_pt candidates 2.5pt and 5.0pt without preselecting a winner; synthetic data is never relabeled REAL_VTS.
7. The new_short_stop_dte setting is removed; no DTE7 entry-stop rule is applied.
8. Sale-time premium matching compares option premium prices themselves, not strike distance.
9. After DTE4 full close and authoritative flat, S1 stays idle about 3–4 days until the next monthly cycle.
U28 is resolved by the user correction dated 2026-10-13. Scenario execution remains NOT_RUN because the current code does not implement the rule and this document-only task does not authorize code changes or tests.
11. No tests were executed in this document task.
## Integrated decision scenarios amendment (2026-10-12; planning only, NOT_RUN)
| Plan ID | Scenario | Expected result | State |
|---|---|---|---|
| TP-X-S9-01 | Per-lot stop at 50% of entry | Close that lot's remaining quantity; no cross-lot average-price substitution | NOT_RUN |
| TP-X-S9-02 | 2x arm then 10% drawdown | Arm per-lot high-water tracking at 2.00x entry; close only when premium falls 10% from peak | NOT_RUN |
| TP-X-S9-03 | S1 flat before DTE7 | S9 remains independently held; S1 flat alone does not trigger S9 close | NOT_RUN |
| TP-X-ID-01 | S5 U-ID collision | S1 U16–U29 unchanged; S5 items namespaced S5-U16–S5-U20; S9 U30–U37 unchanged | NOT_RUN |

- DTE7 rollover calendar semantics and exact execution timing remain unresolved. This plan amendment does not indicate test execution or implementation approval.

## Cross-strategy scenario addendum — S9 DTE7 (planning only; NOT_RUN)
| Plan ID | Scenario | Expected result | State |
|---|---|---|---|
| TP-X-S9-DTE-01 | Trading-day DTE7 at 11:00 KST | Evaluate rollover with authoritative trading calendar | NOT_RUN |
| TP-X-S9-DTE-02 | Next expiry not listed | Wait/monitor; no substitute order; trade after listing and preflight | NOT_RUN |
| TP-X-S9-REC-01 | Restart with trailing active | Restore lot state and reconcile broker positions before trading | NOT_RUN |
| TP-X-S9-REC-02 | Stale quote or partial fill | Block unsafe action until quote/position reconciliation | NOT_RUN |
| TP-X-S9-PRI-01 | Trailing + stop + rollover simultaneous | Trailing > stop-loss > rollover; reconcile before next action | NOT_RUN |

- S9-only policy; no test execution or implementation approval implied.


## S9 validation-gate cross-reference (planning only; NOT_RUN)
- Calendar source/off-by-one/holiday and next-expiry listing tests: see `TP-S9-CAL-01/02` in the S9 delta scenario plan.
- Quote freshness tests must cover missing timestamps, stale quote, clock skew, disconnect gaps, and wrong contract identity; threshold remains unset pending VTS evidence.
- Restart tests must cover multi-lot restoration, trailing high-water persistence, partial/late fills, cancel races, duplicate execution IDs and broker position mismatch.
- Detailed expected results and evidence: `05_strategy_9_dte7_quote_restart_validation_addendum_v0.1.md`. No tests executed.



---

## Strategy 6 v0.3 scenario amendment — planning only, NOT_RUN (2026-10-13)

These cases supersede the old S6 15:00/15:12/15:15 and intrinsic-proxy expectations in the earlier v0.2 section. Earlier records remain preserved as history.

| Case ID | Class | Setup / boundary | Expected result | Evidence required | Status |
|---|---|---|---|---|---|
| TP-S6-V03-N01 | normal | valid session, both ATM IV values valid, ratio >1.3, rank-5 quote valid | one order only; no active before fill | IV source timestamps, config hash, order intent | NOT_RUN |
| TP-S6-V03-B01 | boundary | ratio exactly 1.3 | eligible only if all other gates pass | canonical IV values | NOT_RUN |
| TP-S6-V03-B02 | boundary | ratio just below 1.3 | no order | input snapshot/reason | NOT_RUN |
| TP-S6-V03-B03 | boundary | trigger exactly 11:00 and just after | config-defined boundary; after cutoff no new entry | official KST timestamp/config | NOT_RUN |
| TP-S6-V03-B04 | boundary | before official open or invalid calendar | no order | calendar/source status | NOT_RUN |
| TP-S6-V03-N02 | sequential rank | rank 5 has no executable listed quote, rank 6 valid | never have two live candidate orders; next candidate only after prior non-submission/cancel completion | preflight/order/cancel evidence | NOT_RUN |
| TP-S6-V03-E01 | timeout | first submitted order has zero fill at 10 minutes | cancel, reconcile late fill, end entry for day; no retry | request/fill/cancel timestamps | NOT_RUN |
| TP-S6-V03-E02 | cancel race | fill arrives during cancel-pending | apply late fill; do not submit next candidate until reconciliation | event sequence/execution IDs | NOT_RUN |
| TP-S6-V03-N03 | first fill | CALL fills before PUT | store actual CALL fill; start opposite timer; not pair-active | execution and position snapshots | NOT_RUN |
| TP-S6-V03-N04 | pair complete | PUT fills within permitted window | PAIR_ACTIVE only after both legs reconcile | per-leg fills/positions/group IDs | NOT_RUN |
| TP-S6-V03-E03 | opposite no-fill | opposite leg not filled within 10 minutes | cancel/reconcile; keep actual first leg as single-leg holding | cancel and position evidence | NOT_RUN |
| TP-S6-V03-E04 | partial fill | any order has partial fill | filled/leaves separate; never assume full 1 contract filled | order reports and lots | NOT_RUN |
| TP-S6-V03-B05 | trailing arm | one leg mark equals its actual entry fill ×2 | arm that leg only; no immediate close solely at 2× | fill, mark and watermark | NOT_RUN |
| TP-S6-V03-B06 | trailing boundary | mark just above and exactly at 90% of own high-water | above: hold; at/below: close that leg | high-water and timestamped mark | NOT_RUN |
| TP-S6-V03-N05 | independent legs | CALL reaches 2× while PUT does not | CALL trail armed; PUT unarmed | per-leg states | NOT_RUN |
| TP-S6-V03-E05 | stale/missing mark | open leg but mark stale/missing | no proxy P&L; retain exposure for reconciliation/exit management | source/receive time and reason | NOT_RUN |
| TP-S6-V03-B07 | hard cutoff | one second before, exactly at, and after 15:10 | at/after cutoff, all actual residual S6 legs become close targets | official clock and close batch | NOT_RUN |
| TP-S6-V03-E06 | partial close | one close leg fills and another remains | EXIT_PENDING until all residual lots flat | per-leg remaining qty and positions | NOT_RUN |
| TP-S6-V03-R01 | restart | restart with single leg, pair, pending order or trailing watermark | restore/reconcile orders, fills, positions and config before evaluation | before/after snapshots and provenance | NOT_RUN |
| TP-S6-V03-E07 | invalid contract | wrong expiry/type/strike/multiplier or unlisted symbol | BLOCKED; no order | authoritative Option Master result | NOT_RUN |
| TP-S6-V03-E08 | missing config | first_rank, timeout_split, quote source/freshness or config version null | BLOCKED; no default substitution | config validation report | NOT_RUN |
| TP-S6-V03-X01 | cross-strategy risk | S6/S7/S8/S9 insurance exposures overlap | aggregate premium, margin, quantities and correlated stress; no double-counted protection | account risk snapshot | NOT_RUN |
| TP-S6-V03-X02 | S1 overlap | S1 short/strangle and S6 pair coexist | preserve owner/group and count actual lots once in account risk | positions and aggregate exposure | NOT_RUN |
| TP-S6-V03-X03 | config reload | config changes while a lot remains open | existing lot retains entry config version/hash; effective-time policy gates new orders | config/lot lineage | NOT_RUN |

### Cross-strategy interaction updates
- TP-X05: include S6 daily, S7 weekly, S8 monthly/overlay and S9 insurance premium/expiry/correlated tail exposure; S6/S7/S8 margin and quantity aggregation is mandatory.
- TP-X07/TP-X08: an S6 first-leg/partial fill is included in worst-case account exposure; cancel race cannot trigger a duplicate rank order.
- TP-X09: restart reconciliation includes S6 single-leg state and per-leg high-water.
- TP-X10/TP-X15: S6 15:10 forced close precedes S6 trailing; shared account emergency override follows common approved risk policy.
- TP-X12: stale IV/quote/mark blocks new entry; existing exposure must not be silently dropped.
- All cases remain NOT_RUN. This is a test plan, not implementation or approval evidence.


## Strategy 7 v0.3 scenario plan amendment (2026-10-13)
These S7-V03 cases are current planning IDs; older TP-S7 cases remain historical v0.2 cases. All are NOT_RUN unless marked BLOCKED.

| Test ID | Type | Setup/boundary | Expected result | Evidence | Status |
|---|---|---|---|---|---|
| S7-V03-N01 | Normal | Monday group start, ratio exactly 1.30, master/quotes valid | Entry candidate only after all data/risk gates | master, active/base, timestamps, config hash | NOT_RUN |
| S7-V03-N02 | Normal | Thursday group starts while Monday group remains open | Independent group/lot/expiry/high-water; no overwrite | group/order/position snapshots | NOT_RUN |
| S7-V03-N03 | Normal | Rank 5 valid | One single-leg order; no simultaneous rank 6 or pair order | order timeline | NOT_RUN |
| S7-V03-B01 | Boundary | ratio 1.2999/1.3000/1.3001 | Only >= threshold passes | source values/decision trace | NOT_RUN |
| S7-V03-B02 | Boundary | Rank 5 invalid/illiquid, rank 6 valid | Cancel/terminal reconcile before rank 6 | quote/cancel/fill IDs | NOT_RUN |
| S7-V03-B03 | Boundary | timeout 9:59/10:00/10:01; fill arrives during cancel | No next order before terminal state and fill reconciliation | event sequence/order IDs | NOT_RUN |
| S7-V03-B04 | Boundary | 14:59:59/15:00:00/15:00:01 | No new entry after 15:00; timeout crossing cutoff blocked by U17 | clock/config/order state | BLOCKED U17 |
| S7-V03-E01 | Exception | First leg fills; opposite leg not filled within 10 min | Preserve one-sided lot; retry/hold decision blocked by U16 | fills/cancel/residual qty | BLOCKED U16 |
| S7-V03-E02 | Exception | mark 49.99%/50%/50.01% of actual entry | Stop that leg at/below 50% | fill basis/mark/close report | NOT_RUN |
| S7-V03-E03 | Exception | mark 1.99x/2x/2.01x entry | High-water activates at >=2x; not immediate exit | mark sequence/state | NOT_RUN |
| S7-V03-E04 | Exception | 9.99%/10%/10.01% drop from high-water | Close leg at >=10% decline | watermark/marks | NOT_RUN |
| S7-V03-E05 | Exception | One leg stops while other remains open | Close only triggered leg residual; monitor other independently | per-leg positions/fills | NOT_RUN |
| S7-V03-E06 | Exception | Monday/Thursday groups coexist with S6/S8/S9 | Independent group state and aggregate risk; no double-counted protection | group IDs/account risk | BLOCKED account config |
| S7-V03-E07 | Exception | expiry YYYYMMDD vs ISO date | Canonical expiry identity matches | raw/canonical expiry | NOT_RUN |
| S7-V03-E08 | Exception | Holiday-shortened week | Official calendar and Option Master, no weekday inference | calendar/master evidence | BLOCKED source |
| S7-V03-E09 | Boundary | expiry 15:09:59/15:10:00/15:10:01 | Close workflow starts 15:10; flat only after fills/position confirm | clock/orders/fills/flat snapshot | NOT_RUN |
| S7-V03-R01 | Recovery | Restart with pending order/open lot/high-water | Restore both groups before resuming; no blind reset | durable state/ledger | NOT_RUN |
| S7-V03-R02 | Recovery | Missing/stale volatility or option mark | New entry blocked; no zero/synthetic substitute | source timestamps/BLOCKED trace | BLOCKED freshness |
| S7-V03-R03 | Recovery | Partial close/reject/cancel-race/late fill | Actual residual qty drives action; reset only after flat | order/fill/position timeline | NOT_RUN |
| S7-V03-X01 | Cross-strategy | S1/S6/S7/S8/S9 tail exposure overlap | Aggregate premium/margin/stress; no unsupported netting | account risk by strategy/group/expiry | BLOCKED |
| S7-V03-X02 | Cross-strategy | Two S7 groups plus S6/S8/S9 compete for account budget | Block if caps unset/exceeded; never increase S7 qty | config/reserve/risk decision | BLOCKED |

## Strategy 8 v0.3 scenario delta (plan only; not executed)

| Scenario ID | Type | Scenario / expected result | Status |
|---|---|---|---|
| TP-S8-V03-N01 | Normal | Valid master/window/vol=1.3/risk pass; one single-leg order | NOT_RUN |
| TP-S8-V03-B01 | Boundary | Vol ratio below/equal/above 1.3 | NOT_RUN |
| TP-S8-V03-B02 | Boundary | Rank 5 unavailable; rank 6 only after cancel confirmation | NOT_RUN |
| TP-S8-V03-B03 | Boundary | 10-minute timeout; cancel request alone cannot replace | NOT_RUN |
| TP-S8-V03-E01 | Exception | Fill during cancel blocks alternate rank and reconciles qty | NOT_RUN |
| TP-S8-V03-E02 | Exception | Partial fill/cancel race records filled and remaining qty | NOT_RUN |
| TP-S8-V03-N02 | Normal | Opposite leg separately submitted; pair complete only after both fills | NOT_RUN |
| TP-S8-V03-E03 | Exception | Opposite leg timeout while timeout_split null | BLOCKED: user decision |
| TP-S8-V03-B04 | Boundary | Mark around 50% entry fill triggers per-leg stop | NOT_RUN |
| TP-S8-V03-B05 | Boundary | Mark reaches 2x fill and activates high-water | NOT_RUN |
| TP-S8-V03-B06 | Boundary | Mark reaches 90% high-water and closes that leg remaining qty | NOT_RUN |
| TP-S8-V03-E04 | Exception | New high compared to prior watermark before update | NOT_RUN |
| TP-S8-V03-E05 | Exception | Missing/stale/wrong-contract mark blocks action | NOT_RUN |
| TP-S8-V03-B07 | Boundary | Expiry day 15:09:59/15:10:00/15:10:01 | NOT_RUN |
| TP-S8-V03-E06 | Exception | Pending cancel overlaps 15:10 close; reconcile race | NOT_RUN |
| TP-S8-V03-E07 | Recovery | Restart with working order/partial fill/open leg reconciles first | NOT_RUN |
| TP-S8-V03-X01 | Cross-strategy | Same contract S1/S8 has separate lots/exit owners | NOT_RUN |
| TP-S8-V03-X02 | Cross-strategy | S6/S7/S8 risk aggregated; unset cap blocks | BLOCKED: risk config |
| TP-S8-V03-B08 | Boundary | DTE 15/14 and budget 200000/below while gates unresolved | BLOCKED: user decision |
| TP-S8-V03-R01 | Recovery | Config change does not alter open lot provenance | NOT_RUN |
| TP-S8-V03-E08 | Exception | Macro regime changes never scale PUT quantity | NOT_RUN |



## Strategy 2 v0.3 scenario amendment — 2026-10-13 (planning only; NOT_RUN)

- 작성일: 2026-10-13; 상태: planning only / NOT_RUN / draft / unverified / unapproved.
- Existing common plans v0.1–v0.4 and S5/S9 delta plans are preserved. No tests/REAL_VTS replay were run.

## A. Entry and structure selection

| Scenario ID | Class | Input / boundary | Expected target behavior | Evidence | Status |
|---|---|---|---|---|---|
| S2-V03-N01 | Normal | All features fresh; monthly cycle eligible; ratio <0.85; risk passes | Select wide structure; exact listed standard contracts; prescribed 4-leg sequence | feature snapshot, expiry/IDs, quotes, risk, hash | NOT_RUN |
| S2-V03-N02 | Normal | Ratio >0.85; features valid | Select narrow structure; no inferred alternative | same as above | NOT_RUN |
| S2-V03-B01 | Boundary | ratio 0.8499/0.8500/0.8501 | `<=` boundary documented; base<=0 blocks | raw vol values and branch decision | NOT_RUN |
| S2-V03-B02 | Boundary | volume z 2.99/3.00/3.01 | Strict `>3.0`; equality excluded unless later approved spec changes it | source/time/formula/decision | NOT_RUN |
| S2-V03-B03 | Boundary | abs OBI 0.499/0.500/0.501 | Strict `>0.5`; stale/missing depth blocks | order book source/time | NOT_RUN |
| S2-V03-B04 | Boundary | basis 0.299/0.300/0.301 | Strict `>0.3` only with verified units/sign | synchronized futures/index observations | NOT_RUN / source blocked |
| S2-V03-B05 | Boundary | abs(price−POC) 0.999/1.000/1.001; price exactly POC | Strict `>1.0`; IV comparison follows documented location rule | POC and matched IV provenance | NOT_RUN |
| S2-V03-B06 | Boundary | bbw null/empty/stale/zero/negative/boolean-like | undefined or stale BBW blocks; no truthy fallback | raw window/sample/freshness | NOT_RUN / formula pending |
| S2-V03-B07 | Boundary | IV missing/stale or expiry/strike mismatch | no entry; no alternate expiry or inferred IV | contract IDs/timestamps | NOT_RUN |
| S2-V03-B08 | Boundary | ATM tie, offset strike not listed, tick rounding boundary | no inferred rounding; block until approved listed-strike rule | Option Master chain/selection audit | NOT_RUN / S2-U17 |
| S2-V03-E01 | Exception | risk config missing/null/PROVISIONAL | block before any order | config hash and risk decision | NOT_RUN |

## B. Sequential order and per-leg lifecycle

| Scenario ID | Class | Event | Expected target behavior | Evidence | Status |
|---|---|---|---|---|---|
| S2-V03-O01 | Normal | inner PUT BUY fully fills | only then submit inner CALL BUY | order/fill IDs and positions | NOT_RUN |
| S2-V03-O02 | Normal | both inner buys fully filled/reconciled | only then submit outer PUT SELL | actual long lots and risk check | NOT_RUN |
| S2-V03-O03 | Normal | outer PUT SELL fully fills | only then submit outer CALL SELL | sequence and per-leg state | NOT_RUN |
| S2-V03-B09 | Boundary | timeout at 9:59/10:00/10:01 | apply 10-minute wait; no next leg while prior order uncertain | order timestamps/status | NOT_RUN |
| S2-V03-E02 | Exception | first inner PUT rejected/no fill | no remaining legs submitted | rejection and absence of later order IDs | NOT_RUN |
| S2-V03-E03 | Exception | first inner PUT partial, remainder cancel pending | cancel-confirm and late-fill reconciliation; no next leg; recovery or BLOCKED | fills/leaves/cancel/position evidence | NOT_RUN / S2-U16 |
| S2-V03-E04 | Exception | inner CALL rejected/partial after inner PUT filled | no outer sells; reconcile actual PUT lot; recovery or BLOCKED | both order histories/positions | NOT_RUN / S2-U16 |
| S2-V03-E05 | Exception | outer PUT partial/rejected | no outer CALL until outer PUT fully fills; recalc exposure | 3 leg states and risk/close plan | NOT_RUN / S2-U16 |
| S2-V03-E06 | Exception | outer CALL partial/rejected | do not assume 4-leg completion; reconcile all actual lots | 4 leg reports/positions | NOT_RUN / S2-U16 |
| S2-V03-E07 | Exception | fill arrives during/after cancel request | cancel request is not terminal; no next leg before final state reconciles | event times, order IDs, cumulative fills | NOT_RUN |
| S2-V03-E08 | Exception | duplicate evaluation while pending/active | no duplicate group; monthly cycle consumed once | group ID, state, orders, lots | NOT_RUN |
| S2-V03-R01 | Recovery | restart with working/cancel-pending order, partial lot or late fill | restore orders/fills/positions/config, reconcile before evaluation/reset | restart logs and position snapshot | NOT_RUN / S2-U19 |

## C. Option-price P&L, trailing and expiry close

| Scenario ID | Class | Input | Expected target behavior | Evidence | Status |
|---|---|---|---|---|---|
| S2-V03-P01 | Normal | four actual filled legs; valid marks, multiplier, fees | group P&L from signed option marks/fills, not underlying return | fills, marks, multiplier, fees/slippage, ledger | NOT_RUN / S2-U18 |
| S2-V03-P02 | Boundary | option-group P&L ratio −30.01/−30.00/−29.99% | apply approved stop formula; threshold remains provisional until approved | marks, net entry cost, trigger | NOT_RUN |
| S2-V03-P03 | Boundary | trailing activation 29.99/30.00/30.01% | activation follows approved formula | P&L series/high-watermark/hash | NOT_RUN |
| S2-V03-P04 | Boundary | high-watermark 49.99/50/50.01%, 99.99/100/100.01% | tier transitions follow approved formula | P&L/tier events | NOT_RUN |
| S2-V03-P05 | Exception | net entry cost<=0, mark missing/stale, multiplier/fee mismatch | no divide-by-zero or fabricated P&L; block metric action and reconcile; terminal close remains | input/guard/reason | NOT_RUN / S2-U18 |
| S2-V03-P06 | Exception | legacy short-switch timer fires after trailing exit | target path contains no `SHORT_SWITCH_TIMEOUT_EXIT` | state/timer/event log | NOT_RUN |
| S2-V03-T01 | Boundary | monthly expiry day 15:09:59/15:10:00/15:10:01 | at/after 15:10 start terminal close; no entry; no false flat | expiry/calendar/clock/orders/fills/positions | NOT_RUN |
| S2-V03-T02 | Exception | close leg partial/reject/cancel race at 15:10 | remain EXIT_PENDING/RECONCILIATION_REQUIRED until all actual lots flat | leaves/late fills/position snapshots | NOT_RUN |
| S2-V03-T03 | Normal | all lots flat before next monthly cycle | same-expiry re-entry prohibited; next cycle waits for calendar eligibility | monthly calendar/group state/flat evidence | NOT_RUN |
| S2-V03-T04 | Recovery | restart during 15:10 close | restore/reconcile, continue terminal close without blind duplicate orders | restart/order/position evidence | NOT_RUN |

## D. Cross-strategy account risk

| Scenario ID | Class | Input | Expected target behavior | Evidence | Status |
|---|---|---|---|---|---|
| S2-V03-X01 | Interaction | S2 and S1/S6/S7/S8/S9 overlap strike/expiry | aggregate premium, margin, Greeks/delta and stress; no automatic protection credit | owner/group/leg positions, marks, stress matrix | NOT_RUN |
| S2-V03-X02 | Interaction | account/strategy cap reached by actual + pending worst-case exposure | block S2 before first order; pending leaves included | account risk snapshot/orders/gate | NOT_RUN |
| S2-V03-X03 | Interaction | same option identity belongs to another strategy | do not net or close another strategy's lot as S2 recovery | provenance and close plan | NOT_RUN |
| S2-V03-X04 | Interaction | common account read model stale/unavailable | block new entry; retain reconciliation/terminal management | read-model status/timestamp | NOT_RUN |

## E. Acceptance requirements

Each executed case must link exact test ID, dataset ID with REAL_VTS vs derived/synthetic provenance, config version/hash, input timestamps, per-leg orders/fills/cancels, actual positions, P&L ledger, logs and outcome. Scenario labels here are planned groups, not claims that executable tests already exist. Document structure is not strategy validation or implementation approval.
## S2-U20/U21 additional scenarios

| Scenario ID | Class | Input / boundary | Expected target behavior | Evidence | Status |
|---|---|---|---|---|---|
| S2-V03-E09 | Policy ambiguity | first leg zero fill at 10 min; cancel confirmed; next leg otherwise eligible | Do not automatically advance until S2-U20 policy is resolved; no second order ID emitted | order/cancel events, monthly cycle state, decision reason | BLOCKED / NOT_RUN |
| S2-V03-B10 | Limit price config | limit basis/tick rule/quote max age/max spread each null or invalid | block before first order; no implicit MID_PRICE_OFFSET fallback | config hash, bid/ask/depth/time, tick and spread decision | NOT_RUN |
| S2-V03-B11 | Limit price boundary | valid quote at tick rounding boundary and spread just below/equal/above configured cap | follow approved rounding and spread semantics; if rule not approved, BLOCKED | raw quote, limit price, tick, spread and rule version | NOT_RUN |

## Strategy 3 v0.3 scenario amendment — planning only / NOT_RUN (2026-10-13)

These cases target the proposed near-month minus far-month KOSPI200 Futures calendar spread. No tests were executed. All cases are NOT_RUN unless explicitly BLOCKED.

| Test ID | Class | Setup / boundary | Expected target behavior | Evidence | Status |
|---|---|---|---|---|---|
| S3-V03-N01 | Normal | valid near/far master identities, synchronized quotes, sufficient spread history, capital/cost gates configured | build `near - far`, calculate z, emit candidate only if after-cost edge passes; strategy remains disabled absent activation approval | IDs/expiry/quotes/history/config hash | BLOCKED: activation and risk gates |
| S3-V03-B01 | Boundary | z at entry threshold 1.9999/2.0000/2.0001 | exact approved comparison semantics; current 2.0 remains provisional | z inputs/window/decision | NOT_RUN |
| S3-V03-B02 | Boundary | z around exit 0.1999/0.2000/0.2001 | convergence exit follows approved boundary | z history and exit decision | NOT_RUN |
| S3-V03-B03 | Boundary | abs(z) around stop 3.4999/3.5000/3.5001 | stop gate precedes lower-priority profit/timeout triggers | z and priority trace | NOT_RUN |
| S3-V03-B04 | Boundary | near/far quote timestamps within/outside configured tolerance | outside tolerance blocks spread creation; no stale fallback | source/receive timestamps and tolerance config | BLOCKED: tolerance unset |
| S3-V03-E01 | Exception | same identity or same expiry supplied for both legs | reject before order plan; no economic spread | resolved identities and preflight reason | NOT_RUN |
| S3-V03-E02 | Exception | missing/unknown multiplier, cost, quote, P&L | BLOCKED/UNAVAILABLE; no default zero/guess | provider result and gate trace | NOT_RUN |
| S3-V03-E03 | Exception | spread history is futures-index basis instead of near/far | reject wrong spread type; do not fallback to No.956 basis | series provenance and source identities | NOT_RUN |
| S3-V03-E04 | Exception | `_exit_pending` reached before `regime` assignment | expected implementation must avoid uninitialized-variable exception; current path is a known issue, test not run | stack/log and input state | NOT_RUN; code change prohibited here |
| S3-V03-E05 | Exception | adapter returns equal quantity opposite sides for same identity | preflight blocks net-zero/canceling pseudo-spread | leg identities/sides/qty | BLOCKED: current adapter mismatch |
| S3-V03-O01 | Order lifecycle | near leg fills, far leg has no fill/partial fill | remain PARTIALLY_EXPOSED; reconcile actual risk; no ACTIVE pair assumption | per-leg order/fill/leaves/position snapshots | NOT_RUN |
| S3-V03-O02 | Cancel race | cancel requested, late fill arrives before terminal state | do not retry/submit duplicate; recompute residual exposure from cumulative fills | order events/execution IDs/position | NOT_RUN |
| S3-V03-O03 | Exit lifecycle | one leg closes, other close rejected/partial | EXIT_PENDING until all actual lots flat; retry based only on reconciled residual lots | close orders/fills/position snapshots | NOT_RUN |
| S3-V03-R01 | Recovery | restart with pending order, partial fill, open spread or EXIT_PENDING | restore config/order/fill/position state and reconcile before evaluation | before/after state and provenance | NOT_RUN |
| S3-V03-T01 | Time boundary | 15:09:59/15:10:00/15:10:01 | proposed force close starts at/after 15:10; no overnight and no false-flat state | official time/session/order/fill/position | BLOCKED: cutoff conflict in code |
| S3-V03-T02 | Timeout | elapsed time vs 300 evaluate calls | do not treat calls as minutes; block timeout behavior while max_hold_minutes null | timestamps/config and holding duration | BLOCKED: max_hold_minutes null |
| S3-V03-X01 | Cross-strategy | S3/S4/S5 futures positions share margin/identity | aggregate actual and pending exposure; preserve lot owner; no unsupported offset | account margin and strategy provenance | BLOCKED: account config |
| S3-V03-X02 | Config lineage | config changes while group open | open group retains entry config hash; new config applies only by approved effective-time rule | group/config history | NOT_RUN |
| S3-V03-X03 | No.956 conflict | old Futures−Index basis is supplied while calendar spread is selected | preserve No.956; do not mutate decision log; reject mismatch and flag proposed deprecation only | decision record and source identities | GOVERNANCE CHECK |
| S3-V03-A01 | Acceptance | each F01–F29 has exact case and evidence | test mapping complete before validation claim | traceability matrix/run artifacts | NOT_RUN |

### Scenario completion boundary
All S3 cases above are plans, not executable-test claims. No test suite, REAL_VTS replay, or KIS Live order was run in this document-only task. Passing a future scenario set will not itself authorize Strategy 3 activation.

## Strategy 4 v0.3 additional scenarios — plan only, NOT_RUN

| Case ID | Type | Setup / boundary | Expected safe behavior | Required evidence | Status |
|---|---|---|---|---|---|
| TP-S4-V03-N01 | Normal | Approved enablement, capital gate PASS, fresh IV/quotes, actual S4 option lots filled, own-option delta exceeds band | hedge target computed from verified multipliers; order only after risk preflight; actual hedge qty changes only on fill | config hash, option lots, Greeks lineage, contract master, order/fill/position | NOT_RUN |
| TP-S4-V03-B01 | Boundary | delta exactly equals deadband; next representable value above; one-mini-contract delta quantum | deterministic no-hedge/hedge boundary; deadband cannot leave impossible sub-contract oscillation | delta units, rounding, multiplier and target qty | BLOCKED / NOT_RUN |
| TP-S4-V03-B02 | Boundary | `enabled=false`; `capital_gate_min=null`; capital just below/equal/above approved threshold | no new S4 entry/hedge exposure while disabled; null blocks; exact boundary follows documented comparator | registry, allocator, risk decision, no order plan | NOT_RUN |
| TP-S4-V03-E01 | Exception | BASECAMP NON_EXECUTION but no filled option lots; aggregate account delta nonzero | no S4 Futures hedge signal; no inference that basecamp represents options | event kind, actual positions, emitted plan | NOT_RUN |
| TP-S4-V03-E02 | Exception | IV unavailable/stale, multiplier missing, Greeks timestamp mismatch, quote stale | fail-closed for new risk; no fabricated delta/zero/default | source status, timestamps, block reason | NOT_RUN |
| TP-S4-V03-E03 | Exception | option call fills but put rejects/partial; cancel races with late fill | reconcile each leg; hedge only actual eligible filled option inventory; terminal recovery policy applied | per-leg orders/fills/leaves and positions | NOT_RUN |
| TP-S4-V03-E04 | Exception | Futures rebalance partially fills or rejects; target differs from actual quantity | target/pending/actual separated; recompute residual from authoritative fills; no blind duplicate | order reports, target/actual/pending qty, position snapshot | NOT_RUN |
| TP-S4-V03-E05 | Exception | simultaneous risk exit, expiry, trailing and delta rebalance | risk/expiry/terminal exit wins; no new rebalance; options and linked hedge included in terminal grouped plan | trigger snapshot, plan IDs, per-leg fills | NOT_RUN |
| TP-S4-V03-E06 | Exception | P&L feed is account-wide or `premium_spent` missing; theta cost unavailable | do not compute S4 trailing from account P&L or substitute zero theta cost; BLOCKED | source ownership, marks, cost ledger | NOT_RUN |
| TP-S4-V03-R01 | Recovery | restart with working/cancel-pending orders, partial options/Futures fills, old config hash | restore orders/fills/positions, reconcile actual inventory and config before resuming; no reset until flat | restart logs, authoritative position read model, hash | NOT_RUN |
| TP-S4-V03-R02 | Recovery | 15:10 close boundary and delayed/late fill | terminal close remains pending until all required legs reconcile flat; no overnight state reset | clock/calendar, fills, remaining lots, close batch | NOT_RUN |
| TP-S4-V03-X01 | Cross-strategy | S1 and S4 read overlapping aggregate delta; S3/S5 share Futures identity/margin | no duplicate hedge ownership; account risk still aggregates all actual/pending exposure | strategy/lot ownership, Futures lots, margin and account risk | BLOCKED / NOT_RUN |
| TP-S4-V03-P01 | P&L | options and Futures actual fills, timestamp-aligned marks, fees/slippage and theta evidence | S4 P&L attributed to own options plus linked Futures and costs; no account-P&L proxy | fills, marks, multiplier, cost ledger, theta lineage | BLOCKED / NOT_RUN |

All added cases are plans only. No tests or REAL_VTS replay were executed.

## S1 user-confirmed reference/strike correction — 2026-10-13 (planning only; NOT_RUN)
- U28 policy status: RESOLVED. Strike uses the previous reference point, not current/new ATM.
- Each +2.5pt crossing: SELL PUT at previous reference - 7.5pt. Each -2.5pt crossing: SELL CALL at previous reference + 7.5pt. Then update reference point to the newly reached ATM.
- Required examples: 100→102.5 gives PUT 92.5; 102.5→105 gives PUT 95; 105→107.5 gives PUT 97.5. Downward movements are symmetric CALL cases.
- This resolves the policy ambiguity only. Existing code gap remains; no tests or REAL_VTS replay were run, and no implementation approval is implied.

---
## v0.9 추가 시나리오 — S2/S5/S8/S9
상태: 계획 추가만 완료. 실행 결과는 전부 NOT_RUN이며 실제 전략 구현 완료를 의미하지 않는다.
### S2 — cancel/fill reconciliation
- cancel request pending → partial fill during cancel → cancel confirmed → execution query reveals late fill → residual target recomputed → only residual qty reissued.
- cancel confirmed with zero fills → target qty reissued once using new client_order_id only after prior order terminal confirmation.
- duplicate cancel/fill event, restart, stale quote, missing position snapshot, risk-cap failure → no duplicate order; RECONCILIATION_REQUIRED/BLOCKED.
- assert reorder_qty = max(0, target_qty - reconciled_filled_qty - valid_working_qty) and no reissue while a valid working order remains.
### S5 — whipsaw count
- gap entry → adverse move before advance_pt → opposite option hedge actually filled → underlying returns to gap direction across configured hedge-reversal boundary → exactly one whipsaw event.
- repeat ticks/same event ID/duplicate fill report → count remains one.
- hedge order ACK without fill, option premium wiggle without underlying trigger, or incomplete cancel/fill reconciliation → no confirmed count and no follow-on action.
- second confirmed cycle → no new entries for that day; all actual remaining S5 lots enter exit lifecycle; verify flat by position reconciliation, not order ACK.
### S8 — trading-day entry and retry
- exactly 10 trading sessions remain: entry gate passes if all other inputs/risk checks pass; 9 sessions remain: blocked.
- weekend/official holiday does not consume retry days; count first eligible trading day as day 1.
- 10-minute no-fill timeout with cancel/fill race; reconcile before retry.
- retries allowed only within 3 trading-day window; on day 3 at 15:00 KST no new retry; already filled exposure remains under separate position/risk management.
- prior KRW 200,000 budget value has no gating effect; missing common account/strategy risk caps still blocks entry.
### S9 — D-4 forced liquidation, priority and liquidity
- exact expiry/calendar vectors: four sessions remain at 11:00 KST → D-4 gate triggers; three/five remain → verify no off-by-one; holidays/invalid expiry → BLOCKED.
- S1 and S9 both due: S1 close intent is emitted first, then S9; S1 unresolved state must not indefinitely starve mandatory S9 exit.
- third strike quote stale/wide/insufficient depth → no arbitrary price; wait for new snapshot of same contract and recheck; unset liquidity threshold/retry interval → BLOCKED.
- D-4 cutoff during liquidity wait → cancel entry attempt; existing S9 positions still enter mandatory exit/reconciliation lifecycle. D-4 is the fourth actual KRX trading session strictly before expiry, excluding expiry day, weekends, official holidays, temporary closures and other non-trading sessions (user-approved 2026-10-13).
- cancel/close race with late fill → remain EXIT_PENDING until authoritative position is flat; DTE7 rollover must not reactivate.
### Acceptance evidence
All above remain NOT_RUN until executed against the actual approved strategy path with reproducible REAL_VTS order/fill/quote/calendar evidence. Synthetic fixtures may test invariants but cannot be reported as REAL_VTS validation. Missing freshness, liquidity, slippage or retry parameters block runtime activation.


---

# Canonical consolidation notice

- This file is the newest consolidated draft as of 2026-10-13.
- Status remains draft / unverified / unapproved. This is not implementation authorization.
- The delta source files below are absorbed as preserved historical source text. For future review, use this consolidated file as the current matrix/traceability/scenario reference; do not treat the delta files as separate current standards. Historical files are retained and not deleted.
- Code/tests/config/manifest/commit/push/REAL_VTS replay were not run or changed in this document-only task.


---

# Absorbed historical delta: 04_strategy_1_to_9_scenario_test_plan_s2_delta_v0.2.md

# Strategy 1–9 scenario test plan — Strategy 2 delta v0.1

- 작성일: 2026-10-13; 상태: planning only / NOT_RUN / draft / unverified / unapproved.
- Existing common plans v0.1–v0.4 and S5/S9 delta plans are preserved. No tests/REAL_VTS replay were run.

## A. Entry and structure selection

| Scenario ID | Class | Input / boundary | Expected target behavior | Evidence | Status |
|---|---|---|---|---|---|
| S2-V03-N01 | Normal | All features fresh; monthly cycle eligible; ratio <0.85; risk passes | Select wide structure; exact listed standard contracts; prescribed 4-leg sequence | feature snapshot, expiry/IDs, quotes, risk, hash | NOT_RUN |
| S2-V03-N02 | Normal | Ratio >0.85; features valid | Select narrow structure; no inferred alternative | same as above | NOT_RUN |
| S2-V03-B01 | Boundary | ratio 0.8499/0.8500/0.8501 | `<=` boundary documented; base<=0 blocks | raw vol values and branch decision | NOT_RUN |
| S2-V03-B02 | Boundary | volume z 2.99/3.00/3.01 | Strict `>3.0`; equality excluded unless later approved spec changes it | source/time/formula/decision | NOT_RUN |
| S2-V03-B03 | Boundary | abs OBI 0.499/0.500/0.501 | Strict `>0.5`; stale/missing depth blocks | order book source/time | NOT_RUN |
| S2-V03-B04 | Boundary | basis 0.299/0.300/0.301 | Strict `>0.3` only with verified units/sign | synchronized futures/index observations | NOT_RUN / source blocked |
| S2-V03-B05 | Boundary | abs(price−POC) 0.999/1.000/1.001; price exactly POC | Strict `>1.0`; IV comparison follows documented location rule | POC and matched IV provenance | NOT_RUN |
| S2-V03-B06 | Boundary | bbw null/empty/stale/zero/negative/boolean-like | undefined or stale BBW blocks; no truthy fallback | raw window/sample/freshness | NOT_RUN / formula pending |
| S2-V03-B07 | Boundary | IV missing/stale or expiry/strike mismatch | no entry; no alternate expiry or inferred IV | contract IDs/timestamps | NOT_RUN |
| S2-V03-B08 | Boundary | ATM tie, offset strike not listed, tick rounding boundary | no inferred rounding; block until approved listed-strike rule | Option Master chain/selection audit | NOT_RUN / S2-U17 |
| S2-V03-E01 | Exception | risk config missing/null/PROVISIONAL | block before any order | config hash and risk decision | NOT_RUN |

## B. Sequential order and per-leg lifecycle

| Scenario ID | Class | Event | Expected target behavior | Evidence | Status |
|---|---|---|---|---|---|
| S2-V03-O01 | Normal | inner PUT BUY fully fills | only then submit inner CALL BUY | order/fill IDs and positions | NOT_RUN |
| S2-V03-O02 | Normal | both inner buys fully filled/reconciled | only then submit outer PUT SELL | actual long lots and risk check | NOT_RUN |
| S2-V03-O03 | Normal | outer PUT SELL fully fills | only then submit outer CALL SELL | sequence and per-leg state | NOT_RUN |
| S2-V03-B09 | Boundary | timeout at 9:59/10:00/10:01 | apply 10-minute wait; no next leg while prior order uncertain | order timestamps/status | NOT_RUN |
| S2-V03-E02 | Exception | first inner PUT rejected/no fill | no remaining legs submitted | rejection and absence of later order IDs | NOT_RUN |
| S2-V03-E03 | Exception | first inner PUT partial, remainder cancel pending | cancel-confirm and late-fill reconciliation; no next leg; recovery or BLOCKED | fills/leaves/cancel/position evidence | NOT_RUN / S2-U16 |
| S2-V03-E04 | Exception | inner CALL rejected/partial after inner PUT filled | no outer sells; reconcile actual PUT lot; recovery or BLOCKED | both order histories/positions | NOT_RUN / S2-U16 |
| S2-V03-E05 | Exception | outer PUT partial/rejected | no outer CALL until outer PUT fully fills; recalc exposure | 3 leg states and risk/close plan | NOT_RUN / S2-U16 |
| S2-V03-E06 | Exception | outer CALL partial/rejected | do not assume 4-leg completion; reconcile all actual lots | 4 leg reports/positions | NOT_RUN / S2-U16 |
| S2-V03-E07 | Exception | fill arrives during/after cancel request | cancel request is not terminal; no next leg before final state reconciles | event times, order IDs, cumulative fills | NOT_RUN |
| S2-V03-E08 | Exception | duplicate evaluation while pending/active | no duplicate group; monthly cycle consumed once | group ID, state, orders, lots | NOT_RUN |
| S2-V03-R01 | Recovery | restart with working/cancel-pending order, partial lot or late fill | restore orders/fills/positions/config, reconcile before evaluation/reset | restart logs and position snapshot | NOT_RUN / S2-U19 |

## C. Option-price P&L, trailing and expiry close

| Scenario ID | Class | Input | Expected target behavior | Evidence | Status |
|---|---|---|---|---|---|
| S2-V03-P01 | Normal | four actual filled legs; valid marks, multiplier, fees | group P&L from signed option marks/fills, not underlying return | fills, marks, multiplier, fees/slippage, ledger | NOT_RUN / S2-U18 |
| S2-V03-P02 | Boundary | option-group P&L ratio −30.01/−30.00/−29.99% | apply approved stop formula; threshold remains provisional until approved | marks, net entry cost, trigger | NOT_RUN |
| S2-V03-P03 | Boundary | trailing activation 29.99/30.00/30.01% | activation follows approved formula | P&L series/high-watermark/hash | NOT_RUN |
| S2-V03-P04 | Boundary | high-watermark 49.99/50/50.01%, 99.99/100/100.01% | tier transitions follow approved formula | P&L/tier events | NOT_RUN |
| S2-V03-P05 | Exception | net entry cost<=0, mark missing/stale, multiplier/fee mismatch | no divide-by-zero or fabricated P&L; block metric action and reconcile; terminal close remains | input/guard/reason | NOT_RUN / S2-U18 |
| S2-V03-P06 | Exception | legacy short-switch timer fires after trailing exit | target path contains no `SHORT_SWITCH_TIMEOUT_EXIT` | state/timer/event log | NOT_RUN |
| S2-V03-T01 | Boundary | monthly expiry day 15:09:59/15:10:00/15:10:01 | at/after 15:10 start terminal close; no entry; no false flat | expiry/calendar/clock/orders/fills/positions | NOT_RUN |
| S2-V03-T02 | Exception | close leg partial/reject/cancel race at 15:10 | remain EXIT_PENDING/RECONCILIATION_REQUIRED until all actual lots flat | leaves/late fills/position snapshots | NOT_RUN |
| S2-V03-T03 | Normal | all lots flat before next monthly cycle | same-expiry re-entry prohibited; next cycle waits for calendar eligibility | monthly calendar/group state/flat evidence | NOT_RUN |
| S2-V03-T04 | Recovery | restart during 15:10 close | restore/reconcile, continue terminal close without blind duplicate orders | restart/order/position evidence | NOT_RUN |

## D. Cross-strategy account risk

| Scenario ID | Class | Input | Expected target behavior | Evidence | Status |
|---|---|---|---|---|---|
| S2-V03-X01 | Interaction | S2 and S1/S6/S7/S8/S9 overlap strike/expiry | aggregate premium, margin, Greeks/delta and stress; no automatic protection credit | owner/group/leg positions, marks, stress matrix | NOT_RUN |
| S2-V03-X02 | Interaction | account/strategy cap reached by actual + pending worst-case exposure | block S2 before first order; pending leaves included | account risk snapshot/orders/gate | NOT_RUN |
| S2-V03-X03 | Interaction | same option identity belongs to another strategy | do not net or close another strategy's lot as S2 recovery | provenance and close plan | NOT_RUN |
| S2-V03-X04 | Interaction | common account read model stale/unavailable | block new entry; retain reconciliation/terminal management | read-model status/timestamp | NOT_RUN |

## E. Acceptance requirements

Each executed case must link exact test ID, dataset ID with REAL_VTS vs derived/synthetic provenance, config version/hash, input timestamps, per-leg orders/fills/cancels, actual positions, P&L ledger, logs and outcome. Scenario labels here are planned groups, not claims that executable tests already exist. Document structure is not strategy validation or implementation approval.
## S2-U20/U21 additional scenarios

| Scenario ID | Class | Input / boundary | Expected target behavior | Evidence | Status |
|---|---|---|---|---|---|
| S2-V03-E09 | Policy ambiguity | first leg zero fill at 10 min; cancel confirmed; next leg otherwise eligible | Do not automatically advance until S2-U20 policy is resolved; no second order ID emitted | order/cancel events, monthly cycle state, decision reason | BLOCKED / NOT_RUN |
| S2-V03-B10 | Limit price config | limit basis/tick rule/quote max age/max spread each null or invalid | block before first order; no implicit MID_PRICE_OFFSET fallback | config hash, bid/ask/depth/time, tick and spread decision | NOT_RUN |
| S2-V03-B11 | Limit price boundary | valid quote at tick rounding boundary and spread just below/equal/above configured cap | follow approved rounding and spread semantics; if rule not approved, BLOCKED | raw quote, limit price, tick, spread and rule version | NOT_RUN |

---
## v0.2 — S2 cancel/fill race scenarios
1. Cancel requested → partial fill during cancel → cancel confirmed → late fill reconciled → residual qty only reissued.
2. Cancel confirmed with zero fill → one residual target order; duplicate event does not create a second order.
3. Unknown cancel state, stale quote, valid working order or position mismatch → no retry; RECONCILIATION_REQUIRED/BLOCKED.
Acceptance remains NOT_RUN until tested against the actual approved execution path.


---

# Absorbed historical delta: 04_strategy_1_to_9_scenario_test_plan_s5_delta_v0.4.md

# Strategy 5 시나리오 테스트 계획 S5 delta v0.3

- 상태: draft / unverified / unapproved
- 작성일: 2026-10-12
- 기존 `04_strategy_1_to_9_scenario_test_plan_v0.2.md` 보존. 본 파일은 S5 시나리오 추가안이다.
- 실행 금지 범위: 본 작업에서는 어떤 테스트도 실행하지 않는다. 시나리오 설계만 한다.

| ID | 시나리오 | 입력/경계 | 기대 상태/안전 기준 |
|---|---|---|---|
| S5-T01 | 갭 없음 | abs(open-prev_close) < min_gap_pt | NO_TRADE_TODAY, 주문 없음 |
| S5-T02 | 갭 임계값 하한 | gap=min_gap_pt-ε | 거래 없음 |
| S5-T03 | 갭 임계값 정확 경계 | gap=min_gap_pt | 명세의 inclusive `>=` 기준으로 갭 방향 ATM 옵션 BUY 계획; authoritative gap input이 유효하지 않으면 BLOCKED |
| S5-T04 | 갭 임계값 상한 | gap=min_gap_pt+ε | ATM 갭 방향 옵션 BUY 계획 |
| S5-T05 | 갭 상승 | positive gap, valid CALL ATM ask | CALL BUY, qty/contract identity 검증 |
| S5-T06 | 갭 하락 | negative gap, valid PUT ATM ask | PUT BUY, qty/contract identity 검증 |
| S5-T07 | advance 전 반전 | favorable move < advance_pt, reverse >= hedge_reversal_pt | 반대 옵션 1계약 hedge 계획 |
| S5-T08 | advance 경계 | move=advance_pt±ε | 전/후 상태가 결정론적으로 분기 |
| S5-T09 | advance 후 이익 청산 | move >= advance_pt, peak retracement >= gap×ratio | hedge 신호가 아니라 profit exit |
| S5-T10 | reversal minimum | ratio-derived retracement vs reversal_min_pt | max 조합은 검증 후보로 비교, 확정 전 실행 금지 |
| S5-T11 | 재반전 | hedge open, direction returns | hedge close, original option P&L/fills reconcile |
| S5-T12 | 휩소 첫 회 | whipsaw count=1 | 정책에 따른 관찰/대사; count definition 미확정이면 BLOCKED |
| S5-T13 | 휩소 두 번째 회 | count=whipsaw_limit=2 | 당일 신규 거래 전면 중단 및 청산 계획 |
| S5-T14 | 30분 종료 직전 | elapsed=session_minutes-ε | 세션 종료 action 미실행 |
| S5-T15 | 30분 종료 경계 | elapsed=session_minutes | session_end_action null이면 BLOCKED; 후보별 테스트 |
| S5-T16 | 30분 종료 이후 | elapsed=session_minutes+ε | 신규 진입 금지; 종료 정책 적용 후 잔여 노출 대사 |
| S5-T17 | session_end_action 후보 | close_all / hold / close_hedge_only 각각 독립 시나리오 | 결과 비교만 수행; 어떤 후보도 현재 확정하지 않음 |
| S5-T18 | 손절 비활성 | stop_loss_enabled=false 명시 | 손절 trigger 없음, 나머지 위험 한도 유지 |
| S5-T19 | 손절 설정 누락/null | key absent or null | fail-closed, 신규 주문 없음 |
| S5-T20 | 손절 활성 | enabled=true, valid stop_loss_pt | 설정된 손절 trigger와 close lifecycle |
| S5-T21 | 헤지 부분체결 | 1계약 요청, partial fill/remaining qty | 실제 filled qty만 노출, retry 전 reconciliation |
| S5-T22 | 원 옵션만 체결 | hedge group 중 한 leg만 filled | PARTIALLY_EXPOSED, 추가 신규 진입 차단 |
| S5-T23 | 헤지 주문 거절/미체결 | reject, timeout, no fill | 포지션 flat 확인 전 reset 금지 |
| S5-T24 | 취소 경합 중 체결 | cancel requested then fill arrives | fill 반영, remaining qty reconcile |
| S5-T25 | 호가 공백/오래된 호가 | quote missing/stale/wide | fail-closed, 주문 없음 |
| S5-T26 | 계약/승수/만기 불일치 | identity/multiplier/expiry missing or conflicting | BLOCKED/UNAVAILABLE |
| S5-T27 | config PROVISIONAL/null | status PROVISIONAL or required null | 신규 주문 없음 |
| S5-T28 | S1/S9와 premium·margin 합산 | shared contract/exposure; open lots | duplicate-free account risk; cap breach blocks |
| S5-T29 | 재시작 | open order/partial fill/position exists | reconciliation before any new signal/order |
| S5-T30 | 실제 옵션 P&L/비용 | fills, premium, multiplier, fees/slippage | underlying proxy를 option P&L로 사용하지 않음 |
| S5-T31 | REAL_VTS 검증 분리 | tuning/holdout windows | time separation, provenance, no tuning leakage |
| S5-T32 | 데이터 누락/시각 불일치 | official open, prev close, quote as-of invalid | BLOCKED/UNAVAILABLE, no order |
| S5-T33 | 당일 중단 후 재시도 | whipsaw_limit reached | same-day entry blocked; next session requires clean reconciliation/config |


## S5-U namespace decision amendment (2026-10-12)
- User decision: preserve S1 U-ID values; namespace S5-specific new items as S5-U16 through S5-U20. This appendix controls references in this S5 delta document.
- Documentation-only resolution; no code, test, Git, or Live order action is authorized.

---
## v0.4 — S5 whipsaw event scenarios
1. Opposite hedge trigger but no actual fill → no confirmed hedge cycle/count.
2. Actual hedge fill then underlying returns through the configured reversal boundary → count exactly one event.
3. Duplicate ticks, event IDs or execution reports → no double count.
4. Two confirmed cycles → block same-day new entries and reconcile all S5 positions to flat.
All scenarios NOT_RUN until replayed with source-timestamped REAL_VTS quote/price/order/fill evidence.


---

# Absorbed historical delta: 04_strategy_1_to_9_scenario_test_plan_s9_delta_v0.4.md

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


## 사용자 확인 결과 2026-10-13
네 항목 모두 예로 승인됨. 이는 정책 결정이며 코드 구현/테스트/REAL_VTS/실거래 승인은 아님.

1. S5 30분 종료: 신규 진입 중단, 미체결 취소 완료 확인, 체결 및 포지션 대사. 기존 포지션은 별도 승인된 청산/위험 규칙만 적용한다.
2. S1/S9 D-4: S1 청산 완료 확인 -> S9 목표 수량 재계산 -> 대기 매수 취소 완료 및 체결/포지션 대사 -> 실제 남은 S9 lot 청산. 요청/접수만으로 완료를 간주하지 않는다.
3. No.956/S3: 공식 No.956 베이시스를 임의 변경하지 않는다. 정의/단위/source identity가 충돌하면 S3는 BLOCKED 유지.
4. 버전: S1/S2/S5/S8/S9 파일명 v0.4를 버전 후보로 유지한다. 원본 제목 v0.3은 수정하지 않고 이후 신규 버전에서 파일명/제목을 일치시킨다.

U38/U40/U42의 정책 처리 방침은 해결됨. 런타임 검증은 미완료. D-4/DTE10 실제 날짜는 자료 미확보로 UNSET; S5 whipsaw는 검증형 후보; S6 재시도 정책은 해결됐으나 런타임 미검증; 공통 quote freshness/liquidity 임계값은 UNSET/BLOCKING.

## Addendum 2026-10-13 — confirmed S6 retry policy and calendar boundary vectors (NOT_RUN)
This addendum supersedes earlier S6 cases that implied a retry after a zero-fill timeout. No scenario was executed.

| ID | Strategy | Scenario | Expected behavior | Evidence required | Status |
|---|---|---|---|---|---|
| TP-S6-V04-E01 | S6 | 10-minute timer expires; no fill; CALL and PUT both reach confirmed-cancel terminal state | Reconcile fills/positions, end entry for the day, no retry | order/fill/cancel timestamps, actual position snapshot, daily-entry fence | NOT_RUN |
| TP-S6-V04-E02 | S6 | Both cancel requests pending; no fill yet | Do not assume cancelled; no new candidate order until terminal state and fill reconciliation | cancel ACK/state + cumulative fills | NOT_RUN |
| TP-S6-V04-E03 | S6 | Late fill arrives while either cancel is pending | Apply actual fill; this is not a zero-fill condition; reconcile actual leg and do not retry blindly | execution ID, fill time, order state, position snapshot | NOT_RUN |
| TP-S6-V04-E04 | S6 | CALL filled, PUT not filled; opposite leg cancelled after timer | Preserve actual CALL lot and apply existing one-leg policy; no fabricated pair and no blind same-day retry | per-leg fill/position and policy state | NOT_RUN |
| TP-S6-V04-R01 | S6 | Restart after both orders cancelled with zero fills | Persisted daily no-retry fence blocks re-entry after reconciliation | persisted state/config hash and broker position query | NOT_RUN |
| CAL-D4-01 | S1/S9 | D-4 at 10:59:59 KST | Follow approved S1-first D-4 sequence only if calendar is authoritative | exact expiry YYYYMMDD and KRX calendar hash | NOT_RUN |
| CAL-D4-02 | S1/S9 | D-4 at 11:00:00 KST | If boundary inclusion remains unset, fail closed | policy/config and event timestamp | NOT_RUN / UNSET |
| CAL-D4-03 | S1/S9 | D-4 at 11:00:01 KST | No new entry; unfinished exits remain reconciliation-required | order/fill/position state | NOT_RUN |
| CAL-DTE10-01 | S8 | Exact trading DTE=11 | DTE10 entry gate not yet reached; other gates still apply | expiry master + calendar | NOT_RUN |
| CAL-DTE10-02 | S8 | Exact trading DTE=10 | Entry may be considered only if exact expiry/calendar and all risk/quote gates pass | expiry master + calendar + config hash | NOT_RUN |
| CAL-DTE10-03 | S8 | Exact trading DTE=9 | Block new S8 entry | expiry master + calendar | NOT_RUN |
| CAL-HOL-01 | S1/S9/S8 | Expiry near an exchange holiday | Count only official KRX trading days, not weekdays alone | official calendar notice and option master | NOT_RUN |
| CAL-HOL-02 | S1/S9/S8 | Expiry after a multi-day holiday | Recalculate D-4/DTE10 from the actual expiry and trading-day set | calendar hash and boundary trace | NOT_RUN |
| DATA-Q-01 | All | Missing source timestamp | Quote freshness UNSET/BLOCKING; no entry | raw source frame and canonical mapping | NOT_RUN |
| DATA-Q-02 | All | Source/receive timestamp mismatch or excessive gap | Block pending validated limits | timestamp series and approved limit | NOT_RUN |
| DATA-Q-03 | All | 5th/6th strike lacks quote or depth evidence | No arbitrary substitute strike; block candidate | option master, quote, depth, volume distribution | NOT_RUN |

## Retry-window comparison (policy-level)

| Strategy | Retry/entry window | Policy status | Important distinction |
|---|---|---|---|
| S6 | Open through 11:00 KST; after 10-minute zero-fill and both orders confirmed cancelled, no retry that day | User-confirmed; boundary/runtime unverified | Do not retry by selecting another strike or after restart |
| S7 | Each Monday/Thursday set can retry until 15:00 KST while eligible | Existing confirmed intent; calendar/runtime unverified | Separate weekly groups; 15:00 cutoff |
| S8 | Three trading-day window after monthly start | Existing confirmed intent; calendar/runtime unverified | Trading days, not calendar days; DTE10 gate is separate |
| S2 | Re-order only remaining target quantity after cancel confirmation and fill/position reconciliation | Existing intent; retry counts/price bounds unset | Not a fixed multi-day window; missing bounds block |

The D-4 counting convention is user-approved (2026-10-13), but calendar candidates remain non-executable until authoritative current KRX calendar and exact expiry master evidence are attached. Months without exact expiry YYYYMMDD remain UNSET/BLOCKED.

## S6/S7/S8 retry policy — shared OMS, distinct strategy rules

| Strategy | Retry rule | Boundary / state gate | Validation |
|---|---|---|---|
| S6 daily insurance | No same-day retry after 10 minutes with zero fills, once both CALL/PUT orders are confirmed cancelled and fills/positions reconciled | Persist a no-retry fence; late/partial fills or unknown cancel state require reconciliation, not another attempt | Intent confirmed; runtime/replay NOT_RUN |
| S7 weekly insurance | Monday/Thursday sets may retry while eligible through 15:00 KST | Each weekly set has separate group/expiry/order state; no new entry after cutoff | Boundary and two-set replay NOT_RUN |
| S8 monthly strangle | Retry within three trading days after monthly start; third-day cutoff 15:00 KST | Entry additionally requires exact expiry/calendar and DTE >= 10 | Calendar and holiday-crossing replay NOT_RUN |

The common contract is terminal-order-state reconciliation, not a shared retry count or window. CANCEL_REQUESTED is not CANCEL_CONFIRMED; do not resubmit while cancel/fill/position state is unknown.

## S6 no-retry policy — explicit verification vectors

| ID | Scenario | Expected result | Status |
|---|---|---|---|
| S6-NR-01 | 10 minutes elapsed, zero fills, CALL and PUT cancel both confirmed, positions reconciled | Mark daily attempt exhausted; no same-day retry | NOT_RUN |
| S6-NR-02 | Cancel requested but one cancel is not confirmed / order state unknown | No retry; enter reconciliation-required state | NOT_RUN |
| S6-NR-03 | Late/partial fill arrives during or after cancel race | Reconcile actual filled quantity and positions; no duplicate replacement order | NOT_RUN |
| S6-NR-04 | Process restart after no-retry condition | Persisted no-retry fence survives restart and prevents same-day retry | NOT_RUN |
| S6-NR-05 | Compare S6, S7 and S8 start windows/cutoffs | S6 no retry under defined condition; S7 through 15:00 on Mon/Thu sets; S8 three trading days, day 3 through 15:00 | NOT_RUN |

These are scenario definitions only. No tests or REAL_VTS replay were run in this document-only task.

## Calendar evidence update (2026-10-13, v2 supplemental)

- Source: `docs/strategy_specifications/trading_day_boundary_table_v2.md`.
- The scenario IDs `CAL-D4-01..03`, `CAL-DTE10-01..03`, and `CAL-HOL-01..02` remain `NOT_RUN`.
- Their actual expiry/D-4/DTE10 vectors remain `UNSET/BLOCKED`: the checked KRX official holiday lookup page did not provide an archived date-range result, and the historical `20260919` KRX master snapshot lacks exact expiry rows for 2027-04, 2027-05, 2027-07, 2027-08, and 2027-10.
- No weekday-only dates are promoted to actual trading sessions. See v2 for the source URLs, source-derived exact-expiry candidates, the weekly 2026-09-23 discrepancy, and the single D-4 inclusion question.


## Calendar evidence correction (2026-10-13, KRX cache inspected)

The previous supplemental note that described all official holiday evidence as unavailable was too broad. Project files `data/calendar/krx/2026.json` and `data/calendar/krx/2027.json` exist and contain KRX source URL, `fetched_at`, year, and 17/16 holiday dates respectively. No.1045 records 2026/2027/2028 source counts as 17/16/17. `trading_day_boundary_table_v2.md` now lists the month-specific holiday dates and candidate vectors derived by excluding weekends and cached KRX holidays. The scenario statuses remain `NOT_RUN`; the dates are candidates only, the D-4 convention was approved by the user on 2026-10-13, and five expiry months remain blocked because the historical exact-expiry master lacks those contracts.
