# Q25 A8 T30 — Graphify Dirty Output Integrity and Preservation Review

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: read-only integrity review of the three pre-existing dirty files, Graphify graph/report consistency, and watcher dependency evidence. No backup, move, regeneration, staging or deletion performed.

## Mandatory reconciliation

- No.1534: retain generated artifacts separately from source data; preserve existing Raw, Canonical, accepted partitions and manifests.
- No.1534 also requires distinguishing generated/derived evidence from original observations and using existing evidence before any rebuild.
- AGENTS.md: protect dirty user files; do not include Graphify output in a commit without review; scheduler/process changes require approval.
- T27/T28 records: existing dirty Graphify outputs are protected; watcher must refuse to overwrite them.

## 1. Runtime invariant checker

File: `application/composition/validation_only_runtime_invariant_checker.py`

- Previously reviewed in T27: diff is EOF newline only, no semantic code changes.
- Focused test: 17 passed.
- No further modification or staging.

## 2. Graphify output diff

Files:
- `graphify-out/graph.json`
- `graphify-out/GRAPH_REPORT.md`

Current generated graph:
- Graphify 0.9.91.
- `built_at_commit=574c9c428a3b5ee1db9088af76825fed4e9959d5`.
- 8,987 nodes / 26,570 links / 426 communities / 1,160 corpus files.
- Baseline committed graph: 7,745 nodes / 21,867 links / 389 communities / 1,025 corpus files.
- Node delta: +1,349 / -107; link delta: +4,834 / -131.
- All 8,987 node IDs unique; 0 duplicate IDs.
- 0 dangling links among 26,570 links.
- 0 node source_file references missing from the current worktree.
- Node origins: 8,755 AST, 174 semantic, 58 without an explicit origin field.
- Node types: 7,113 code, 824 rationale, 958 document, 92 concept.
- Manifest contains 1,163 entries; report has 0 Unicode replacement characters.
- Report corpus size: approximately 1,917,552 words versus approximately 939,204 in the committed baseline.

Interpretation:
- The dirty graph is not merely a timestamp update: it contains a materially expanded current R10 graph with valid node identity, link endpoints and source-file references.
- It also removes 107 prior nodes and changes communities/labels; these generated changes should remain reviewable as a coherent snapshot.
- Graph metadata is 25 commits behind current R10 HEAD, so it is structurally consistent but not current to the latest branch.
- The report is a generated navigation summary, not an authoritative code/test status report.

## 3. Graphify runtime dependency

- `graphify.exe --version` works and reports 0.9.91.
- The active `py` interpreter does not have the `watchdog` Python package installed.
- Historical watcher log shows an earlier `watchdog not installed` startup failure, followed by later successful watch-mode startup.
- The Graphify executable may use a separate bundled/managed runtime; this audit did not establish that runtime''s dependency state.
- No watcher was launched to test this, and no dependency was installed.

## 4. Preservation decision

- Keep the two Graphify files and checker in their current dirty state; do not stage, commit, move, overwrite or delete them.
- The new R10 watcher guard correctly refuses to start while either Graphify output file is dirty (exit 23).
- A non-destructive backup/versioning plan can be prepared, but creating a backup copy or accepting the current generated graph into Git would alter user-managed artifacts and needs explicit approval.
- No original data or Canonical/accepted partition was involved in the Graphify diff.

## 5. Validation and Git

- Read-only graph integrity checks: PASS (unique IDs, link endpoints, source_file references).
- `git diff --check`: PASS.
- T30 is a report-only change; commit and push are recorded in the branch history and Notion No.1581.
- Existing three dirty files remain unchanged and unstaged.
- No changes to Raw/REST/WS/Canonical/accepted/manifest, .env, credentials, scheduled task or running processes.

## Next step

T31: prepare a reversible backup/versioning proposal for the two Graphify outputs (including file hashes, baseline commit, current generated commit and restore procedure) without copying or moving files yet. After presenting the proposal, request approval before any backup, Git staging/commit, watcher activation or scheduled-task change.
