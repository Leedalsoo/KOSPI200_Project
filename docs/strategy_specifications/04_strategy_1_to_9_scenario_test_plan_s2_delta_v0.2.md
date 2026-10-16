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
