# Q25 A8 Q3 S2 zero-fill cancel → group-flat Fast/Detailed parity — 2026-11-16

## Governing decisions and evidence policy
- Mandatory Notion No.1534 inventory/reuse decision was checked, together with No.1535 (existing collected + synthetic/complementary data accepted for project verification; preserve provenance; stop new collection) and No.1538 (market-calibrated synthetic four-leg sidecar methodology).
- A missing simultaneous four-leg quote snapshot was not treated as an immediate blocker. Existing accepted Runtime v2 and prior same-day KIS observations were reused; an additional validation-only snapshot was generated from prior same-day anchors. No future observations were used.
- Synthetic identities/prices remain validation-only. They are not KIS Master identity, observed simultaneous quotes, real account/broker facts, Production/Live or actual fillability evidence.

## Derived validation input
- Accepted Runtime v2 manifest SHA-256 unchanged: `7657C90F13A81A7F98A8CCD075A259C8EC9795477A2A0541366094CD87E0360F`.
- Derived profile: `data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r4_q3_zero_fill_20261116/synthetic_scenario_profile.q3_zero_fill_parity_validation_only_20261116.json`.
  - U18 stop-loss `-0.99` is a validation-only override to prevent automatic exit during this lifecycle scenario; it is not an approved operating threshold.
  - Profile SHA-256: `445E9F07AB0B6DB2CD9D06EAB6667460EA4F80CA0EE5938E874F1D8055E67134`.
- New market-calibrated sidecar r4: 22 candidates / 88 quote rows.
  - Manifest SHA-256: `C5F8BC82824BE8EBC45FE8A09275C5AB5BB9B204C54D50CA3A4E3088E03CC425`.
  - Quote JSONL SHA-256: `A22CDC05DFFCE13DC869DF51AF1B3F36E34E2F197ADFBB11359263BBD6632ABD`.
  - Added candidate `S2-CANDIDATE-022` at `2026-10-12T09:26:21+09:00`, based on accepted Runtime v2 observation `583371e6d310761baa998d4b`, underlying `1034.97`; maximum prior source-anchor age 854 seconds; cross-type IV fallback legs 0.
  - The four quotes are model-generated synchronized validation snapshots, not directly observed quotes.

## Replay composition correction
- `environments/high_speed/virtual_runtime_replay.py` now constructs the validation-only U16 quote/retry policy and conservative executable-side tick-rounded repair-price resolver from the already validated S2 scenario profile, and passes both to `attach_standard_automated_loop`.
- U16 retry schedule consistency is checked (30/60/90 seconds, three retries, 120-second deadline); BUY uses ASK ceiling and SELL uses BID floor. Inconsistent or unresolved profile input fails closed.
- Added `tests/environments/high_speed/test_track2_u16_replay_composition.py` for resolved profile wiring, side/tick rounding and invalid retry schedule rejection.

## Integrated zero-fill cancel → group-flat Fast/Detailed replay
- Deterministic validation fault injection returned a terminal `CANCELLED`, zero-fill broker report for the initial `outer_call` entry order. No real broker/API order was sent.
- U16 state was restored to the retry-exhausted lifecycle checkpoint (`first_repair_submitted_at=09:24:21`, three additional retries used, prior repair terminal/reconciled). At the next accepted market event (`09:26:21`), the r4 sidecar supplied a fresh synchronized validation snapshot. This scenario verifies the deadline/flatten branch; it does not claim that three retry orders were separately replayed in this run.
- Three entry legs filled; `outer_call` cancelled with fill 0. U16 submitted `TRAP_CLOSE` for all three open legs; all three close reports FILLED.
- Final state in both modes: U16 flatten terminal/reconciled; open lots 0; pending orders 0; synthetic account positions all zero; group-flat confirmed.

## Fast / Detailed semantic parity
| Metric | Fast | Detailed |
| --- | ---: | ---: |
| Market events | 2,072 | 2,072 |
| Signals / approved | 1 / 1 | 1 / 1 |
| Entry routed | 4 | 4 |
| Entry filled / zero-fill cancel | 3 / 1 | 3 / 1 |
| Close reports filled | 3 | 3 |
| Rejected | 0 | 0 |
| Realized PnL (validation-only) | -1,137,500.0 | -1,137,500.0 |
| Unrealized PnL | 0.0 | 0.0 |
| Open lots / pending orders | 0 / 0 | 0 / 0 |
| Group-flat / U16 flatten reconciled | PASS / PASS | PASS / PASS |

- Semantic parity: PASS across lifecycle reports, fill quantities, group/account flat state, pending orders, U16 terminal state and PnL.
- Detailed trace: `reports/synth/Q25_A8_Q3_ZERO_FILL_AUTO_DETAILED_20261116.jsonl`; 2,094 trace events, 7 order commands, 7 execution reports (3 entry FILLED + 1 zero-fill CANCELLED + 3 close FILLED), observer connected, 6 fill records, zero trace-write errors.
- Detailed trace SHA-256: `59A6EF144EA91C8DCA877D1407CB154C79F42C3F230311C775EE0A3E5CE530E0`.

## Validation and safety
- Track2 focused suite: **271 passed**.
- Replay U16 composition tests: 3 passed.
- `py -m compileall` PASS; `git diff --check` PASS.
- Accepted Runtime v2 source manifest unchanged. Original r3 sidecar and accepted data were not overwritten; r4 is a separate derived sidecar.
- No KIS Live / REAL_VTS / real-account / broker order API calls; no collector restart or new collection.
- Existing unrelated U19/U21 dirty changes and untracked reports were preserved.
- Code changes are local and not committed/pushed in this task.

## Q3 status
- Zero-fill cancel → group-flat integrated replay and Fast/Detailed parity: PASS (validation-only).
- Remaining Q3 work: group-close Fast/Detailed parity.
- S2 remains `PSB_UNVERIFIED` until all required Q3 scenarios/parity are complete. Q4 not started.
