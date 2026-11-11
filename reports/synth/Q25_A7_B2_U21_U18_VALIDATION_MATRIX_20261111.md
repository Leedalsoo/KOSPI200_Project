# Q25 A7 B2 — U21 quote validity and U18 exit-policy validation matrix

Status: validation-only candidate matrix. No operating threshold or fallback rule is approved by this report.

## U21 — quote validity / conservative fallback

| Dimension | Validation cases | Expected fail-closed behavior |
|---|---|---|
| Contract identity | exact instrument/symbol; mismatch | mismatch blocks primary and fallback |
| BID/ASK completeness | both present; BID missing; ASK missing; non-positive; crossed | incomplete/invalid pair is not accepted |
| Source time | timezone-aware; missing; future; stale; semantics unverified | unknown/stale source cannot be treated as fresh |
| Source capability | verified; unverified | unverified capability blocks |
| Provenance | source + raw payload SHA-256; missing/invalid hash | incomplete provenance blocks |
| Spread | absolute; relative-to-MID; below/equal/above limit | policy must explicitly select measure and limit |
| Fallback | alternate source fresh/valid; absent; stale; wrong identity; wide | only valid alternate source can be selected; otherwise block |
| Price side | BUY uses conservative ASK; SELL uses conservative BID | no synthetic mark or receive-time substitution |
| Tick | BUY ceiling; SELL floor; missing tick | missing rounding/tick policy blocks |
| Submission | every decision outcome | order submission remains disabled |

Candidate decisions still requiring explicit approval: max age, spread value/unit, fallback source priority, intended spread measure, tick size/rounding. The validation evaluator accepts these only as injected inputs and has no production defaults.

## U18 — net group PnL exit-policy matrix

Formula structure already selected in prior decisions:
- Net PnL ratio = fee/slippage-inclusive group net PnL / initial group net premium received.
- Stop-loss candidate condition: ratio <= negative stop-loss limit.
- Trailing activation: peak net-PnL ratio >= activation threshold.
- Trailing pullback: (peak ratio - current ratio) / peak ratio >= pullback threshold.

| Dimension | Boundary matrix | Expected result |
|---|---|---|
| Group evidence | complete 4 legs; incomplete leg | incomplete blocks |
| Marking | all four BID/ASK MID; any missing side/time/provenance | missing evidence blocks |
| Costs | realized + unrealized fees/slippage all present; any missing | missing cost evidence blocks |
| Freshness | verified; false/unknown | unverified blocks |
| Denominator | positive initial net premium; null/zero/negative | invalid blocks |
| Stop loss | ratio above; exactly at; below explicit negative limit | HOLD; STOP_LOSS; STOP_LOSS |
| Trailing activation | peak below; exactly at; above activation | inactive; active; active |
| Pullback | below; exactly at; above explicit pullback limit | HOLD; TRAILING_EXIT; TRAILING_EXIT |
| Policy defaults | any threshold null | POLICY_INPUT_BLOCKED |
| Submission | all verdicts | order submission remains disabled |

Numeric stop-loss, trailing activation and pullback ratios remain unapproved. No numeric defaults are introduced into Track2 strategy or operating configuration. Test-only injected values are solely boundary fixtures, not policy recommendations or operating settings.

## Safety boundary
- No Runtime/OMS wiring or order submission.
- No Live, REAL_VTS, account, balance, order, cancel, or correction API.
- No .env, collector, scheduler, permission, or operating configuration changes.
- Existing Track2 strategy ratios remain None; its production exit gate remains blocked.
