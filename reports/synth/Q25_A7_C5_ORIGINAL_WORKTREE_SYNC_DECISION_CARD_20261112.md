# Q25 A7 C5 — Original working-folder synchronization decision card
Date: 2026-11-12

## Verdict and boundary

C5 proposal completed. This stage is a decision card only. **No synchronization, copy-back, merge, cleanup, staging, or mutation of the original working folder is authorized or performed.** A separate explicit user decision is required before any selected migration work begins.

## Protected source baseline (rechecked)

- Original folder: `C:\Users\white\Desktop\MovingProject\KOSPI200_Project`
- Branch: `cleanup/p2-quarantine-20261026`
- HEAD: `b060fa57d3801e8227e88c8e54df8d2f9ffe7407`
- Git porcelain status: 224 entries (23 tracked modified; 201 untracked entries)
- Expanded untracked file inventory: 311 files (Git collapses some untracked directories in status; this is not additive to 224).
- No original file was edited, moved, overwritten, renamed, deleted, staged, stashed, reset, checked out, committed, or pushed during C5.

## Inventory and handling classes

Counts below follow the C3 read-only inventory; nested/expanded file counts are not additive to the 224 Git status entries.

| Class | Inventory | Proposed handling |
| --- | --- | --- |
| Tracked source modifications | 21 files across application/runtime, core/strategy, virtual/high-speed, KIS infrastructure, ingestion and replay | Candidate for per-file diff review and selective migration only. No bulk copy. |
| Tracked Graphify artifacts | 2 modified files | Regenerate after accepted source migration; do not migrate as authoritative source. |
| Verification | 141 status paths; includes 83 evidence items, 48 patch/fix scripts, 4 baseline snapshots and Graphify/other artifacts | Split executable test/fixture assets from generated results, logs and one-off patch scripts. Review each group. |
| Reports and run artifacts | 80 files; includes reports, logs/status, structured evidence, runners and R4 backups | Preserve as an evidence archive; selectively migrate durable Markdown/JSON reports after provenance and secret review. |
| Caddy MCP server | 41 files | Separate security review only. Exclude OAuth client state, tunnel state, tokens, logs, credentials and backups from Git migration. |
| Nested worktrees | 4 independent worktrees; two contain local changes (1 and 6 status entries) | Preserve each worktree and HEAD. Never flatten/copy into the main repo. |
| Validation-only config/scenario | 7 paths in C3 classification | Candidate only after schema, provenance, hash and `runtime_eligible=false` checks. |
| Graphify and technical docs | generated graph outputs across subfolders; one Strategy 9 draft | Regenerate graph outputs; retain draft separately until spec approval. |

Tracked source modifications include `infrastructure/kis/kis_rest_market_observation_collector.py` and `scripts/ingest_kis_vts_websocket_canonical.py`. These touch market-data collection/ingestion and must remain excluded from automatic migration pending dedicated source, safety, and regression review. Runtime/strategy diffs likewise require per-file ownership and test mapping.

## Recommended decision

**Option A — phased selective migration (recommended).**

1. Freeze and preserve the original folder as-is; capture a read-only manifest (path, status, size, timestamp, SHA-256) before each future migration batch.
2. Review the 21 tracked source diffs individually. Classify each as accept, defer, or reject; identify owner, dependencies, tests and rollback point. No whole-folder copy.
3. Migrate only explicitly accepted source files into a new isolated worktree/branch. Keep KIS collector and WS ingestion files in a separate approval batch.
4. Add only mapped tests/fixtures and validation-only scenario assets. Exclude runtime results, caches, logs and one-off patch scripts from the code commit.
5. Restore durable docs/reports as a separate evidence-only batch. Regenerate Graphify from the resulting tree.
6. Handle Caddy MCP and each nested worktree as independent projects with their own security/state review.
7. Run focused tests, full clean-checkout pytest, diff/secret checks, and original-folder before/after HEAD/status/hash comparison before any push.

## User decision card

Choose one path for a future, separately approved stage:

- **A — Phased selective migration (recommended):** review and migrate accepted source/test/config/docs groups in separate batches; keep Caddy and nested worktrees isolated.
- **B — Evidence archive only:** preserve a read-only archive/manifest of the 224-entry state, with sensitive Caddy state excluded; do not merge source changes.
- **C — Keep frozen:** leave all 224 entries in the original folder and continue development only from the integrated branch.

Choosing A/B/C here does not authorize deletion, overwriting, staging, commit, or push. After the choice, the exact file list and batch boundaries must be presented for approval before execution.

## Safety verification

- Original branch/HEAD/status remain `cleanup/p2-quarantine-20261026` / `b060fa57d3801e8227e88c8e54df8d2f9ffe7407` / 224.
- No `.env`, OAuth/tunnel client-state contents, production RiskConfig, scheduler, collector, or original files were changed.
- No KIS/Live/REAL_VTS/account/order API was called; no order was submitted.
- No remote push is part of C5.

## C5 completion

C5 is complete as a proposal/decision-card stage only. Actual synchronization remains blocked pending the user's A/B/C decision and a separate execution approval.
