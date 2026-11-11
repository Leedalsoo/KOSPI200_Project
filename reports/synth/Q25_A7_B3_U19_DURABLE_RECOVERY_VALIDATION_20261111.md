# Q25 A7 B3 — U19 restart recovery validation-only implementation

Date: 2026-11-11
Status: local implementation and validation complete; local commit only.

## Policy basis

- Notion No.1497 selected broker/exchange-held positions as the primary position basis; persisted execution ledger is secondary evidence.
- Account query authority and real account API access were not granted.
- Ledger mismatch adjustment, restart continuation, pending-order/late-fill handling and durable schema were not previously specified. This implementation does not invent automatic correction or continuation policy.

## Implementation

- core/oms/track2_u19_recovery.py
  - Validation-only broker position and execution-ledger snapshot contracts.
  - Broker positions are primary; ledger positions must match exactly before recovery gate passes.
  - Missing/unverified snapshots, different capture instants, duplicate/conflicting execution IDs, pending/unknown orders, invalid quantities and position mismatches fail closed.
  - Empty broker positions alone do not establish flat; both broker and ledger must confirm empty.
  - Matching duplicate execution IDs with identical fingerprints are idempotent; conflicting fingerprints block.
  - No automatic quantity adjustment, flat assumption, entry enablement or order submission.
- environments/virtual/position/track2_u19_recovery_store.py
  - SQLite schema version 1, append-only checkpoint table, immutable update/delete triggers, canonical JSON SHA-256 and read-time integrity check.
  - Persists both broker and ledger position views, snapshot IDs/hashes, execution IDs/fingerprints and pending-order IDs for restart audit/dedup recovery.
- application/composition/track2_u19_recovery.py
  - Validation-only coordinator consumes injected snapshots and persists the decision.
  - No KIS/Live/REAL_VTS/account adapter or automatic Runtime restore is connected.
- Group PnL MID mark and terminal group-close wiring already integrated by S33/A2 remains unchanged; B3 reran its targeted Runtime tests.

## Conservative boundaries / unresolved policy

- Snapshot as_of instants must match exactly. No tolerance window is inferred.
- Broker/ledger mismatch remains POSITION_LEDGER_MISMATCH; no auto-adjust, resume or flat classification.
- Pending/unknown order IDs block recovery until late-fill reconciliation is supplied.
- Only VALIDATION_ONLY:* injected snapshot sources are accepted by this coordinator.
- runtime_restore_performed=false, new_entry_enabled=false, order_submission_enabled=false for all decisions.
- Actual broker account-position retrieval, production persistence wiring, automatic Runtime restoration and operational restart policy remain unapproved/out of scope.

## Verification

- 12 S2-focused test files: 186 passed.
- Python compileall: PASS.
- git diff --check: PASS.
- Secret-pattern scan: no matches.
- Graphify AST update: completed.
- Existing Graphify warnings remain: application/composition/virtual_composition_root.py line 54 syntax extraction warning; 29 files yielded no symbols. No new warning from the three added Python modules.
- No Live, REAL_VTS, real-account, order, cancel, correction, balance or external API calls.

## Git and preservation

- Worktree: C:\Users\white\AppData\Local\Temp\Q25_S2_INTEGRATE_20261111
- Branch: integrate/q25-s2-20261111
- Start HEAD: 3932d3757803696b7901302356acef49e3dc05c1
- B3 is committed locally only; A7 B3 does not specify a push.
- Original project folder HEAD b060fa57d3801e8227e88c8e54df8d2f9ffe7407 and its 224 dirty/untracked items remain unchanged.
- Remote cleanup/p2-quarantine-20261026 remains at B1 SHA 5ab5f3b224e28a433b324943ad383480bf181d5d.

## Next

- A7 next stage: B4 — natural-signal Runtime E2E + Fast/Detailed Replay parity and final S2 verdict.
- X+1 (build_standard_strategy_registry(strategy_ids=...) signature mismatch) must be resolved before Runtime execution.
- S2 overall remains PSB_UNVERIFIED; this validation-only recovery gate is not a production restart/recovery readiness claim.
