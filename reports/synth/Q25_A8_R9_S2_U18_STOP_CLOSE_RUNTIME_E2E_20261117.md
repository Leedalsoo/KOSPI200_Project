# Q25 A8 R9 — S2 U18 Stop-Close Runtime E2E (2026-11-17)

## Scope

- Revalidated the real `Track2AsymmetricTrap` strategy through the current shared Virtual Runtime path.
- Scope is the first four-leg entry followed by the U18 stop-close lifecycle. This is validation-only evidence, not an S2 operating-policy or Production approval.
- No production strategy, Risk, OMS, broker, KIS API, collector, scheduler, or account configuration was changed.

## Decision and source reconciliation

- Mandatory No.1534 reuse-first inventory rule applied: compare confirmed Notion decisions and existing Accepted/Raw/Canonical/manifest lineage before treating a discrepancy as missing data; use deterministic provenance-preserving validation inputs where needed.
- No.1538 market-calibrated S2 quote provenance and No.1554 synthetic identity boundary applied.
- No.1539 absolute-net-premium denominator decision retained. No.1540 trailing-path evidence remains a separate scenario; this task does not merge it with the stop-path threshold.
- No.1549 threshold scenarios remain distinct. The `-0.40` stop threshold used here is only the dedicated exit-path test fixture; it does not replace the separate `-0.50` baseline or `-0.90` trailing-path test.
- No.1559 S2 verdict and No.1566 shared-runtime coverage record remain the current status references.

## Reused input inventory and hashes

All source files below were copied from the preserved Q25_A8_P2 validation workspace into the isolated R9 worktree and marked read-only. Source files were not modified.

| Input | SHA-256 |
|---|---|
| Accepted Runtime v2 manifest | `7657c90f13a81a7f98a8ccd075a259c8ec9795477a2a0541366094cd87e0360f` |
| Accepted partition 2026-10-12 | `c360b12e4c55551542490e73693ca59d42c3eb3135496d310cee7ee9fead62b5` |
| Accepted partition 2026-10-13 | `331c01e819e9ddd4d0c39e98bf0c9d43b9a82e575743c0c34b74e8178f494cf5` |
| Source four-leg sidecar manifest | `13580e010c34c74a1787bffb6b6b72adebdc4964f848937c0894bfa0fd4918b7` |
| Source four-leg quote JSONL (84 rows) | `466c796c536d48a91fd548e6c61c597da4bde558bd56a079cc8956a9f882786e` |
| Candidate inputs | `d2d96b35d0402c1bdf8a6b07e771e9bdc593772985610dc68d3fd74f615b5a32` |

Accepted Runtime v2 contains 2,072 rows across the two listed partitions. The sidecar contains 21 candidate timestamps and 84 synchronized four-leg quote rows. These remain synthetic validation quotes, not observed simultaneous market quotes or listed KIS contract identities.

## Profile-bound stop scenario

- Source market-calibration profile: `S2-MARKET-CALIBRATED-SYNTHETIC-SCENARIO-v2`, SHA-256 `c0607c405abba4d2500bd8d5572db0270a9bdc61ab7e4943b1fd3c73d6181b18`.
- Target stop-path test profile: `S2-MARKET-CALIBRATED-EXIT-PATH-TEST-v3`, SHA-256 `6c17b94112d12ba01361bfa1d6cdfbfe810b4f08a20033a4fbfa83905b28d726`.
- The profiles have identical U21 quote policy and market-calibration settings. The only allowed profile differences are the profile ID, U18 test policy, exit-path test metadata, and limitations.
- A new profile-bound sidecar was created. Each quote row preserves the original profile ID/hash in `source_scenario_profile_*`; only profile-binding metadata changed. Bid, ask, last, quantity, timestamp, contract fields, source anchors, and market-calibration values were byte-value-equivalent to the source rows.
- Derived quote JSONL SHA-256: `03decb8449543fdf9027ddf5ee2013b78307386f192365b1f662c10c7208c4dc`.
- Derived manifest SHA-256: `b22628009c5ed2a06b5fa5cc4fdf28d29e7609b98997add96a2894f0be898546`.
- The new `verification/track2_quote_profile_binding.py` helper enforces matching U21 and market calibration, validation-only profile flags, source hashes, and quote-value preservation. It refuses to overwrite an existing output directory.

## Runtime results

### Bounded first-group stop-close scenario

Run ID: `Q25-A8-R9-S2-U18-STOP-86-20261117`

| Metric | Result |
|---|---:|
| Market events | 86 (intentional event cap) |
| Strategy signals | 2 (entry + U18 stop-close) |
| Approved | 2 |
| Routed / filled | 8 / 8 |
| Rejected | 0 |
| Open PositionLots after close | 0 |
| Account positions after close | 0 |
| Initial net premium received | 1,987,500 |
| VSSF realized PnL | -1,575,000 |

The trace contains four `ASYMMETRIC_TRAP_NARROW` entry fills and four `TRAP_CLOSE` close fills. The group ended flat. `exhausted=false` is expected because this run deliberately stops at 86 events; it is not a full-stream exhaustion claim.

Trace SHA-256: `f91633627465e6499dc7ebcb0e894983f7790a525d9174ef3919a068f7779359`.

### Full 2,072-event replay

The same `-0.40` stop test profile was replayed across all 2,072 events. The first group entered and closed successfully; the strategy then emitted a second entry later in the stream. Final result: 3 signals, 12 fills, 0 rejects, 4 open lots, and 4 account positions. Therefore the first-group stop-close path passes, but the full replay is not flat at end because of the later re-entry. This is not reported as a whole-stream group-flat pass.

Full trace SHA-256: `e52c6b1421ebd6102bcae07b0e5633a93445918348e1ca99c4c0419dbd8f7c91`.

### Separate `-0.50` baseline profile

The original market-calibrated profile was also replayed without rebinding. It produced 2,072 events, one entry signal, four fills, and no stop-close. Its validation-only account net PnL was `-787,500`. This remains separate from the deliberately triggerable `-0.40` stop-path fixture.

Trace SHA-256: `332ae040891ac747d2e8497806f462d9e9f3f36c8d45570234464b9df2655f91`.

## Code and test changes

- Added `verification/track2_quote_profile_binding.py` for deterministic, provenance-preserving profile binding.
- Added `tests/verification/test_track2_quote_profile_binding.py`.
- Added `tests/verification/test_q25_a8_r9_s2_u18_stop_close_runtime_e2e.py` using the actual S2 strategy and shared Virtual Runtime.
- Added optional `--max-events` to `verification/run_track2_market_calibrated_runtime_replay.py` and covered the argument in its wrapper test.
- Focused S2 + shared Runtime regression: **75 passed in 5.91s**.
- `py_compile`: PASS.
- `git diff --check`: PASS.
- Graphify no-cluster extraction completed: 916 source files processed, 8,080 nodes, 24,834 edges. Its parser warned about `application/composition/virtual_composition_root.py` at line 54; Python `py_compile` for that file passed. Generated `graphify-out/graph.json` is local-only and intentionally excluded from the commit.

## Remaining boundaries

- S2 remains `PSB_UNVERIFIED`; the 12 operating risk limits remain null/fail-closed.
- `-0.40` is a validation-only stop trigger, not an approved operating stop-loss. U18 trailing-path behavior is not re-certified by this R9 run; No.1540 remains a separate historical validation record.
- This does not certify actual KIS contract identity, tradability, account mapping, real fees/taxes/slippage, margin, profitability, or Live readiness.
- No KIS Live, REAL_VTS, account, order, cancellation, or margin API was called. No new market-data collection was started.
- No Raw, Canonical, Accepted Runtime source, original sidecar, or `Project200` file was modified. No merge to `Project200` was performed.

## Git scope

Isolated branch: `work/q25-a8-r9-integrated-e2e-20261117`.

Only the three new validation/test files, the replay CLI and its wrapper test, and this report are intended for commit. Generated data, traces, and Graphify output remain local-only.