# Q25 A8 T27 — Pre-existing Dirty Runtime Checker and Graphify Artifact Review

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: read-only comparison of the remaining pre-existing dirty files against the committed R10 baseline and No.1534 preservation rules.

## Mandatory decision reconciliation

- No.1534 requires preserving original data and existing project artifacts, distinguishing source data from derived/generated artifacts, and avoiding destructive replacement before source/decision reconciliation.
- No.1535/No.1538 require provenance and clear distinction between observed and generated evidence.
- This review did not modify, stage, regenerate or delete any of the pre-existing dirty files.

## Findings

### 1. Runtime invariant checker

File: `application/composition/validation_only_runtime_invariant_checker.py`

- Git diff contains only the final newline at EOF; no Python logic, imports, signatures, conditions or invariant rules differ from the committed baseline.
- Focused checker suite: **17 passed, 0 failed**.
- `git diff --ignore-space-at-eol` shows no semantic change.
- The file remains modified in the worktree and was not staged or committed.

### 2. Graphify outputs

Files:
- `graphify-out/GRAPH_REPORT.md`
- `graphify-out/graph.json`

Working output compared with committed baseline:
- Graph report corpus: 1,025 → 1,160 files.
- Graph nodes: 7,745 → 8,987.
- Graph links: 21,867 → 26,570.
- Graph communities: 389 → 426.
- Graphify version remains 0.9.91.

Freshness:
- Current generated `built_at_commit`: `574c9c428a3b5ee1db9088af76825fed4e9959d5`.
- Current R10 HEAD at review time: `b93d66c9c83a9b3bbcd97912fc75aba60a114d68`.
- The graph''s source commit is **24 commits behind** current R10 HEAD. Therefore these outputs are newer/larger than the committed baseline but stale relative to the current branch.
- No Graphify regeneration was run because it would overwrite pre-existing user-generated output files. The report''s unusual separator glyphs were also left untouched.

### 3. Worktree and Git safety

- No staged changes existed before this report.
- Three pre-existing dirty files remain preserved and excluded from staging:
  - `application/composition/validation_only_runtime_invariant_checker.py`
  - `graphify-out/GRAPH_REPORT.md`
  - `graphify-out/graph.json`
- `git diff --check`: PASS.
- Project200 remote HEAD unchanged.
- No Raw/REST/WS/Canonical/accepted/manifest/synthetic source data, .env or credentials changed.

## Conclusion

- The invariant checker difference is formatting-only (EOF newline), with its focused tests passing.
- Graphify outputs contain expanded graph data but were generated from a commit 24 commits behind current R10 HEAD.
- No destructive cleanup, regeneration, staging or commit of those pre-existing files was performed.

## Next step

T28: inspect the Graphify watcher/auto-regeneration configuration and determine why the graph remains 24 commits behind. First inspect scheduled tasks/processes/configuration read-only. Do not run graphify update or overwrite generated outputs until the user explicitly approves regeneration.
