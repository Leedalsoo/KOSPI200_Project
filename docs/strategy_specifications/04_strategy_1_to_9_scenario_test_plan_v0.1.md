# Strategy 1~9 정상·경계·예외·복구 시나리오 테스트 계획 v0.1

- 상태: **계획 초안 / 미실행 / 미승인**
- 기준 브랜치/HEAD: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- 적용 범위: Strategy 1~9 상세 명세 v0.2 및 통합설계표 v0.3
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