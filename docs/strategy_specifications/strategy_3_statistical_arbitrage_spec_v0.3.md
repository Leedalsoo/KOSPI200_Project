# Strategy 3 Statistical Arbitrage 상세 명세 v0.3
- 상태: **초안 v0.3 / 판단요소별 구조 보강 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- v0.2 변경: F01~F29 판단요소별 현행 사실/목표 규칙/미결정 상태, 상태 전이, 수용 게이트 추가
- 현 코드: core/strategy/track3_statistical_arbitrage.py v1.0
- 연결: Track3 runtime input, common Analytics, execution_cost estimator, Track3PlanAdapter, Futures identity source, MultiLegBridge.

## 1. 목적 — 미확정
현재 구현은 spread z-score mean reversion, regime별 threshold/size/cost gate를 시사한다. 실제 spread 구성, 자산 조합, 양쪽 leg의 경제적 역할은 확정되지 않았다.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- 기본 z-entry=2.0, z-exit=0.2, stop=3.5, max holding=300 evaluate calls, min expected net profit=15,000, base round-trip cost=10,000.
- HIGH_VOLATILITY: threshold=max(2.2, 2.0*vol_ratio*1.2), min profit 1.5x, qty=1.
- EXTREME_MOVE: threshold=999, entry blocked.
- GAP: threshold=max(2.0, 2.0*1.1), min profit 1.3x, qty=1; market_stable와 spread_normalizing 둘 다 필요.
- Other regime: threshold=max(1.5, 2.0*vol_ratio); abs(z)>=2.5 and allow_size_up이면 qty=2.
- expected gross=abs(z)*spread_std*0.8*contract_multiplier*qty, net=gross-cost. 이전 exit z와 차이가 0.8 미만이면 재진입 차단.
- _signal은 Futures proposal을 만들고 resolver/Track3PlanAdapter가 execution plan을 구성한다.
- position/group/leg state는 실제 fill 확인 전에 진입 평가에서 설정된다. Track3MultiLegExecutionPlanAdapter는 hedge_identity == identity를 강제하고 동일 instrument identity에 같은 qty의 반대 side legs를 만든다. 따라서 현재 계획은 순노출을 상쇄할 수 있으며, spread 차익거래라는 전략 목적과 모순될 수 있다. 신규 명세에서 두 leg가 다른 상품/identity인지 또는 단일 Futures leg인지 확정해야 한다.
- evaluate_input에서 _exit_pending을 확인할 때 regime이 아직 할당되지 않아 pending 경로에서 UnboundLocalError가 날 수 있다.
- cutoff, trailing, z-stop, timeout, convergence+profitability 순서로 exit signal을 생성한다. trailing high-watermark는 portfolio current P&L + options P&L, premium-spent ratio를 사용한다.
- close resolver는 open lots를 기준으로 만들고 callback은 group_complete와 position_flat 후 상태를 초기화한다.

## 3. 목표 lifecycle
DATA_WARMUP → REGIME_VALIDATION → COST_AND_EDGE_CHECK → ENTRY_PLANNED → ENTRY_WORKING → ACTIVE/PARTIAL → EXIT_PENDING → FLAT_CONFIRMED → CLOSED. 미정 spread identity, 같은 계약의 반대 leg, unavailable cost/multiplier는 fail-closed한다.

## 4. 필수 데이터
Spread 구성식과 timestamp alignment; z-score window/mean/std/warmup/outlier; regime enum/source; gap/stability definition; futures symbol-to-identity; multiplier/cost/fees/slippage units; portfolio P&L attribution; run/group/leg provenance; authoritative fills/positions.

## 5. 미결정 항목
1. 실제 spread가 구성되는 instruments와 가격.
2. SHORT_SPREAD/LONG_SPREAD의 정확한 order sides와 leg quantities.
3. HEDGE_LEG의 목적 및 동일 Futures identity를 허용할지.
4. 15,000 profit threshold, 30,000 trailing activation 및 -5,000 exit tolerance의 근거.
5. 300 evaluations를 elapsed time으로 볼지 call count로 유지할지.
6. group_integrity 갱신 주체, partial fill/restart/roll behavior.
7. close cost, current P&L, options P&L, premium_spent의 authoritative source.
8. cutoff/overnight/contract expiry와 account-wide risk.

## 6. 검증 시나리오
z threshold/0.2/3.5 경계, regime별 edge; missing multiplier/cost; spread leg same-identity/opposite-side; _exit_pending path; gap stable/normalizing combinations; entry/exit partial fill; duplicate close; 300th call/cutoff; zero premium; stale analytics; restart/reconciliation.

## 7. 추적/판정
관련 코드: track3_statistical_arbitrage.py, core/analytics/execution_cost.py, resolve_track3/Track3PlanAdapter, Futures identity source, MultiLegBridge.
**BLOCKED** — pending 경로 오류 후보, spread 정의와 Futures leg identity/역할 미확정.

---

## 8. 판단요소별 상세 정의 — v0.2 핵심

| ID | 판단요소 | 현재 코드에서 확인된 사실 | 신규 명세의 목표 규칙 | 결정 상태 / 차단 사유 |
|---|---|---|---|---|
| F01 | 전략 목적·경제적 역할 | spread z-score mean reversion, regime별 진입/청산/edge gate. 실제 tradable spread 정의 불명확. | Tradable spread, alpha source, leg payoff, hedge purpose, after-cost edge를 수식으로 정의한다. | **미결정** — 경제적 spread 정의 필요 |
| F02 | 적용 시장·상품 | Signal은 FUTURES proposal; multi-leg adapter는 두 Futures legs 구성. | Authoritative Futures master identity로 universe 확정, 동일 identity 상쇄 leg 금지. | **BLOCKED** — 동일 identity/반대 side 가능 |
| F03 | 운용 주기·활성화 | date_str 변경 시 일부 상태/cooldown reset; cutoff는 MarketSessionPolicy 기준. | 공식 session/calendar, trading date, overnight, expiry/rollover와 reset 분리. | **미결정** |
| F04 | 기준가격·시계열 | Injected Track3RuntimeInputSource가 spread_history/as_of 제공; timestamp equality 검사. | Spread leg identity, price source, time alignment, unit, gaps/duplicates/freshness 보존. | **부분 확인** — spread construction 미정 |
| F05 | 진입 신호·조건 | z-entry=2.0; regime별 threshold/min-profit/qty; expected net profit gate. | Spread/z window, mean/std, thresholds, regime gate, direction mapping 승인. | **미결정** |
| F06 | 추가 진입·재구성 | active_position None일 때 entry; state/group legs는 fill 전 설정. Scale-in policy 없음. | Pending/active group 중 중복 진입 금지; 재진입은 close confirmation/cooldown 후. | **BLOCKED** — pre-fill state |
| F07 | 대기·진입 취소 | proposal→resolver→MultiLegExecutionPlan; full entry cancel/partial lifecycle not in strategy state. | Per-leg ACK/working/partial/cancel/reject/timeout/race and idempotent reconciliation. | **미검증** |
| F08 | 계약 선택·identity | Resolver maps symbol to FuturesInstrumentIdentity; adapter enforces hedge_identity == identity. | Each spread leg identity separately resolved; product/expiry/multiplier/quote verified. | **BLOCKED** — current same identity |
| F09 | spread unit/multiplier | gross = abs(z)*spread_std*0.8*multiplier*qty; positive multiplier required. | Spread units/std/multiplier dimensionally consistent and tested. | **미결정** |
| F10 | 변동성/regime | HIGH_VOLATILITY/GAP/EXTREME_MOVE have special rules; vol_ratio adjusts threshold. | Regime source/enum, windows/units, boundary and stale behavior fixed. | **미결정** |
| F11 | market stability/gap | GAP needs market_stable and spread_normalizing; EXTREME_MOVE blocks entry. | Gap/stability/normalization formulas and timestamp windows defined. | **미결정** |
| F12 | size/capital/cost | Base qty=1; qty=2 if abs(z)>=2.5 and allow_size_up; min profit 15,000, base cost 10,000. | Editable total capital, premium cap, strategy/account max-loss, margin, fees, slippage, qty cap. | **수치 미확정** |
| F13 | order/pricing/reprice | Proposal requested_price absent; strategy class does not define per-leg pricing policy. | Per-leg price/tick, limit collar, reprice/timeout/cancel/replace and liquidity rules. | **미결정** |
| F14 | group preflight | Resolver creates plan; MultiLegRisk can approve each leg, but identical opposite legs may pass as orders. | Group preflight validates identity, non-cancellation economics, quote/cost/margin/max-loss before routing. | **BLOCKED** |
| F15 | partial/reject/unknown | Entry state set before fill; callback resets only after close group_complete and position_flat. | State driven by authoritative per-leg fills/lots; unknown/partial/cancel race reconciled. | **BLOCKED** |
| F16 | hedge/rebalance/leg roles | Adapter adds opposite-side same-qty HEDGE at same identity. | Alpha/spread legs and genuine hedge roles separated; hedge needs measurable risk reduction. | **BLOCKED** |
| F17 | holdings/exposure | position_group_legs stores labels and qty, not authoritative per-leg identities/fills. | Actual leg identities/sides/fills/qty and net exposure derived from position read model. | **미검증** |
| F18 | stop/risk exit | Directional z-stop=3.5; no strategy account max-loss trigger shown. | Hard max-loss/stress-loss, z-stop priority and terminal risk handling defined. | **미결정** |
| F19 | profit/trailing | high P&L watermark uses portfolio current P&L + options P&L; activates >30,000, retention tiers 85/88/90%. | Strategy-attributed actual P&L/fees/marks and deterministic watermark/tier behavior. | **미결정** |
| F20 | time exit/expiry | max_holding_ticks=300 evaluation calls, not elapsed time; cutoff signal qty=1 but resolver uses open lots. | Decide elapsed-time vs call count, exact expiry, cutoff, rollover and flat-confirmed reset. | **미결정** |
| F21 | close scope/qty/side | Close resolver uses open lots; signal qty may differ from actual position. | Authoritative lots determine side/remaining qty; grouped close and all-flat confirmation. | common principle confirmed; strategy path **미검증** |
| F22 | P&L/fees/slippage | Expected edge formula is not actual execution P&L; cost/current P&L/options P&L/premium are analytics inputs. | Separate expected vs realized/unrealized P&L, actual fills, fees, slippage, multiplier and marks. | **미검증** |
| F23 | trigger priority | Cutoff, trailing, z-stop, timeout, convergence checks are ordered; _exit_pending branch references regime before assignment. | Deterministic priority; pending path must not reference uninitialized values. | **BLOCKED** — UnboundLocalError candidate |
| F24 | lifecycle/provenance | Strategy group_id uses date/sequence; resolver group_id uses canonical signal_id; close callback checks group_complete/flat. | Stable group identity and run/evaluation/leg/order/execution provenance. | **미검증** |
| F25 | restart/duplicate/timeout | reset clears state; durable restoration/idempotent entry reconciliation not shown. | Restore active group/orders/fills/lots/cooldown/watermark/config hash before new entry. | **미결정** |
| F26 | cross-strategy/account risk | Portfolio P&L inputs exist, but aggregate exposure/concentration not proven in this path. | Aggregate all-strategy margin/shared identity/correlated stress loss without implicit netting. | **미결정** |
| F27 | data error/unavailable | Provider blocks missing source/timestamp mismatch/short history/invalid cost or multiplier; absent account P&L may be converted to zero in payload. | Missing authoritative P&L is UNAVAILABLE, not zero; stale/mismatch fail-closed. | **BLOCKED** |
| F28 | editable limits/config | Strategy constants exist; editable account capital/premium/max-loss runtime enforcement not proven. | Versioned editable capital/premium/max-loss/account risk settings, effective time, hash and routing gate. | **수치·강제경로 미확정** |
| F29 | tests/acceptance | Tests cover regime input fail-closed and Futures proposal side only. | Test identity cancellation, units, regimes, pending branch, partial fills, actual P&L, expiry, restart and risk limits. | **미완료** |

## 9. Strategy 3 목표 상태 전이표 — 구현 전 계약

| 현재 상태 | 이벤트/조건 | 다음 상태 | 필수 가드·행동 | 실패 처리 |
|---|---|---|---|---|
| DISABLED | ON/config valid | WAITING_FOR_SESSION | entry permission/config version | unknown config → BLOCKED |
| WAITING_FOR_SESSION | session/source available | DATA_WARMUP | timestamps and authoritative source | missing source → UNAVAILABLE |
| DATA_WARMUP | sufficient spread history | REGIME_VALIDATION | spread identity/unit consistency | mismatch → BLOCKED |
| REGIME_VALIDATION | regime permits entry | COST_AND_EDGE_CHECK | thresholds/quantity/net edge | extreme regime → ENTRY_BLOCK |
| COST_AND_EDGE_CHECK | distinct leg identities and risk pass | ENTRY_PLANNED | reject same-identity opposite legs | invalid spread → BLOCKED |
| ENTRY_PLANNED | idempotent plan persisted | ENTRY_WORKING | per-leg order state | uncertain route → RECONCILIATION_REQUIRED |
| ENTRY_WORKING | all required legs filled/reconciled | ACTIVE | actual lots match intended spread | partial/reject → PARTIALLY_EXPOSED |
| ACTIVE | stop/trailing/timeout/convergence/cutoff | EXIT_PENDING | deterministic priority, close actual lots | missing close leg → BLOCKED |
| EXIT_PENDING | fills pending | EXIT_PENDING | remaining qty/cancel race/no duplicate close | unknown → RECONCILIATION_REQUIRED |
| EXIT_PENDING | all legs confirmed flat | FLAT_CONFIRMED | executions and positions match | mismatch → RECONCILIATION_REQUIRED |
| FLAT_CONFIRMED | P&L/cost finalized | CLOSED | persist exit z/cooldown/provenance | mismatch → BLOCKED |
| any active state | restart/source/API failure | RECONCILIATION_REQUIRED | restore group/orders/fills/lots | cannot reconcile → BLOCKED |
| RECONCILIATION_REQUIRED | authoritative state agrees | prior valid state or FLAT_CONFIRMED | no blind retry or silent reset | uncertainty → BLOCKED |

## 10. 명세-코드-테스트 추적 및 수용 게이트

| 추적 ID | 관련 경로/기준 | 검증 산출물 | 현재 판정 |
|---|---|---|---|
| S3-F01~F06, F09~F12, F18~F20, F23 | core/strategy/track3_statistical_arbitrage.py, core/analytics/track3.py | spread thesis, units, thresholds, priority tests | BLOCKED |
| S3-F04, F10~F12, F17, F22, F27 | track3_runtime_input_provider.py, infrastructure/kis/track3_runtime_input_source.py, track3_analytics_provider.py | source/time/unit/fee/P&L provenance tests | INCOMPLETE |
| S3-F07~F08, F13~F16, F21, F24~F25 | track3_multi_leg_execution_plan_adapter.py, track3_futures_execution_plan_adapter.py, resolve_track3, MultiLegBridge | non-cancelling identities, fills and recovery | BLOCKED |
| S3-F26, F28 | core/risk, account/margin/fee providers and risk config | aggregate account risk/config tests | BLOCKED |
| S3-F29 | tests/strategy/test_strategy3.py and Virtual E2E | F01~F29-to-test map | INCOMPLETE |

Acceptance gates:
- A01: tradable spread legs and payoff approved.
- A02: same-identity opposite legs rejected unless a distinct economic role is proven.
- A03: z/std/vol/regime/cost calculations are dimensionally consistent and source-backed.
- A04: pending path has no uninitialized variable; exit priority is deterministic.
- A05: per-leg partial/reject/cancel-race/restart reconciled.
- A06: actual P&L/fees/multiplier and account aggregate risk authoritative.
- A07: editable total capital/premium/max-loss settings versioned and enforced.
- A08: F01~F29 map to tests/evidence; unresolved cases BLOCKED.
- A09: validation and explicit user approval remain separate.

## 11. 미결정·승인 필요 항목

| ID | 결정 필요 사항 | 필요한 근거 | 현재 영향 |
|---|---|---|---|
| D01 | Tradable spread instruments/legs | market source, contract master, payoff analysis | implementation blocked |
| D02 | Hedge leg role/ratio | exposure reduction and stress evidence | same identity opposite side not accepted as target |
| D03 | z/std windows and units | history, timestamp and statistical tests | thresholds unapproved |
| D04 | regime/size-up/min-profit values | regime scenarios, costs and multiplier sensitivity | sizing/edge unapproved |
| D05 | trailing/max-loss P&L basis | authoritative trade P&L and options attribution | exit policy unapproved |
| D06 | 300 calls vs elapsed time, cutoff/expiry | session calendar and expiry rules | lifecycle unresolved |
| D07 | partial fills/group integrity/recovery | execution reports and position read model | safe execution blocked |
| D08 | editable account/strategy risk numbers | capital, quotes, fees, margin, stress loss | values require separate approval |
| D09 | zero fallback vs unavailable | authoritative account/P&L source contracts | fail-closed semantics need resolution |
| D10 | cooldown/last_exit_z/group identity persistence | lifecycle/idempotency design | duplicate/re-entry risk |

## 12. v0.2 판정

- 상태: **초안 / 미검증 / 미승인**.
- 판단요소: **F01~F29 29/29 작성**.
- 주요 차단: same-identity opposite legs, pending branch regime uninitialized reference, pre-fill active state, actual P&L/expiry/account risk unresolved.
- Document structure only; no strategy scenario/E2E tests run.
- Code changes/commit/push/KIS Live orders: none.
- Next: Strategy 4 same F01~F29 depth.

## 13. v0.3 사용자 지시 반영 — spread 정의 제안 (2026-10-13)

- 상태: **초안 / 검증 전 / 미승인 / 구현 기준 사용 금지**.
- 사용자 지시: 시장 표준 기본안인 **KOSPI200 Futures 근월물−차월물 캘린더 스프레드**를 v0.3 초안의 목표 spread로 채택한다.
- `No.956` Decision Log는 **삭제하거나 직접 수정하지 않았다**. 해당 항목은 Futures−Index basis 정의를 확정한 기존 기록으로 보존한다. 이 v0.3 문서에서는 No.956의 폐기 또는 범위 변경이 필요한지 **제안만** 기록한다. 결정로그 상태 변경은 하지 않는다.
- 폐기/대체 제안: No.956의 Futures−Index basis 정의는 캘린더 스프레드 기반 Strategy 3과 의미가 다르므로, 사용자가 추후 명시적으로 승인할 경우에만 `폐기됨` 상태와 사유/대체 기준을 별도 기록한다. 현재 상태는 미결/승인 대기이며 No.956은 유효한 과거 결정으로 남는다.

### 13.1 목표 spread 및 실행 가능성

`spread_t = near_month_futures_price_t - far_month_futures_price_t`로 정의한다. 두 가격은 같은 시점의 authoritative KOSPI200 Futures quote/observation이어야 한다. 각 leg는 서로 다른 만기·instrument identity여야 하고, multiplier 및 contract specification이 authoritative Futures Master로 확인되어야 한다. 기본 목표 포지션은 spread가 과거 평균 대비 저평가되었을 때 near-month BUY + far-month SELL, 고평가되었을 때 near-month SELL + far-month BUY이다. 이 방향 규칙은 가격차 정의와 z-score 부호에 따라 재검증해야 하며, 수량은 각 계약 승수/가치가 동등해지는 hedge ratio 검증 전까지 1:1을 **잠정 기본안**으로만 둔다.

- 동일 identity의 동일 수량 반대 주문은 유효한 spread가 아니며 preflight에서 차단한다.
- Futures-Index basis는 별도 historical decision No.956의 정의다. v0.3 캘린더 spread에 섞거나 자동 fallback으로 사용하지 않는다.
- near/far quotes, timestamp alignment, contract expiry, multiplier, trading calendar, roll/expiry mapping, costs/slippage, spread history coverage 중 하나라도 확인되지 않으면 entry `BLOCKED/UNAVAILABLE`.
- `spread_history`는 실제로 정의된 near-minus-far spread observations만 포함한다. 현재 analytics의 `_z_score`/`_spread_std`는 주입된 history를 계산하므로, 그 자체로 instrument construction을 보증하지 않는다.

### 13.2 Provisional parameters — not approved

```yaml
strategy3:
  status: PROVISIONAL
  enabled: false
  capital_gate_min: null
  spread_type: calendar_near_far
  spread_formula: near_month_futures_minus_far_month_futures
  z_entry: 2.0
  z_exit: 0.2
  z_stop: 3.5
  max_hold_minutes: null
  min_expected_net_profit: null
  reentry_z_gap: 0.8
  force_close_time: "15:10"
  no_new_entry_dte: null
  qty_base: 1
  size_up_allowed: false
```

`null` or unverified values fail closed. These values are proposals, not market-validated parameters. Config version/hash and effective time must be recorded per run and linked to every group/leg/order/execution.

### 13.3 Strategy lifecycle and order-state contract

| State | Entry condition / event | Required invariant | Failure behavior |
|---|---|---|---|
| DISABLED | Default / capital gate unavailable | no new entry route | BLOCKED |
| DATA_WARMUP | session and source available | sufficient synchronized near/far observations | UNAVAILABLE/BLOCKED |
| SPREAD_VALIDATION | identity/expiry/multiplier verified | distinct near/far identities and consistent units | BLOCKED |
| REGIME_AND_EDGE_CHECK | z/regime/cost inputs valid | after-cost expected edge exceeds configured minimum | ENTRY_BLOCK |
| ENTRY_PLANNED | group persisted idempotently | leg sides/qty/prices/risk preflight pass | BLOCKED |
| ENTRY_WORKING | per-leg orders accepted/working | track ACK, cumulative fill, leaves, cancel/reject/timeout independently | RECONCILIATION_REQUIRED |
| PARTIALLY_EXPOSED | one leg or partial quantity filled | actual fills and residual risk determine actions; no assumed pair completion | maintain/repair policy unresolved; fail closed |
| ACTIVE | both legs and positions reconciled | actual identities, quantities and sides match spread plan | BLOCKED/reconcile |
| EXIT_PENDING | stop/convergence/timeout/cutoff | close only actual remaining lots; no duplicate close | RECONCILIATION_REQUIRED |
| FLAT_CONFIRMED | all orders terminal and actual positions flat | fills and position snapshot agree | remain pending if mismatch |
| CLOSED | realized P&L/cost reconciled | preserve config and provenance | BLOCKED if accounting incomplete |
| RECONCILIATION_REQUIRED | restart/API/cancel race/unknown status | reconcile broker orders, fills and positions before any retry/reset | no blind retry; BLOCKED |

### 13.4 Current-code difference register

| ID | Code observation (not a new requirement) | v0.3 target / classification |
|---|---|---|
| CD01 | `core/analytics/track3.py::_z_score` and `_spread_std` compute from supplied `spread_history`; `application/composition/track3_analytics_provider.py` forwards `data.spread_history`. Instrument pair is not defined in these functions. | **MISMATCH / BLOCKED** until near/far construction is authoritative. |
| CD02 | `Track3MultiLegExecutionPlanAdapter` has been reported to enforce `hedge_identity == identity` and build equal-quantity opposite-side legs. | **MISMATCH**: cannot represent near/far calendar spread; verify full adapter path before implementation. |
| CD03 | `_exit_pending` branch appears before `regime` is assigned in `evaluate_input`; potential `UnboundLocalError`. | **MISMATCH / BLOCKED**; document only, do not fix in this document-only task. |
| CD04 | Entry/group state is updated during evaluation before authoritative fills are confirmed. | **MISMATCH**; state must be fill/position-driven. |
| CD05 | Trailing P&L references portfolio P&L plus options P&L and premium spent. | **MISMATCH** for futures calendar spread; use strategy-attributed realized/unrealized futures P&L, costs and verified marks. |
| CD06 | Close cutoff is described in code as 15:15. | **MISMATCH** with provisional 15:10 target; session/calendar validation required. |
| CD07 | Holding timeout is 300 evaluation calls, not elapsed time. | **MISMATCH / UNRESOLVED**; max_hold_minutes remains null. |
| CD08 | 15,000 expected-profit threshold, 10,000 base cost, 30,000 trailing activation and -5,000 tolerance are present as legacy values. | **LEGACY / NOT APPROVED**; do not promote without cost, multiplier and REAL_VTS validation. |
| CD09 | Entry/exit per-leg partial fill, cancel race, late fill and restart recovery are not demonstrated by current strategy tests. | **NOT IMPLEMENTED / NOT MAPPED** until evidence exists. |
| CD10 | Missing authoritative multiplier/cost/quote must not be replaced with guessed defaults. | **REQUIRED FAIL-CLOSED GATE**. |

### 13.5 Complete v0.2 F01–F29 disposition

All F01–F29 rows in §8 are carried forward; this classification supplements rather than deletes their original text.

| ID range | v0.3 disposition |
|---|---|
| F01–F05 | Spread thesis is now proposed as near/far calendar spread; z/statistics, timestamp, direction and units remain to verify. |
| F06–F08 | Fill-driven state and distinct near/far identities required; current same-identity adapter is mismatch. |
| F09–F14 | Multiplier/units, regime, quote/price rules, group preflight and after-cost edge remain unverified/config-gated. |
| F15–F17 | Partial fills, leg role, actual holdings/exposure remain blocked pending per-leg authoritative state. |
| F18–F23 | Stop/max-loss, P&L/trailing, time/expiry, close sizing and trigger priority remain provisional; pending-regime defect is a code issue, not fixed here. |
| F24–F28 | Provenance, restart, account risk and versioned config enforcement remain blocked. |
| F29 | Existing tests are not a complete F01–F29 acceptance map; scenarios below are plans only. |

### 13.6 v0.2 open items and gates disposition

The v0.2 open items D01–D10 are all retained and classified below; none is considered implementation-approved:

| v0.2 ID | Disposition in v0.3 | Status |
|---|---|---|
| D01 spread instrument/legs | Proposed near/far calendar spread; actual Futures master and executable quotes must verify | Proposed; validation required |
| D02 hedge role/ratio | Treat the two calendar legs as spread legs, not a separate same-identity hedge; hedge ratio unresolved pending multiplier/exposure analysis | BLOCKED |
| D03 z/std windows and units | Config/data contract and REAL_VTS calibration required | UNRESOLVED |
| D04 regime/size-up/min-profit | Values stay provisional; size-up disabled | UNRESOLVED |
| D05 trailing/max-loss basis | Strategy-attributed Futures P&L and authoritative risk policy required | UNRESOLVED |
| D06 timeout/cutoff/expiry | 15:10 is proposed; elapsed-time timeout and DTE remain null | UNRESOLVED |
| D07 partial fills/group recovery | per-leg reconciliation and restart scenarios required | BLOCKED |
| D08 capital/strategy risk | `capital_gate_min: null` blocks entry; user confirmation required before activation | BLOCKED |
| D09 zero fallback vs unavailable | missing authoritative P&L/quote/cost => UNAVAILABLE/BLOCKED | Proposed fail-closed rule |
| D10 cooldown/group identity | persist exit z, cooldown, group/order/execution IDs and config hash | UNRESOLVED |

A01–A09 from v0.2 remain **not passed** unless independent current evidence is attached. In particular A01 spread execution, A02 identity validation, A03 dimensional/source validation, A04 pending-path defect, A05 partial/cancel/restart, A06 actual P&L/account risk, A07 config enforcement and A08 test mapping remain BLOCKED/INCOMPLETE. A09 remains a governance rule, not a technical pass.

### 13.7 Decision Log conflict handling — No.956

No.956 explicitly defines Futures−Index basis and is preserved unchanged. The current v0.3 proposal instead uses near-month Futures minus far-month Futures. These are different spread definitions and must not be merged. Proposed follow-up, only after separate user approval: append a new Decision Log record explaining why No.956 is proposed for `폐기됨` or narrowed to a historical basis experiment, with this calendar-spread proposal as its alternative. **No.956 status remains unchanged in this task.**

### 13.8 Approval boundary

- Strategy status: `draft / unverified / unapproved / disabled`.
- Strategy registry, capital allocation and VTS automatic operation remain disabled; capital gate null blocks entry.
- No code edits, no tests run, no commit/push, no KIS Live orders.
- Required user confirmations before any later activation: (1) minimum capital/margin gate; (2) approval of calendar near/far as the final Strategy 3 spread and separate authorization to change the status/scope of No.956; (3) validated multiplier/hedge ratio and risk limits.
