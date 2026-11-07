# Runtime Market-Data Freshness Policy Decision Sheet v0.1
**Date:** 2026-10-14 KST  
**Status:** Decision proposal / approval required / not an implementation specification.

## 1. Purpose
Define the policy questions that must be resolved before a common KIS freshness gate can be implemented. The sheet deliberately separates verified source behavior from policy choices. It does not authorize code changes or order routing.

## 2. Verified source behavior

| Source | Field/behavior observed in code | What can currently be concluded | What cannot currently be concluded |
|---|---|---|---|
| KIS REST option price + order book | `aspr_acpt_hour`; price and book time strings compared when both are non-empty | The two returned strings can be checked for equality | Absolute source age, date, timezone-aware instant, future skew, and valid max age are not established by the current normalizer |
| KIS WebSocket option record | Source hour extracted from H0IOCNT0 payload; `received_at` supplied by collector | Receive timestamp and raw source-hour string can be retained | Setting `observed_at=received_at` alone does not prove source event age; source date/time semantics and clock skew are unresolved |
| KIS daily rolling market-time response | KIS `today` and date1..date5 with session times in captured evidence | The response can provide an authoritative current trading-day/date window for that response | It does not prove REST/WS quote timestamp semantics or annual calendar coverage |

## 3. Proposed common rules for approval

1. **Timestamp parsing:** Preserve the raw source timestamp verbatim. Parse to an absolute instant only after the exact KIS field semantics and timezone are documented. Do not silently substitute local receive time for a missing/invalid source timestamp.
2. **Date association:** If the source supplies time-of-day without a date, do not attach a date based only on the machine clock. A date association rule must cite an authoritative KIS trading-date source and define session rollover handling. Until then, source age is `UNKNOWN`.
3. **Receive time:** Store collector receive time separately from source event time. Use receive time for transport-latency diagnostics only; it is not an automatic replacement for source event time.
4. **Freshness states:** Use at least `FRESH`, `STALE`, `UNKNOWN`, and `CONFLICT`, with reason, source/TR, exact contract identity, raw hash/reference, source timestamp, receive timestamp, policy version, and evaluation timestamp.
5. **Missing/ambiguous source timestamp:** `UNKNOWN` and fail-closed for risk-increasing order admission. REST timestamp equality does not make the observation fresh.
6. **Multi-leg coherence:** Every required leg/input must independently pass identity and freshness checks. If any leg is `STALE`, `UNKNOWN`, or `CONFLICT`, block the new multi-leg entry. The maximum allowed cross-leg timestamp spread remains unset pending approval and source-cadence evidence.
7. **Stale exposure handling:** Do not create an implicit stale-data exception for reduce/hedge/close orders. Require authoritative contract identity, reconciled position quantity, pending/terminal order state, and a separately approved pricing/execution rule. If any are unknown, remain `BLOCKED`.
8. **Gate location:** The common verdict must be mandatory before `RiskGate.admit_order()` for single-order and each multi-leg path. Risk approval remains necessary but does not substitute for freshness approval.
9. **Recovery:** A newer quote may clear only the freshness condition it proves; it must not clear unresolved account, order, fill, position, or contract-identity blockers.
10. **Evidence:** Keep KIS VTS, KIS Live, Virtual/replay, and synthetic evidence separated. Never log credentials or full account identifiers.

## 4. Values intentionally not selected

The following are data-policy decisions and are not inferable from current source code alone. They remain `UNSET` until supported by official KIS field documentation, observed update cadence, strategy input requirements, and explicit user approval:

- Maximum age by input class: option last/bid/ask/order book, underlying index/futures, Greeks/IV, and any derived analytics.
- Whether REST and WebSocket require different age limits.
- Exact source timestamp field definition, timezone, date association, session rollover and future-clock-skew allowance.
- Maximum cross-leg timestamp spread and synchronization requirements.
- Whether any reduction/hedge path can be permitted when current quotes are stale; required reconciliation and pricing controls.
- Policy version ownership, effective time, audit retention and invalidation rules.

**Current fail-closed interim state:** Until the above are approved and implemented, the existing code must not be described as enforcing a common freshness gate. Inputs whose source age cannot be proven remain `UNKNOWN/BLOCKED`; no new risk-increasing order may be admitted on the basis of such input.

## 5. Required evidence before approval

- Official KIS documentation for `aspr_acpt_hour` and the H0IOCNT0 source-hour field, including whether the field is trade/quote/event time and what timezone/date applies.
- A sanitized sample set with raw hashes, source fields, KIS trading date, receive timestamps and observed cadence. No credentials or account amounts.
- Strategy-by-strategy input dependency map S1–S9 and multi-leg synchronization requirements.
- Explicit user decision on the numeric age limits, future skew, cross-leg spread and stale-exposure policy.

## 6. Implementation remains blocked

No runtime code or tests were changed/created by this policy sheet. The next approval request must show the exact policy values and the file-level gate/test diff plan. A separate explicit approval is required before implementing strategy/data-policy changes.
