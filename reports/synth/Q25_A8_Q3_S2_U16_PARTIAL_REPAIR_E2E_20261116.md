# Q3 S2 4-leg U16 partial-fill repair / U19 recovery E2E — 2026-11-16

## Scope and provenance
- Validation-only replay in isolated worktree `Q25_A8_Q1`, branch `work/q25-a8-q1`; source workspace unchanged.
- Existing accepted Runtime v2 and existing P2 market-calibrated four-leg sidecar reused. No raw/accepted source files overwritten.
- Runtime manifest SHA-256: `7657C90F13A81A7F98A8CCD075A259C8EC9795477A2A0541366094CD87E0360F`.
- Original sidecar manifest SHA-256: `13580E010C34C74A1787BFFB6B6B72ADEBDC4964F848937C0894BFA0FD4918B7`.
- Original sidecar quote SHA-256: `466C796C536D48A91FD548E6C61C597DA4BDE558BD56A079CC8956A9F882786E`.
- Validation-only profile override: U18 stop-loss `-0.50` → `-0.99` to prevent automatic exit during repair verification. No production approval; source profile unchanged.
- Derived profile SHA-256: `7441DCCB30D1FC337BD53054B38AADB8BB22095E2366D54D376FCB29FEB57EAF`.
- Derived quote sidecar SHA-256: `1952E7359CA25469821490BD6BE57180A31998D9090C9A9905C5B098C8170F05`.
- Derived sidecar manifest SHA-256: `C72E909EABEFACCE1A5C2004D39E8990150DEB7A805A72F1FDD9D313BFFED0414`.
- Quote values were not changed; only scenario profile SHA metadata was rebound in the derived validation-only copy. The derivation link to the original manifest is recorded.

## Integrated scenario result
- Run ID: `Q3-S2-U16-PARTIAL-REPAIR-E2E-RETRY4-20261116`.
- 86 replay events, one S2 signal; replay intentionally stopped at the lifecycle checkpoint (`exhausted=false`).
- Each of four legs had target quantity 3. `outer_call` original order filled 1 of 3, then became terminal CANCELLED with remaining order quantity 0.
- U16 repair submitted exactly the missing 2. Repair order terminal and position-reconciled.
- Final per-leg reconciliation: `inner_put`, `inner_call`, `outer_put`, `outer_call` each had cumulative execution fills 3, open-lot quantity 3, and virtual account quantity 3.
- Group complete; pending orders empty. Track2 strategy transitioned from entry-pending to active only after the repaired four-leg group completed.
- U16 repair state persisted to SQLite. U19 validation-only broker snapshot, execution-ledger snapshot, and expected four-leg manifest matched: `RESTORE_ALLOWED`.
- U16 state restored only after U19 authorization; post-restore state `REPAIR_COMPLETE`, action `NO_SUBMISSION`; no duplicate repair order. U19 `runtime_restore_performed=false`, `new_entry_enabled=false`, `order_submission_enabled=false`.

## Fast / Detailed parity
- Fast and Detailed replay semantic summary matched: 86 events, 1 signal, 1 approved, 4 routed, filled metric 10, rejected 0, net PnL `-2,362,500.0` (validation-only simulation only).
- Four-leg fill/lot/account reconciliation, U16 repair quantity 2, U19 `RESTORE_ALLOWED`, U16 `REPAIR_COMPLETE`, strategy active state, and no-duplicate-submission result matched.
- Detailed trace SHA-256, identical across three same-Run-ID runs: `037B75F88AB15CD6ED808DE4EF7E39019264A23B8AD1E314A6ED7E78F3E2B244`.

## Code and validation
- Repair orders now carry explicit `TRAP_REPAIR` purpose. The bridge permits this purpose to bypass entry sequencing only after validating the original stored four-leg plan, exact leg identity/side/role, terminal original partial order, exact missing quantity, no pending group orders, and fill-to-lot-to-account quantity reconciliation.
- Validation-only identity adapter resolves repair role against the exact manifest-bound synthetic sidecar rows, independent of the latest active market candidate.
- Track2 strategy activates the group after a `TRAP_REPAIR` callback only when `group_complete=true` and `position_flat=false`.
- Track2 test modules: 17 modules, 260 passed. `compileall` PASS. `git diff --check` PASS.
- Protected config hashes and original accepted Runtime/sidecar hashes unchanged.
- No Live/KIS/REAL_VTS/account/order API called. No collector restart or new market-data collection.
- Code remains uncommitted and unpushed; existing unrelated U19/U21 changes and untracked reports preserved.

## Q3 status
- U16 integrated partial-fill repair + U19 evidence-gated state recovery: validation-only PASS.
- Remaining: zero-fill cancel followed by group-flat integration and its Fast/Detailed parity; group-close Fast/Detailed parity. S2 remains `PSB_UNVERIFIED`; Q4 not started.
