# Strategy 1~9 정상·경계·예외·복구 시나리오 테스트 계획 v0.3

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
| TP-S1-U01 | Rise/fall short accumulation | Valid approved config/REAL_VTS; user-confirmed directional rule available; config and risk gates must be valid | Only policy-defined shorts enter; actual+pending worst-case short exposure never exceeds 10; hedge buys excluded from count but included in account risk | option identity, orders/fills, exposure snapshots, config hash | NOT_RUN |
| TP-S1-U02 | Retracement approaches nearest short strike | Actual short lots and non-null trigger distance selected only after REAL_VTS tuning/approval | 1:1 option hedge candidate for linked residual qty; no Futures hedge or duplicate hedge | short lot provenance, distance, target qty, candidate, risk preflight | NOT_RUN |
| TP-S1-U03 | Hedge quote gap then candidate fallback | First quote unavailable; alternative exists; 30-minute timer | LIMIT reservation for one candidate; after 30 minutes cancel; descend only after cancel terminal, leaves=0 and reconciliation | timestamps, order IDs, cancel ack, candidate quotes, fills | NOT_RUN |
| TP-S1-U04 | Fill during cancellation | Hedge order cancel-pending; delayed execution arrives | Do not submit next candidate; apply late fill; recompute hedge need and reconcile | event sequence, cancel state, cumulative fill/leaves, lineage | NOT_RUN |
| TP-S1-U05 | Combined short cap reaches 10 | CALL+PUT actual shorts plus pending worst-case exposure reaches 10 | Stop new shorts; preserve positions; hedge buys excluded from short count but subject to account risk | open lots, pending leaves, cap calc, risk decision | NOT_RUN |
| TP-S1-U06 | Hedge release at ±5.0pt | Linked hedge open; authoritative ATM crosses threshold away from short strike | Close actual remaining linked hedge qty; no reset until flat; short remains separate | price/strike distance, close plan, fills, open lots | NOT_RUN |
| TP-S1-U07 | Full close at DTE 4 | Exact expiry and approved DTE semantics; short, hedge and base CALL/PUT lots exist | Group terminal plan covers every remaining S1 lot; no new entry; lifecycle completes only after flat | expiry source, DTE calc, group/leg plan, fills, fees, flat snapshot | NOT_RUN |
| TP-S1-U08 | Flat market / no additional movement | Active positions, no approved short trigger crossed | No special trade; preserve positions and lifecycle | input snapshot, no-signal reason, unchanged lots/state | NOT_RUN |
| TP-S1-U09 | Partial fill | Any base/short/hedge/close leg partial or rejected | Independent per-leg state; recalculate actual exposure; no all-or-none assumption; block unsafe continuation until reconciled | per-leg order/fill/leaves, group state, position snapshot | NOT_RUN |
| TP-S1-U10 | Monthly boundary | DTE4 close complete; next monthly cycle not started | Preserve flat-confirmed old group; wait idle about 3–4 days after DTE4 flat until the next monthly cycle starts; do not re-enter early; no blind re-entry | calendar, flat snapshot, state transitions, config version | NOT_RUN |

| TP-S1-U11 | Step-anchor reference behavior | REAL_VTS tuning input with multiple threshold crossings; target short accumulation otherwise specified | Current code has no target step-accumulation logic; this case remains BLOCKED until U28 (last-short anchor vs per-step anchor) is resolved. Do not infer behavior from current fence logic | ATM path, short events, anchor timestamps, config version, user decision | NOT_RUN / BLOCKED |

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
10. The step anchor refresh policy is unresolved (U28); no test may assume last-short or per-step anchor.
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
