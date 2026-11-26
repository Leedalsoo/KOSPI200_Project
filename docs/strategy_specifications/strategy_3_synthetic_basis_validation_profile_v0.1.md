# S3 Synthetic Basis-Arbitrage Validation Profile v0.1

- Status: **Virtual/validation-only proposal; not an approved production or live-trading specification**.
- Supersedes no historical decision. No.956 remains authoritative for the observed signal: same-time KOSPI200 Futures minus KOSPI200 Index.
- Purpose: validate a conventional two-leg cash-and-carry/basis mean-reversion model with synthetic-only instruments while preserving the existing production execution adapter's fail-closed behavior.

## 1. Strategy thesis and separation of signal from execution

Signal basis:

`basis_t = KOSPI200_Futures_t - KOSPI200_Index_t`

Use only the authoritative paired observations specified by No.956 for the signal history. Futures and Index source timestamps must be within 2 seconds; otherwise do not create that observation. The rolling mean/std and Z-score are computed from the basis history, not from ETF proxy prices.

The Index is a reference value, not a tradable leg. For isolated synthetic economic validation only, the second leg is represented by a separately identified **KOSPI200 cash-basket / ETF proxy**. This proxy is not an authoritative KIS instrument, not an approved product selection, and not an accepted market-data source.

## 2. Two-leg synthetic model

| Role | Synthetic leg | When basis Z > 0 | When basis Z < 0 |
|---|---|---|---|
| Futures spread leg | KOSPI200 Futures proxy | SELL | BUY |
| Cash-basket hedge leg | KOSPI200 Index-tracking ETF/basket proxy | BUY | SELL |

- The two leg identities must be distinct and separately namespaced as `SYNTHETIC_CONTRACT:`.
- The second leg is a cash-basket proxy, not a second Futures contract and not an option.
- The model must never create opposite orders on the same instrument identity.
- Both legs are paired as one spread group. A one-leg fill is PARTIALLY_EXPOSED, never ACTIVE.
- The production `Track3MultiLegExecutionPlanAdapter` remains blocked. This test model does not authorize or route production orders.

## 3. Synthetic hedge ratio

For one synthetic Futures contract:

`cash_units = round((futures_price * futures_multiplier) / (cash_proxy_price * cash_proxy_beta * cash_unit_multiplier))`

Use nearest whole cash units, with half-up rounding. In this profile, futures multiplier, cash proxy price, beta and unit multiplier are explicit synthetic inputs. No multiplier, beta, price or identity may be inferred from a missing field.

This is a notional hedge approximation, not a claim of perfect beta neutrality. Sensitivity tests must include beta drift, tracking error and rounding residual.

## 4. Provisional signal and lifecycle parameters

These are test-profile defaults only; they are not approved strategy thresholds.

| Parameter | Synthetic test default |
|---|---:|
| Rolling basis observations | 60 |
| Minimum warmup | 60 valid paired observations |
| Entry | `abs(z) >= 2.0` |
| Normalization exit | `abs(z) <= 0.5` |
| Stop | `abs(z) >= 3.5` |
| Maximum holding time | 60 elapsed minutes |
| Futures base quantity | 1 |
| Scale-in | Disabled |
| Concurrent S3 spread groups | 1 |
| Market regime | NORMAL only |
| Source timestamp pairing | <= 2 seconds, per No.956 |
| Cash proxy quote age | Synthetic fixture must be timestamp-aligned; real limit unapproved |

Entry additionally requires valid cost inputs, stable market regime, a normalizing/mean-reversion condition, distinct identities, positive multipliers, and an after-cost expected-edge gate. Missing inputs produce UNAVAILABLE/BLOCKED, not zero.

The 60-minute, Z thresholds, cash-proxy beta, cost model and position sizing are deliberately provisional and must be recalibrated and re-approved before any real-investment use.

## 5. P&L model

For a positive-Z entry (short Futures / long cash proxy):

`gross_pnl = (futures_entry - futures_exit) * futures_multiplier * futures_qty + (cash_exit - cash_entry) * cash_unit_multiplier * cash_qty`

For a negative-Z entry (long Futures / short cash proxy):

`gross_pnl = (futures_exit - futures_entry) * futures_multiplier * futures_qty + (cash_entry - cash_exit) * cash_unit_multiplier * cash_qty`

`net_pnl = gross_pnl - entry_fees - exit_fees - entry_slippage - exit_slippage`

Expected edge and realized P&L must remain separate. Do not use portfolio-wide P&L or option premium as a substitute for S3 spread-attributed P&L.

## 6. Required synthetic scenario matrix

1. Positive basis Z converges: short Futures + long cash proxy; net P&L after costs.
2. Negative basis Z converges: long Futures + short cash proxy.
3. Z moves farther from mean: stop path.
4. Z crosses entry threshold but market regime is HIGH_VOLATILITY/EXTREME_MOVE: no entry.
5. Basis history below warmup: no entry.
6. Futures/Index timestamp delta exceeds 2 seconds: omit basis observation.
7. Missing price, beta, multiplier, fees or slippage: UNAVAILABLE/BLOCKED.
8. Same synthetic identity supplied for both legs: reject.
9. Cash proxy beta/tracking error/rounding residual stress.
10. One leg fills and the other rejects or remains pending: PARTIALLY_EXPOSED; never mark ACTIVE.
11. Both legs partially fill with unequal hedge notional: exposure mismatch reported.
12. Duplicate entry signal while a group is pending/active: no second group.
13. Convergence exit, stop exit and 60-minute timeout.
14. Fee/slippage stress changes positive gross P&L into negative net P&L.
15. Restart/unknown order state: reconciliation-required test state; no blind retry.
16. Group close must use actual synthetic filled quantities, not requested quantities.

## 7. Provenance and safety boundary

- All synthetic identities use `SYNTHETIC_CONTRACT:` and remain test-local.
- Fixture metadata must state `runtime_eligible=false`, `identity_source_status=BLOCKED_IDENTITY_OWNER_UNRESOLVED`, `identity_policy.runtime_use=PROHIBITED`, `validation_only_use=SYNTHETIC_SCENARIO_ONLY`.
- No Raw/Canonical/accepted source, Option/Futures Master, market-data manifest or existing validation fixture is changed.
- No KIS, REAL_VTS, account or Live API; no broker order/cancel/liquidation; no collector restart or new collection.
- No Production strategy, adapter, Risk, OMS, Runtime, registry, capital gate or order-routing code is changed.
- This profile validates the economics and fault states of a hypothetical two-leg spread only. It does not clear the current production adapter's unresolved identity contract or any live readiness gate.

## 8. Re-approval before real investment

Before any production activation, independently confirm: actual tradable cash proxy/product and short-sale availability; authoritative identity and multiplier; beta/hedge ratio; synchronized quotes and liquidity; fees, taxes, borrow/financing and slippage; margin and account-level stress loss; execution sequencing/partial-fill repair; session/expiry/roll; and all thresholds against out-of-sample and walk-forward evidence. The user will review and revise these items again before real investment.

## Virtual Runtime capability boundary

- Read-only source trace: the existing Virtual multi-leg bridge, VSSF command-context provider, and canonical order transport accept only FUTURES and OPTION asset types. They do not currently support an equity/ETF cash-basket leg.
- Do not mislabel the synthetic cash proxy as a Futures contract to force routing. The current 37-test batch validates the isolated synthetic two-leg economics plus existing S3 source/profile/fail-closed contracts; it is not a full two-asset Virtual Runtime execution.
- Adding a synthetic equity/cash-basket asset to Virtual OMS/Router/VSSF is a separate architecture/contract task. No such runtime change was made.

## Additional validation-only coverage (No.1766)

The follow-up test batch extends the synthetic-only matrix without connecting the cash proxy to the existing Virtual OMS/Router:

- beta drift changes the notional hedge quantity and residual;
- nearest-unit rounding residual is bounded by half one cash-unit notional;
- proxy tracking error can overwhelm a profitable Futures leg and turn net spread P&L negative;
- asymmetric partial fills remain `PARTIALLY_EXPOSED`;
- an existing pending/active group prevents duplicate entry;
- restart snapshots are observation-only and do not authorize new entry or blind retry;
- close quantity is derived from actual filled quantity minus already-closed quantity, never requested quantity; over-close is rejected.

These are pure validation-harness rules, not Production policy or Runtime execution evidence. Actual broker reconciliation, partial-fill repair, atomic group routing, durable restart persistence, and ETF/equity Virtual asset support remain outside this test scope.

## 2026-11-25 No.1853 ? S2 U18/U19 and S3 synthetic validation follow-up

- Notion Q&A: https://app.notion.com/p/4235f4f6eaa181ab8382f08d76c353cf
- Reconciled No.1852, No.1836, No.1761, No.1764, No.1766, No.1838 and Current Baseline/A8 records. Existing collected and synthetic inputs remain provenance-labelled validation evidence; no new collection or source mutation.
- S2 accepted Runtime v2: 20261012 SHA256 `c360b12e4c55551542490e73693ca59d42c3eb3135496d310cee7ee9fead62b5`; 20261013 `331c01e819e9ddd4d0c39e98bf0c9d43b9a82e575743c0c34b74e8178f494cf5`; manifest `7657c90f13a81a7f98a8ccd075a259c8ec9795477a2a0541366094cd87e0360f`. Base S2 sidecar is 21 candidates/84 quotes (manifest `13580e010c34c74a1787bffb6b6b72adebdc4964f848937c0894bfa0fd4918b7`); U18 builder creates the 22nd candidate/88th quote. The already-extended 22/88 sidecar must not be re-used as builder input.
- S2 U18 stop-close + U19 four-leg restart E2E: 3 passed on current Project200 code. U18 closed all four synthetic legs and ended flat. U19 reconciled four PositionLots/account positions, persisted validation-only restart evidence, restored U16 retry state, and rejected restore with a pending order. No actual Runtime restore or order submission.
- First test attempt used the already-extended 22/88 sidecar and correctly hit the builder's append-count invariant. Reconnecting the original 21/84 source sidecar yielded 3 passed. No Production/test source changed.
- S1-S9 shared-runtime synthetic routing: 13 passed using P5 manifest SHA256 `47D6746BFD7ABFEA9D52016434CA06F097CA117E6724F96C522B58EB8E5590F` and exact KRX 20261008 anchor SHA256 `e770a22a882e71e500260203276a067fc27940587d1d7edcbd670548b36e20d9`. P5 is DERIVED_SCENARIO, validation_only=true, identity owner unresolved, runtime_use=PROHIBITED. Deterministic test-only signal driver, not natural-signal or profitability evidence.
- S3 synthetic basis harness + source/profile/fail-closed tests: 46 passed. Covers beta drift, hedge quantity/residual, tracking error, asymmetric partial fill, duplicate-entry guard, restart observation-only behavior and close-quantity bounds. Cash proxy remains synthetic; Virtual OMS/Router/VSSF supports FUTURES/OPTION only.
- No.1852 S1-S9 focused matrix remains S1 12 / S2 292 / S3 8 / S4 51 / S5 23 / S6 85 / S7 78 / S8 21 / S9 61 passed. Follow-up batches overlap; do not add into one acceptance total.
- S2 remains `PSB_UNVERIFIED`; S4 remains `DRAFT / UNVERIFIED / UNAPPROVED / DISABLED`; other OPEN/UNVERIFIED statuses remain unchanged. Natural-signal full lifecycle, real costs/margin/account risk and Production/Live readiness are not certified.
- No KIS/REAL_VTS/account/Live API, broker action, collector/service/scheduler, new collection, or Raw/Canonical/accepted-source/manifest original modification. Temporary data junctions were removed and source hashes remained unchanged.


## No.1861 ? Synthetic asset-type transport boundary (2026-11-26)

- CanonicalOrderTransport rejects `EQUITY`, `ETF` and `CASH_BASKET`; current transport supports only FUTURES/OPTION.
- Track3 production adapter remains unresolved even with a synthetic Futures identity. VirtualMultiLegExecutionBridge rejects a custom synthetic cash-basket identity type rather than treating it as Futures.
- Validation-only regression: six S3 modules, 51 passed. No Production source or routing contract changed.
- Actual cash proxy identity, short-sale/borrow, KIS Master, beta/tracking error, costs, liquidity, margin and account risk remain OPEN.
