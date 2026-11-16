# Q25 A8 Q3 S2 zero-fill cancel → group-flat validation — 2026-11-16

## Scope and policy
- Isolated worktree: `Q25_A8_Q1`, branch `work/q25-a8-q1`.
- Mandatory references checked: Notion No.1534, No.1535, No.1538, No.1554, No.1557.
- No.1534 inventory/reuse-first rule applied. Missing evidence was not treated as an immediate blocker; original lineage and accepted validation evidence were checked first.
- No.1535/1538 and No.1554 permit provenance-preserving synthetic/complementary inputs for validation-only software/runtime tests. Synthetic identity/value is not promoted to actual KIS identity, observed market data, account/broker fact, Production or Live.
- No real-account/KIS/Live/REAL_VTS/order API calls; no collector restart or new data collection.

## Integrated zero-fill cancel → group-flat scenario
- Added an integrated test using `ValidationOnlyU16RuntimeCoordinator` + `ValidationOnlyU16VirtualBridgePorts` + the virtual multi-leg bridge fixture.
- Four-leg group: `inner_put`, `inner_call`, `outer_put` had confirmed virtual fills; `outer_call` ended `CANCELLED` with zero fill.
- U16 zero-fill leg had zero own position while the other three legs retained confirmed group exposure. At the fixed T0+120s deadline, U16 selected group flatten, not repair.
- Group flatten closed every confirmed open leg using the authoritative stored plan; the test reconciled terminal close reports, no pending orders, no residual lots, and zero virtual account quantity for all four identities.
- Track2 strategy exit state reset only after `TRAP_CLOSE` reported complete and flat.
- This is an in-memory deterministic validation fixture with explicit `SYNTHETIC_CONTRACT:S2:` identities. It validates software lifecycle composition; it is not a market replay or evidence of real fillability.

## Validation
- Focused Track2 suite: `py -m pytest -p no:cacheprovider -q <all tests/*track2*.py>` — **268 passed**.
- Targeted zero-fill / U16 / sequential progression subset — **90 passed**.
- `py -m compileall -q` on changed U16 production/test modules — PASS.
- `git diff --check` — PASS.
- Accepted Runtime v2 manifest SHA-256 unchanged: `7657C90F13A81A7F98A8CCD075A259C8EC9795477A2A0541366094CD87E0360F`.
- Existing market-calibrated sidecar manifest SHA-256 unchanged: `13580E010C34C74A1787BFFB6B6B72ADEBDC4964F848937C0894BFA0FD4918B7`.
- Fast/Detailed replay parity for this zero-fill group-flat scenario is **not yet verified**. This fixture test alone does not establish replay-mode parity.

## Git and remaining Q3 work
- Only the U16-related source/test files and this report are in scope for the Q3 commit. Existing U19/U21 dirty files and unrelated untracked reports remain untouched.
- S2 remains `PSB_UNVERIFIED`.
- Remaining Q3 evidence: zero-fill scenario Fast/Detailed replay parity; group-close Fast/Detailed replay parity.
- Q4 not started.
