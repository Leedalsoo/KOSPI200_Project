# Q25 A8 R9 S2 U18 Trailing Runtime E2E — 2026-11-17

## Scope and decision alignment

- Worktree: `C:\Users\white\Desktop\MovingProject\Q25_A8_R9`
- Branch: `work/q25-a8-r9-integrated-e2e-20261117`
- Base HEAD before this change: `b00a860f02c0f230a26ac929eecb5394d49f066d`
- Related decisions checked: No.1534, No.1538, No.1554, No.1540, No.1566.
- Scope: validation-only S2 U18 trailing exit through the shared Virtual Runtime. No production strategy policy or operational threshold was changed.

## Reuse-first source audit

No.1540 records a 23-candidate/92-row synthetic path, 120 market events, 8 fills, 0 rejects, profile SHA-256 `eada46f0f80fe0d44c4e0ad52e7b972a31ae2eca031a91bf103a3c63e9049d79`, and historical trace SHA-256 `5f063f6672795e0293603be2b5b13e88347901d2b57e679be3106ccca7e0c888`. The exact historical sidecar/report/trace files were not found in the current MovingProject worktrees checked (original, P1/P2/Q1/Q4, R1–R9, sync-validation, and other project worktrees); the No.1540 Notion record remains the historical reference. The R9 source sidecar was present and hash-verified at 21 candidates / 84 quote rows. Rather than declaring the path blocked, the existing source anchor and No.1540 timestamps/target ratios were reused to generate two missing four-leg snapshots deterministically in a temporary validation sidecar. This is a new reproducible revalidation, not a byte-identical rerun of the historical trace.

Accepted Runtime v2:
- Rows: 2,072
- Manifest SHA-256: `7657c90f13a81a7f98a8ccd075a259c8ec9795477a2a0541366094cd87e0360f`
- 20261012: 686 rows, SHA-256 `c360b12e4c55551542490e73693ca59d42c3eb3135496d310cee7ee9fead62b5`
- 20261013: 1,386 rows, SHA-256 `331c01e819e9ddd4d0c39e98bf0c9d43b9a82e575743c0c34b74e8178f494cf5`

Reused sidecar:
- Manifest SHA-256: `b22628009c5ed2a06b5fa5cc4fdf28d29e7609b98997add96a2894f0be898546`
- Quote JSONL SHA-256: `03decb8449543fdf9027ddf5ee2013b78307386f192365b1f662c10c7208c4dc`
- Candidate inputs SHA-256: `d2d96b35d0402c1bdf8a6b07e771e9bdc593772985610dc68d3fd74f615b5a32`
- Source profile: `S2-MARKET-CALIBRATED-EXIT-PATH-TEST-v3`, SHA-256 `6c17b94112d12ba01361bfa1d6cdfbfe810b4f08a20033a4fbfa83905b28d726`

All source files were read-only during generation and their hashes were rechecked unchanged by the E2E test.

## Synthetic supplement and provenance

New helper: `verification/track2_u18_trailing_scenario.py`

- Reused the 2026-10-12 09:26:00 four-leg source anchor.
- Added four-leg snapshots at 09:26:21 and 09:26:30, matching timestamps present in the accepted Runtime base stream.
- Final scenario: 23 candidates / 92 quote rows (21/84 reused + 2/8 generated).
- Peak snapshot: inner-long mid shift +2.00 points; outer-short mid shift -2.00 points.
- Pullback snapshot: inner-long mid shift +1.50 points; outer-short mid shift -1.50 points.
- Bid/ask spreads and displayed depth were preserved. All generated prices are synthetic; they are not observed KIS option quotes.
- Source anchor timestamp and generated quote timestamp are separately recorded. Source anchor maximum age is 854 seconds at peak and 863 seconds at pullback, below the 900-second calibration limit. No future anchor is used.
- Deterministic generation rule, source anchor quote hash, source observation, generated timestamp, phase, target ratio, and validation-only status are recorded in each generated candidate/quote and the sidecar manifest.

Generated temporary sidecar:
- Manifest SHA-256: `d8508c71f90aa3a39f53d882dfb23de214f3ea4259746044c832363fa8556688`
- Quote JSONL SHA-256: `16986aac07d09f2c27453bde4550df5a49e27470663fe4a10134939383a8cbb4`
- Candidate inputs SHA-256: `5dab229e72fe533ef99ddd026e4249ac5914f5cc51e427493d073fbec7bf607f`
- Source anchor four-leg quote digest: `ac01b13c4ba746d196ac841de8682524d178ed1d129af707dfd154c1f99e24fe`

The profile binder was extended to allow the validation-only `trailing_path_test` metadata field while retaining the existing restriction against unrelated market/quote policy changes.

Target profile:
- `S2-MARKET-CALIBRATED-TRAILING-PATH-TEST-v4`
- SHA-256: `eada46f0f80fe0d44c4e0ad52e7b972a31ae2eca031a91bf103a3c63e9049d79`
- U18 fixture: stop -0.90, trailing activation +0.40, pullback 0.25.
- `execution_enabled=false`, `order_submission_enabled=false`, `live_api_enabled=false`, `real_vts_api_enabled=false`.

Profile-bound sidecar:
- Manifest SHA-256: `a915ea2a6226389d303d84cc7b6f335b35b77781dccaa1a6b603034ae553fc50`
- Quote JSONL SHA-256: `167a9bd3e86acc94b3bc445df2927418281d629c6a2c152fdeadf644074ce64a`

## Shared Virtual Runtime result

Test: `tests/verification/test_q25_a8_r9_s2_u18_trailing_runtime_e2e.py`

- Replay cap: 120 base market events.
- 2 strategy signals / 2 approvals.
- Entry: 4 fills (`ASYMMETRIC_TRAP_NARROW`).
- Exit: 4 fills (`TRAP_CLOSE`).
- Total: 8 fills, 0 rejects.
- Peak at 09:26:21: net PnL ratio +58.2893%.
- Pullback at 09:26:30: net PnL ratio +33.1321%.
- Calculated peak-to-current retracement: 43.1592%, exceeding the validation-only 25% trigger.
- Runtime emitted `TRAP_GROUP_TRAILING_EXIT` and routed the four-leg close through the shared OMS/Router/Virtual execution path.
- Final open PositionLots: 0.
- Final VSSF virtual account positions: empty.
- Final realized/net PnL after the close path and modeled costs: approximately -KRW 75,000. This is an execution-path test result, not profitability evidence.

Detailed trace:
- Local file: `reports/synth/Q25_A8_R9_S2_U18_TRAILING_RUNTIME_E2E_20261117.jsonl`
- 146 trace records.
- SHA-256: `1f736057fee0d08834bf3a588a24e2b93c879c33161830f0d80155b6e080af23`
- The trace is retained locally as runtime evidence and is not included in the code commit.

## Validation

Combined focused regression:
- U18 exit policy and group-PnL mark tests
- U19 recovery and restart tests
- Shared StrategyHub Runtime E2E
- U18 stop-close and trailing-close Runtime E2E
- Quote profile binding and market-calibrated quote scenario tests
- Result: **92 passed in 8.56s**
- `py_compile`: PASS
- `git diff --check`: PASS

Graphify code-only update:
- Completed without LLM.
- 8,116 nodes / 24,944 edges.
- Graph output remains local and unstaged.
- Graphify reported a parser warning for `application/composition/virtual_composition_root.py` at line 54 (11 symbols extracted) and 29 code files with no symbols. This is recorded separately from pytest results. The flagged Python file also passed `py -m py_compile`; this is an extractor warning, not a confirmed Python syntax error.

## Limits and remaining gaps

- This proves the U18 trailing close route in the validation-only shared Virtual Runtime for this deterministic synthetic path.
- It does not prove actual KIS option quote behavior, actual contract identity, account balance/margin, real execution quality, strategy profitability, or Live/REAL_VTS readiness.
- The synthetic multiplier/contract identities remain scenario fixtures and are not authoritative account or broker facts.
- After the official KIS/real-account investment API is connected under separate approval, match official contract codes, option right, strike, exact expiry, multiplier, tick, tradability, quote source/time, order/replace/cancel/fill, fees/taxes, balance, margin, and account-risk fields against the entire codebase field by field. Until then, use only provenance-preserving synthetic criteria for validation.
- U18 stop/trailing operating thresholds remain unapproved. S2 remains `PSB_UNVERIFIED`.
- U19 Runtime restart test still covers a single open PositionLot checkpoint; complete four-leg restart reconciliation, real broker late-fill handling, and automatic Runtime restoration remain unverified.
- No Raw/Canonical/Accepted source data, production strategy configuration, credentials, Live/REAL_VTS/account/order API, collector, or scheduler was changed or invoked.
- No merge or push to canonical `Project200` or `master` was performed.
