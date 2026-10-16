# Strategy 1 Code-Intent Difference Table v0.3
- Date: 2026-10-12
- Status: draft / unverified / unapproved
- Baseline: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- Document only. No code edits or test execution.

| Path | Observed current behavior | User intent §1 | Status |
|---|---|---|---|
| core/strategy/track1_tail_defense.py | Imports delta_to_mini_futures_qty; state includes futures_hedge_count and active hedge fields; release threshold is 1.5; DTE cutoff is 4; builds outer CALL/PUT and inner PUT fence; hedge proposal is FUTURES; state changes before confirmed fill; fence state clears immediately at DTE cutoff | Base long CALL/PUT each 1 at ATM ±12.5; option short cap 10; option hedge at configurable nearest-short distance, ratio 1:1; release ±5; all S1 legs close at DTE4; no Futures hedge | MISMATCH; legacy Futures path; reset risk |
| application/composition/track1_runtime_input_provider.py | Reads S1 lots/identities and calculates short coverage/net delta using SELL lots and option delta; missing sources recorded; provides fence direction/momentum/DTE/net delta | Link hedge to actual short residual quantity and use sale-time premium, candidate option quote and liquidity | Partial mismatch; required inputs not demonstrated |
| application/composition/automated_virtual_runtime_factory.py resolve_track1 | Handles S1 Futures proposals through single-leg Futures plans; non-Futures proposal returns None; no demonstrated S1 option group resolver | Option-only hedge and grouped base/short/hedge option legs with independent fill lifecycle | Mismatch; option routing not demonstrated |
| tests/strategy/test_strategy1.py | Observed test names include test_strategy1_entry_contract and test_strategy1_missing_delta_fails_closed_for_futures_hedge | Tests must cover option hedge, cap 10, cancel/fill race, candidate fallback, ±5 release and DTE4 all-leg close | Legacy test assumption and coverage gap |

| Short step anchor / strike formula | core/strategy/track1_tail_defense.py | Current code maintains active_fence_type/strike and volatility-dependent fence distance; the inspected path does not implement target step-based short accumulation | User-confirmed rule: every +2.5pt crossing sells PUT at previous reference point - 7.5pt; every -2.5pt crossing sells CALL at previous reference point + 7.5pt; then reference point refreshes to the newly reached ATM. Examples: 100→102.5 PUT 92.5; 102.5→105 PUT 95; 105→107.5 PUT 97.5. | Spec intent resolved; implementation gap remains / no code change authorized |

## Difference inventory
1. Futures hedge symbols and resolver are legacy residue for future approved replacement.
2. Existing outer CALL/PUT and inner PUT fence does not establish the requested base long strangle plus accumulated option shorts.
3. Current trigger uses fence/momentum and delta-derived Futures quantity rather than distance-to-short-strike and 1:1 option quantity.
4. Current release 1.5 differs from requested ±5.0pt.
5. Current max_hedge_allowed=20 is not the combined short cap 10 excluding hedge buys.
6. DTE cutoff clears internal fence state before authoritative flat; target closes all S1 short/hedge/base legs and preserves state until flat.
7. Sale-time premium matching, liquidity tie-break and 30-minute cancel-confirm candidate descent are not demonstrated in current paths.
8. Runtime input lacks demonstrated target fields for sale-time premium, option candidate liquidity and cancel/late-fill state.
9. Current tests encode Futures-hedge behavior and do not prove the target scenarios. The current strategy code does not implement the target step-based short accumulation, so last-short-reference vs per-step reference cannot be inferred.
10. No evidence shows the current resolver routes target S1 option grouped plans.
11. Existing code/tests/PASS are not approval of the new intent.
12. The requested month-gap idle period (about 3–4 days after DTE4 flat) is a target behavior not demonstrated in current runtime.
13. new_short_stop_dte=7 is removed from the target config; any current DTE7 gate would be legacy/deprecated, not retained.
14. Premium-price matching is sale-time option premium vs current candidate option premium; strike distance is not a substitute.

Exact expiry YYYYMMDD and authoritative multiplier remain required. Mini Options are not introduced. Retired No.1168 BUY 2 is not reused. No tests were run. new_short_stop_dte=7 is retired per user confirmation on 2026-10-12; hedge trigger tuning candidates include 2.5pt and 5.0pt only as unfinalized REAL_VTS comparison values.

No.1046 evidence boundary: this is a static code-intent comparison only, not a test or runtime verification result.

## User-confirmed S1 correction — 2026-10-13
- U28: RESOLVED at the specification level.
- Strike uses the previous reference point, not the newly reached/current ATM: upward crossing → SELL PUT at previous_reference_point - short_offset_pt; downward crossing → SELL CALL at previous_reference_point + short_offset_pt.
- Refresh the reference point to the newly reached ATM after each crossing. For 2.5pt steps and 7.5pt offset: 100→102.5 PUT 92.5; 102.5→105 PUT 95; 105→107.5 PUT 97.5; downward moves are symmetric CALLs.
- Existing code does not implement this target behavior. This is a document-only correction; no code/tests/Git/live-order action was performed.
