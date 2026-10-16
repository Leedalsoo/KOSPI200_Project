# Strategy 9 — DTE7 / Quote Freshness / Restart-Reconciliation Validation Addendum

- Date: 2026-10-12
- Scope: documentation and read-only validation planning only.
- Status: **BLOCKED / NOT_RUN** for operational acceptance; no code, tests, commit/push, or Live orders changed.
- Baseline: branch `Project200`, HEAD and `origin/Project200` = `7eb9945e29774fb61fd2d07801762871b2506b98`.
- Related policy: `strategy_9_s1_put_insurance_spec_v0.3.md`, §12 and the user-confirmed DTE7/restart/priority amendment in the S9 delta matrix.

## 1. Trading-day calendar — source and acceptance

### Required source hierarchy

1. **Primary market calendar:** KRX official derivatives-market schedule/calendar, specifically the derivatives annual schedule page: https://open.krx.co.kr/contents/MKD/01/0110/01100303/MKD01100303.jsp
2. **Contract-specific expiry/listing identity:** the authoritative KIS/KRX Option Master or contract-master snapshot for the exact option contract; the expiry must be stored as `YYYYMMDD`. Calendar-day arithmetic or a guessed “third Thursday” rule is not a substitute for exact contract metadata.
3. **Cache/fallback:** use only a previously validated KRX-derived cache with provenance, version/date, and integrity status. If primary source and validated cache are unavailable or conflict, return `UNKNOWN/BLOCKED`; do not infer a trading day.
4. KIS instrument master is useful to confirm that the next expiry/contract is actually listed and tradable. It does not silently redefine KRX trading-day semantics.

### DTE7 interpretation that still needs an executable definition

- User-confirmed: DTE uses **trading days**, and the rollover evaluation reference is **11:00 KST (Asia/Seoul)**.
- Still to define/test explicitly: whether DTE7 means seven eligible trading sessions remaining including/excluding the expiry session, how the expiry session itself is counted, treatment of exchange-announced exceptional closures, and whether 11:00 is the decision snapshot time or order submission time. Preserve the user's 11:00 KST requirement; do not choose an off-by-one convention without a testable rule.
- Required test vectors: normal weekly/monthly expiry, intervening weekend, KRX holiday, exceptional closure/calendar correction, next expiry not yet listed at 11:00, listing becomes available later, and expiry/contract-master disagreement.
- Each result must log KRX calendar source/version/hash, retrieval timestamp, timezone, exact expiry, included session dates, computed DTE, and the 11:00 decision timestamp.

## 2. Quote freshness — no arbitrary threshold

- The KIS Developers API documents REST quote and WebSocket real-time market data separately, but that documentation alone does **not** establish a safe universal quote-age threshold for this strategy. See https://apiportal.koreainvestment.com/apiservice
- The quote-age threshold remains **UNSET / BLOCKING** until the exact option quote schema and timestamp semantics are confirmed (exchange/source timestamp versus receive timestamp, timezone, precision, update cadence, and behavior during no-trade intervals).
- Required configuration fields before runtime approval:
  - `max_quote_age_ms` or a unit-explicit equivalent (no null/default-to-zero behavior);
  - maximum receive-to-source clock skew and clock-health status;
  - required bid/ask validity, crossed/locked-market handling, and maximum spread/depth criteria;
  - separate policy for REST snapshot age versus WebSocket event age, if both are used.
- Establish the threshold using actual KIS VTS option quote captures across active, quiet, gap, reconnect, and expiry-session periods. Predeclare the acceptance rule and holdout window. Do not copy a stock-feed threshold or invent a number for options.
- Fail-closed rules: missing/invalid source timestamp, unknown timestamp semantics, stale quote, wrong contract/expiry, crossed/invalid market, disconnect/reconnect gap, or clock skew beyond the approved bound => `BLOCKED/UNAVAILABLE`; no new entry, fallback strike, rebuy, or rollover order. A stop/trailing decision also must not be evaluated from a fabricated or stale mark; retain the lot and require reconciliation/operational escalation rather than resetting state.
- Log source timestamp, local receive timestamp, computed age, source/transport, contract identity, bid/ask/depth, and the freshness rule/config hash for every trigger evaluation.

## 3. Restart restoration and execution reconciliation — acceptance matrix

| Case | Required persisted state / authoritative evidence | Expected result | Status |
|---|---|---|---|
| Clean restart with open S9 lots | Lot ID; exact option identity and expiry; each actual entry execution ID/price/quantity; filled remaining quantity; trailing-armed flag; high-water mark; last processed market-data timestamp; spec/config hash | Restore by lot; compare to broker executions and current positions before enabling actions | NOT_RUN |
| Missing/corrupt lot snapshot | Broker executions, open orders and positions | No inferred average entry or zero watermark; block entry/rebuy/roll and resolve discrepancy | NOT_RUN |
| Snapshot says open, broker says flat | Authoritative executions/positions and close fills | Reconcile terminal state; only reset after confirmed flat | NOT_RUN |
| Snapshot says flat, broker says open | Broker executions/positions and order history | Rebuild or quarantine lot; no duplicate buy or reset | NOT_RUN |
| Partial fill / late fill after cancel request | Order status plus all execution reports, including late updates; broker position snapshot | Apply each fill once by execution ID; cancel request/ACK alone is not terminal; block fallback until reconciled | NOT_RUN |
| Fill stream and position snapshot disagree | Independent order/fill/position reads with timestamps | `RECONCILIATION_REQUIRED`; retry with bounded policy; no new exposure until consistent | NOT_RUN |
| Restart while trailing armed | Persisted high-water mark and source-timestamped quote series | Restore peak without lowering it; evaluate only after a fresh same-contract quote | NOT_RUN |
| Duplicate/replayed execution report | Stable execution ID and previously applied IDs | Idempotent no-double-count; resulting lot quantity equals broker truth | NOT_RUN |
| Simultaneous trailing, stop and rollover | Same evaluation cycle, fresh quote and exact DTE snapshot | Trailing exit > stop-loss > rollover; one action per lot; no rollover/re-entry until exit fills and positions reconcile | NOT_RUN |

### Minimum reconciliation invariant

For each exact contract and lot/provenance group:

- `broker_position_qty = sum(applied fills) - sum(applied close fills`, adjusted only by explicitly supported broker corrections/assignments/expiry events.
- Open orders, partial fills, pending cancel/replace, and late fills are tracked separately from filled position quantity.
- A fill is applied idempotently by broker execution ID. ACK, order acceptance, cancel request, and a local state transition are not proof of fill, cancel completion, or flatness.
- Lot-level entry price and high-water mark must never be silently averaged across lots or reset before authoritative reconciliation.
- Reconciliation must include exact contract/expiry, side, multiplier, filled and residual quantity, order/execution IDs, event/source timestamps, fees, and final broker position snapshot ID.
- If the broker does not expose enough data to prove one of these invariants, the result is BLOCKED rather than inferred PASS.

## 4. Read-only source inspection result

- Existing `core/strategy/track9_event_overnight_insurance.py` still implements the legacy PUT/CALL overnight pair and `Track9State` fields, not the approved v0.3 per-lot S1-linked insurance lifecycle.
- Therefore the current legacy strategy state is not evidence that v0.3 lot persistence, high-water restoration, quote freshness, or reconciliation is implemented.
- No S9 v0.3 runtime test, restart fault-injection test, KIS VTS quote-age measurement, or calendar-boundary test was run in this task.

## 5. Exit gate

Do not mark this complete until all are true:

1. KRX-derived calendar adapter/cache and exact expiry semantics are documented, versioned, and tested against explicit holiday/off-by-one vectors.
2. KIS option quote timestamp semantics are confirmed; quote-age and market-quality thresholds are configured from measured VTS evidence and approved.
3. Restart recovery reconstructs lot state from persisted state plus broker fills/positions and fails closed on every mismatch case above.
4. Duplicate, partial, late-fill, cancel-race, and simultaneous-trigger tests pass on the actual v0.3 execution path.
5. Evidence records show the code/config hash, test command and exit code, calendar and quote source provenance, order/fill/position IDs, and final reconciled quantities.

**Current overall verdict: BLOCKED.** The policy decisions are recorded, but their market-data source contracts, numerical freshness threshold, and runtime recovery behavior are not yet validated.

## 1A. DTE7 deterministic test contract (definition pass 1)

### Counting convention for the test oracle
- Decision snapshot: 11:00:00 Asia/Seoul on trading date D.
- Let E be the exact expiry date from the authoritative contract master, stored as YYYYMMDD.
- Let S(D,E) be the ordered set of KRX-open derivatives trading sessions whose dates are strictly greater than D and less than or equal to E. D is excluded; E is included only if KRX confirms it is a valid session for that contract.
- `DTE7 = |S(D,E)|`; the DTE7 rollover evaluation fires only when the count is exactly 7 at the 11:00 KST decision snapshot. Calendar-day subtraction is forbidden.
- If E is absent from the session set, expiry metadata is invalid, the calendar has an unconfirmed gap, or contract master conflicts with the calendar, result is `UNKNOWN/BLOCKED`, not a guessed count.
- This convention makes the off-by-one rule executable. It is a proposed test oracle derived from the user's “trading days” requirement; it must be checked against the intended product-specific DTE convention before runtime activation. It does not authorize orders.

### Deterministic fixture cases
For these unit tests, inject an explicit fixture calendar and expiry; do not depend on live KRX access or the machine's local calendar.

| Test ID | Fixture / input | Expected result |
|---|---|---|
| CAL-01 | D is Monday; E is the seventh KRX-open session after D, with no holidays | DTE=7; trigger at 11:00 KST |
| CAL-02 | Same E, but decision D is one KRX session later | DTE=6; no DTE7 trigger |
| CAL-03 | Weekend lies between D and E | Weekend dates do not increment count |
| CAL-04 | A weekday between D and E is marked KRX holiday | Holiday does not increment count |
| CAL-05 | Exceptional closure/corrected calendar removes a previously counted session | Recompute using versioned corrected calendar; log old/new version; block while calendar versions conflict |
| CAL-06 | E itself is a confirmed trading session | E is counted as the final remaining session |
| CAL-07 | E is not an open session or does not match the exact listed contract | UNKNOWN/BLOCKED; no rollover |
| CAL-08 | Next-month contract is not listed at 11:00, then appears later | At 11:00 record WAITING_FOR_LISTING; re-check listing and full preflight after listing; do not submit a speculative order |
| CAL-09 | KRX calendar endpoint unavailable, verified cache valid and same version/provenance | Compute from validated cache and record cache provenance |
| CAL-10 | No valid calendar/cache or calendar conflicts with contract master | UNKNOWN/BLOCKED |
| CAL-11 | Process timestamp is UTC or host-local rather than Asia/Seoul | Normalize decision snapshot to Asia/Seoul; if conversion/clock health cannot be proven, BLOCKED |
| CAL-12 | DTE=8 or DTE=6 at the decision snapshot | No DTE7 trigger; record computed value and reason |

### Calendar acceptance evidence
Each case must assert the computed session-date list, count, exact expiry, 11:00 KST decision timestamp, source/version/hash, contract-master snapshot ID, trigger decision and block reason (if any). A test passes only if both the numeric result and the decision/action gate match. No order adapter is invoked by these unit tests.
