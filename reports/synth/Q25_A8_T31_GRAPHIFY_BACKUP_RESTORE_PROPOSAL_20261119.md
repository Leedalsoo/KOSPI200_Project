# Q25 A8 T31 — Graphify Output Backup and Restore Proposal (No Files Copied)

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Proposal only: no backup files copied, moved, staged, committed or restored.

## Scope and source decision

- No.1534 and AGENTS.md require preserving user-generated artifacts and not overwriting them without a verified recovery path.
- T30 verified graph structure integrity, but the two Graphify output files remain dirty and user-managed.
- T29''s R10 watcher script refuses to start while these files are dirty (exit 23).
- This proposal establishes a reversible path before any future watcher activation.

## Exact files to back up

| File | Current size | Current SHA-256 | Git baseline blob |
|---|---:|---|---|
| `graphify-out/graph.json` | 13,243,956 bytes | `15D802184162145CC639F89605E7933264E33FE8F616D5A71324C8B8D346AF95` | `e1f7afe28fdd34b9b550e9f4ee7bd02b3ec7c9cc` |
| `graphify-out/GRAPH_REPORT.md` | 112,031 bytes | `D9BD4C186B863A98F94B05266B10C3D47F806246B1DF44800DBC04414C89030E` | `b982fce6df43764d18420cf8fb108e0197e50600` |

Current generated graph metadata:
- Graphify version: 0.9.91.
- `built_at_commit=574c9c428a3b5ee1db9088af76825fed4e9959d5`.
- Current branch HEAD at proposal time: `24fca03d4f7e82801d1a17fda5b72de383e23fdd`.
- Generated graph source commit is 25 commits behind current branch HEAD.

## Proposed backup location

`%LOCALAPPDATA%\KOSPI200_Project\graphify-backups\Q25_A8_R10\2026-11-19\`

Proposed contents:
- exact byte-for-byte copies of `graph.json` and `GRAPH_REPORT.md`;
- `backup-manifest.json` with original absolute paths, branch, current HEAD, Graphify version, built_at_commit, UTC/KST capture time, byte sizes, SHA-256 values and baseline Git blob IDs.

No project Raw/REST/WS/Canonical/accepted/manifest data is included in this backup.

## Proposed verification and restore

1. Copy both files without changing the source files.
2. Recompute SHA-256 for each backup and require exact match with the values above.
3. Write the manifest only after both copies pass verification.
4. Before any future Graphify refresh, compare current files to the manifest; refuse on mismatch.
5. Restore only after explicit confirmation by copying the selected backup files back to the active R10 `graphify-out` paths and verifying the restored SHA-256 values.
6. Keep the backup until the user explicitly approves its removal.

## Watcher activation implications

- The current watcher guard refuses to run while the two output files have Git modifications.
- A verified backup makes future changes recoverable, but does not by itself make the current Git worktree clean.
- Before activation, either:
  - explicitly approve accepting the reviewed Graphify output snapshot into the R10 branch, or
  - approve a narrowly scoped guard update that permits the exact manifest-verified snapshot to be refreshed while preserving the backup.
- Registering/enabling the R10 scheduled task and allowing Graphify to rewrite generated outputs are separate operational approvals.
- The existing original Project200 task/script will remain unchanged.

## Preservation

- No copy, move, restore, overwrite, Graphify update/watch, scheduler change or process start was performed for T31.
- Existing dirty files remain unchanged:
  - `application/composition/validation_only_runtime_invariant_checker.py`
  - `graphify-out/GRAPH_REPORT.md`
  - `graphify-out/graph.json`
- Project200 remote branch, Raw/REST/WS/Canonical/accepted/manifest, .env and credentials unchanged.

## Approval requested

Approve creation of the two-file backup at the proposed LOCALAPPDATA location with SHA-256 verification and manifest, without modifying the source files. No watcher task will be registered or activated as part of that backup operation.
