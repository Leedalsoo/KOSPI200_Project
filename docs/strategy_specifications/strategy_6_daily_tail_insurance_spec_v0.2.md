# Strategy 6 — Daily Tail Insurance 판단요소별 상세 명세 v0.2
- 상태: **초안 v0.2 / 판단요소별 구조 보강 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- v0.2 변경: F01~F29 판단요소별 현행 사실/목표 규칙/미결정 상태, 상태 전이, 수용 게이트 추가
- 현 코드: core/strategy/track6_daily_tail_insurance.py v1.0
- 연결: Track6ExecutionInput, Track6OptionContractSource, AnalyticsSnapshot, build_pair_plan, resolve_track6.

## 1. 목적 — 미확정
현 코드는 당일 변동성이 기준 대비 높을 때 long PUT+CALL insurance pair를 매수하고 같은 날 trailing/시간 cutoff로 청산하려는 구조다. 보호 대상, tail payoff 목적, 프리미엄/손실 예산은 미확정이다.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- Required analytics: price.last, active/base/ratio volatility, portfolio.premium_spent.
- ExecutionInput provides date/time, listed PUT/CALL strikes and multiplier.
- Entry if base_vol>0, active_vol >= base_vol*1.3, multiplier positive, both strikes exist. Default quantity 1.
- State is_active is set before pair fills. Entry proposal is PUT BUY; resolver/build_execution_plan creates PUT+CALL pair.
- Current take-profit uses strike-distance “intrinsic” proxy. It derives a multiplier from premium_spent/qty, not contract multiplier and actual marks, so it is not authoritative option pair MTM.
- Trailing activation uses 1.5x or 2.0x spent, then 85/88/90% retention tiers.
- Time exit: from LIMIT_CUTOFF to MARKET_CUTOFF request LIMIT close; at/after MARKET_CUTOFF request fallback close. Exact session constants need reconciliation with authoritative calendar.
- Close proposal is PUT SELL and resolver closes actual open lots. Reset requires group_complete and position_flat.

## 3. 목표 lifecycle
WAITING_FOR_SESSION → VOL_TRIGGER_CHECK → CONTRACT/BUDGET_PREFLIGHT → ENTRY_PLANNED → ENTRY_WORKING → PARTIAL/ACTIVE → TRAILING_OR_TIME_EXIT → EXIT_PENDING → FLAT_CONFIRMED → CLOSED. “Daily” entry cap/reset must never hide an open prior-day position.

## 4. 필수 데이터
Authoritative session/calendar; active/base volatility formula/source/freshness; exact expiry/type/strike/instrument ID/multiplier; quotes/marks and fill prices for both legs; premium budget/max loss/fees/slippage; open lots and fill provenance; cancel/reject/partial state.

## 5. 미결정 항목
1. entry window and max entries/day.
2. 1.3 volatility trigger and baseline.
3. ATM/strike/expiry selection.
4. max premium/max loss and account capital gate.
5. actual pair MTM vs intrinsic proxy and trailing activation.
6. 1.5x/2.0x and 85/88/90 tier policy.
7. exact LIMIT_CUTOFF/MARKET_CUTOFF/PENDING_CANCEL_END handling.
8. one-leg/partial pair entry and emergency risk response.
9. daily reset only after both legs flat.
10. multiplier, fees/slippage and risk enforcement.
11. restart, stale quote and overnight residual handling.

## 6. 검증 시나리오
Volatility exactly around 1.3x; missing/stale strike/multiplier/quote; PUT-only/CALL-only/partial pair fill; premium_spent zero/stale; mark vs intrinsic mismatch; trailing tier boundaries; cutoff/limit/fallback/cancel-race; new date while prior position remains; partial close/restart/flat confirmation.

## 7. 추적/판정
관련 코드: track6_daily_tail_insurance.py, Track6OptionContractSource, resolve_track6, build_pair_plan, MultiLegBridge/PositionLotStore.
**BLOCKED** — P&L proxy and pre-fill active state are insufficient for approved execution.

---

## 8. 판단요소별 상세 정의 — v0.2 핵심

| ID | 판단요소 | 현재 코드에서 확인된 사실 | 신규 명세의 목표 규칙 | 결정 상태 / 차단 사유 |
|---|---|---|---|---|
| F01 | 전략 목적·경제적 역할 | Daily volatility trigger 후 long PUT+CALL pair를 사는 보험 전략. 보호 대상/maximum tail payoff 미정. | Covered exposure, protection horizon, payoff and cost/benefit objective define. | **미결정** |
| F02 | 적용 시장·상품 | Track6OptionContractSource requires KOSPI200 option multiplier 250,000 and listed PUT/CALL identities. | General KOSPI200 options only; exact identity/expiry/multiplier and no Mini options. | **부분 확인** — exact expiry/quotes need validation |
| F03 | 운용 주기·활성화 | Daily bought_date state; cutoff uses MarketSessionPolicy 15:00/15:15; no clear max entry/day beyond active state. | Official session calendar, daily lifecycle, entry window, prior-day residual handling and expiry/overnight rules. | **미결정** |
| F04 | 기준가격·시점 | Analytics current price/active/base vol/premium; input has date/time, strikes and multiplier. | Same-snapshot provenance for quote, vol, contract, premium, fills and account risk. | **미결정** — quote/fill source and freshness |
| F05 | 진입 신호·조건 | active_vol >= base_vol*1.3, base_vol>0, multiplier positive, both strikes present. | Source-backed volatility trigger and boundary equality, budget and session gates. | **미결정** — 1.3x rationale |
| F06 | 추가 진입/rebuild | is_active suppresses repeat entry while active; state becomes active before pair fill. | One pending/active lifecycle; scale-in prohibited unless separately approved; rejected no-fill entry must reconcile and restore eligibility safely. | **BLOCKED** — pre-fill state and no entry callback |
| F07 | pending/cancel lifecycle | In cancel window evaluate_buy returns a CANCEL signal without execution proposal; pending tranche cancellation lifecycle not represented per leg in strategy state. | Separate cancel event from trade signal; per-leg order/cancel/cancel-race and pending status. | **미검증** |
| F08 | contract selection | Option source prefers symmetric 12.5 offset if listed, otherwise nearest listed OTM PUT/CALL around underlying; multiplier equality/positivity checked. | Exact YYYYMMDD expiry, contract IDs, tradability, quote, strike/tick and paired expiry verified. | **부분 확인** |
| F09 | strike/tick/price | Listed pair selection; fallback strikes are closest to current±12.5 but no executable quote check in selector. | Listed strikes only, official tick rounding, spread/liquidity/quote-age gate, symmetric or explicitly approved asymmetry. | **미결정** |
| F10 | volatility/regime | Trigger multiplier default 1.3; trailing activation factor is 1.5 below active_vol 1.3, else 2.0. | Define active/base vol sources, units, windows, freshness and regime-boundary behavior. | **미결정** |
| F11 | additional signal features | Strategy depends on price.last, active/base/ratio vol and premium_spent; no separate event/flow confirmation. | Decide whether any further tail-risk features are required; missing required feature blocks entry. | **미결정** |
| F12 | quantity/capital/cost | Default qty=1 per PUT and CALL; premium_spent analytics is used. Total capital/premium/max-loss/account risk enforcement not proven. | Editable total capital, strategy premium cap, strategy/account max-loss, margin, fees, slippage and pair qty cap. | **수치 미확정** |
| F13 | order pricing/reprice | Entry proposal requested_price absent; pair plan defines sides/strikes/qty but not per-leg price policy. | Limit price/tick, net debit cap, bid/ask, repricing, cancel/replace and timeout per leg. | **미결정** |
| F14 | group preflight | resolver/build_execution_plan creates PUT+CALL pair; standard risk path exists. Complete premium budget and pair max-loss preflight not proven. | Both legs identity/quote/premium/fees/account risk checked together before any order. | **미검증** |
| F15 | partial/reject/unknown | is_active state set before entry fills; callback handles only close tags and resets only group_complete + position_flat. | Per-leg fill state; partial one-leg entry must be managed or safely reduced per approved recovery policy. | **BLOCKED** |
| F16 | hedge/extra legs | No Futures hedge; pair is long PUT+CALL. | No extra hedge leg unless separate approved thesis; pair protection exposure tracked independently. | **부분 확인** |
| F17 | holdings/exposure | State stores PUT/CALL strikes, bought_date, intrinsic watermark and trailing flag, not per-leg fills/qty/mark. | Authoritative actual open lots, fills, multiplier, premium, current Greeks/MTM and group exposure. | **미검증** |
| F18 | stop/max loss | No explicit max-loss exit in shown strategy; premium paid bounds theoretical loss only if pair is fully filled and ownership correct. | Max premium paid, strategy/account max-loss, stress and stale-market risk response. | **미결정** |
| F19 | take-profit/trailing | “Intrinsic” proxy multiplies strike distance by premium_spent/qty, not official contract multiplier or option mark; thresholds 1.5x/2.0x spend and 85/88/90 retention. | Actual option bid/ask or approved mark-to-market, contract multiplier, fees, high watermark and giveback policy. | **BLOCKED** — current proxy not actual option MTM |
| F20 | time exit/expiry | LIMIT close from 15:00 to 15:15; fallback close at/after 15:15; no explicit exact contract expiry rule. | Exact YYYYMMDD, official final trading cutoff, cancel/replace, overnight and flat confirmation. | **미결정** |
| F21 | close scope/quantity | Close proposal PUT SELL; resolver uses open lots; state resets only group_complete and position_flat. | Actual open lots determine both PUT and CALL close quantities/directions; verify all flat before reset. | common principle aligned; full per-leg evidence **미검증** |
| F22 | P&L/fees/slippage | Current take profit uses intrinsic proxy; no authoritative pair MTM/realized fee attribution in strategy decision. | Per-leg actual fill/mark/multiplier/fees/slippage and combined/account P&L. | **BLOCKED** |
| F23 | trigger priority | Active path checks cutoff before take profit; take-profit suppressed at/after 15:12. | Deterministic priority among max-loss, trailing, 15:00 limit exit, 15:12 suppression, 15:15 fallback and pending cancel. | **미결정** |
| F24 | lifecycle/provenance | Pair group plan built from state; close callback only uses group_complete/position_flat. | run/group/evaluation/leg/order/execution IDs, config hash, per-leg state and final accounting. | **미검증** |
| F25 | restart/duplicate/timeout | reset clears state; durable restore of bought_date/open pair/pending close is not shown. | Restore open lots/orders/fills/watermark and bought date before new daily decision; no blind retry. | **미결정** |
| F26 | cross-strategy/account risk | No explicit account aggregate exposure/overlap check in strategy class. | Aggregate premium, margin, tail stress and correlated protection across strategies; avoid double-counting protection. | **미결정** |
| F27 | data failure/unavailable | Analytics must be AVAILABLE; missing strikes/multiplier or invalid volatility returns no entry. | Stale quote/contract/position/marks are UNAVAILABLE; existing positions still require exit/reconciliation handling. | **미검증** |
| F28 | editable settings | vol_trigger_multiplier and insurance_qty constructor settings; account capital/premium/max-loss runtime enforcement not proven. | Versioned editable capital, strategy premium cap, strategy/account max-loss, qty, trigger and fees/margin; hash and effective date. | **수치·강제경로 미확정** |
| F29 | tests/acceptance | tests cover trailing close proposal and non-execution watermark update; integration/candidate tests exist but not full risk/expiry acceptance. | Test pair partial/reject, quote identity, real MTM, all cutoff boundaries, cancel-race, prior-day residual and account limits. | **미완료** |

## 9. Strategy 6 목표 상태 전이표 — 구현 전 계약

| 현재 상태 | 이벤트/조건 | 다음 상태 | 필수 가드·행동 | 실패 처리 |
|---|---|---|---|---|
| DISABLED | ON/config valid | WAITING_FOR_SESSION | entry permission/config version | unknown → BLOCKED |
| WAITING_FOR_SESSION | official session and sources ready | VOL_TRIGGER_CHECK | same-time vol, quote and contract identity | stale/missing → UNAVAILABLE |
| VOL_TRIGGER_CHECK | active/base threshold passes | CONTRACT_BUDGET_PREFLIGHT | listed pair, premium budget, max-loss/account risk | any leg fails → no order |
| CONTRACT_BUDGET_PREFLIGHT | both legs validated | ENTRY_PLANNED | stable group id and reserve budget | risk fail → BLOCKED |
| ENTRY_PLANNED | plan persisted | ENTRY_WORKING | PUT/CALL independent order states | uncertain route → RECONCILIATION_REQUIRED |
| ENTRY_WORKING | both legs filled/reconciled | ACTIVE | actual lots, cost and marks confirmed | partial/reject → PARTIALLY_EXPOSED |
| ENTRY_WORKING | one leg only/partial | PARTIALLY_EXPOSED | follow approved wait/cancel/complete/reduce policy | no policy → BLOCKED |
| ACTIVE | trailing/max-loss/time cutoff | EXIT_PENDING | grouped close for all actual open legs | missing close leg → BLOCKED |
| EXIT_PENDING | partial/cancel race | EXIT_PENDING | reconcile each remaining qty | unknown → RECONCILIATION_REQUIRED |
| EXIT_PENDING | both option lots flat confirmed | FLAT_CONFIRMED | authoritative position read model | mismatch → RECONCILIATION_REQUIRED |
| FLAT_CONFIRMED | P&L/fees finalized | CLOSED | persist result and config hash | mismatch → BLOCKED |
| any active state | new date/restart/API failure | RECONCILIATION_REQUIRED | reconcile old lots before resetting daily state | cannot reconcile → BLOCKED |

## 10. 명세-코드-테스트 추적 및 수용 게이트

| 추적 ID | 관련 경로/기준 | 검증 산출물 | 현재 판정 |
|---|---|---|---|
| S6-F01~F06, F10~F12, F18~F20, F23 | core/strategy/track6_daily_tail_insurance.py, core/strategy/engine/s6_engine.py, s6_rules | thesis, trigger, cutoff and trailing boundary tests | BLOCKED |
| S6-F02, F08~F09, F13~F14 | track6_option_contract_source.py, resolve_track6, build_pair_plan | exact identity, executable quotes and group preflight | INCOMPLETE |
| S6-F07, F15, F17, F21, F24~F25 | on_execution_result, MultiLegBridge, PositionLotStore | pair partial/reject/cancel-race/restart/all-flat evidence | BLOCKED |
| S6-F19, F22, F26, F28 | option mark/P&L, fee/margin providers, editable risk config | actual MTM and account risk limits | BLOCKED |
| S6-F29 | tests/strategy/test_strategy6.py, s6_engine_candidate, Virtual integration | F01~F29-to-test evidence | INCOMPLETE |

Acceptance gates:
- A01: insurance objective and eligible daily window approved.
- A02: exact listed PUT/CALL contracts and multiplier/quotes validated.
- A03: both-leg budget and group risk preflight pass before routing.
- A04: state changes only from authoritative entry/exit fills; partial pair has approved recovery.
- A05: actual option pair MTM, fees, multiplier and trailing watermark verified.
- A06: 15:00 limit, 15:12 take-profit suppression, 15:15 fallback and pending cancel semantics are consistent with calendar.
- A07: prior-day open lots block daily reset/re-entry until reconciled.
- A08: editable capital/premium/max-loss/account risk settings enforced.
- A09: F01~F29 mapped to tests and user approval separate from validation.

## 11. 미결정·승인 필요 항목

| ID | 결정 필요 사항 | 필요한 근거 | 현재 영향 |
|---|---|---|---|
| D01 | daily entry window/max count | session calendar and position lifecycle | daily policy incomplete |
| D02 | 1.3 volatility trigger and source | vol formula/window/regime scenarios | entry threshold unapproved |
| D03 | strike/expiry selection | listed contract master and live quotes | contract choice incomplete |
| D04 | premium/max-loss/account capital values | account capital, quotes, fees, margin, stress | numbers require separate approval |
| D05 | intrinsic proxy replacement | option marks/fills/multiplier and fees | current trailing not authoritative |
| D06 | cutoff/cancel semantics | session policy, pending order state, broker behavior | end-of-day flow unresolved |
| D07 | one-leg partial recovery | group risk and exposure scenarios | execution blocked |
| D08 | overnight/prior-day residual | expiry/session/restart evidence | no daily reset until flat |
| D09 | account aggregate risk/double insurance | all strategy positions and stress correlation | enforcement unproven |
| D10 | state restore and P&L finalization | order/fill/position/ledger provenance | lifecycle incomplete |

## 12. v0.2 판정

- 상태: **초안 / 미검증 / 미승인**.
- 판단요소: **F01~F29 29/29 작성**.
- 주요 차단: pre-fill active state, intrinsic proxy based on premium_spent, pair partial-fill policy, cutoff/cancel semantics, expiry and account risk.
- Document structure only; no strategy scenario/E2E tests run.
- Code changes/commit/push/KIS Live orders: none.
- Next: Strategy 7 same F01~F29 depth.
