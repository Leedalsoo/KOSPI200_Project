# Q25 A7 C3 — Original dirty working-folder read-only classification
Date: 2026-11-12

## Verdict

C3 classification completed. This was a read-only inventory of the original working folder. No file was edited, deleted, renamed, staged, stashed, reset, checked out, or committed in the original folder.

## Protected baseline

- Original path: `C:\Users\white\Desktop\MovingProject\KOSPI200_Project`
- Branch: `cleanup/p2-quarantine-20261026`
- HEAD before and after: `b060fa57d3801e8227e88c8e54df8d2f9ffe7407`
- Git porcelain status entries: 224 before and after (23 tracked modified, 201 untracked entries)
- `git ls-files --others --exclude-standard`: 311 untracked files. Git status collapses some untracked directories, so this expanded file count is not additive to the 224 status entries.
- No index/staging changes were made.

## Classification summary

| Category | Git status entries / expanded files | Classification |
| --- | ---: | --- |
| Tracked source changes | 21 modified files | Application composition/runtime (7), strategy/core (2), environments/virtual and high-speed (9), KIS infrastructure (1), ingestion script (1), replay verification (1). Preserve as user working changes; require later diff-by-diff ownership review. |
| Tracked Graphify changes | 2 modified files | Generated graph report and graph JSON; derived artifacts, not source-of-truth code. |
| Verification assets | 141 untracked status paths | 83 evidence items, 48 fix/patch scripts, 4 baseline snapshots, 3 Graphify artifacts, 3 other verification files. |
| Reports and run artifacts | 80 untracked files | 31 text reports, 29 run logs/status markers, 10 structured evidence files, 6 runners/scripts, 4 R4 backups. |
| Caddy MCP server | 41 untracked files | Server implementation/tests, launch scripts, manifests, docs/skills, config and historical backups. Contains OAuth/tunnel client-state files; treat as sensitive and do not commit or publish without dedicated secret review. File contents were not printed. |
| Nested worktrees | 4 untracked directory entries | Four independent Git worktrees. Three clean; one has 1 local status item and one has 6. Preserve each worktree and its own HEAD/state; no cleanup or consolidation performed. |
| Config and scenario data | 7 untracked paths | Validation-only scenario JSON/hash files and generated graph metadata. |
| Other generated/technical docs | Remaining untracked paths | Graphify outputs across project subdirectories and one Strategy 9 specification draft. Preserve pending ownership review. |

## Tracked source changes (23 total)

- `application/`: bootstrap, automated runtime factory/loop, market calendar hub, standard runtime input provider, Track9 analytics provider, virtual multi-leg execution.
- `core/`: standard strategy registry, Track7 volatility-skew strategy.
- `environments/`: synthetic runtime sources, validation-only calendar, virtual replay, VSSF paper account/PnL/position manager, virtual broker/execution adapters.
- `infrastructure/`: KIS REST observation collector.
- `scripts/`: KIS VTS WebSocket canonical ingestion.
- `verification/`: current strategy replay.
- `graphify-out/`: GRAPH_REPORT.md and graph.json.

Aggregate tracked diff: 1,516 insertions / 757 deletions. No source changes were interpreted as safe to discard or automatically migrate.

## Nested worktree inventory

| Worktree | Branch | HEAD | Own status entries |
| --- | --- | --- | ---: |
| `Q25_A5_S01d1e_clean_20261108` | `q25-a5-s11b-s8-retry-20261108` | `4e3fd26912c7d16e89e57921558ce10ab5ad45f1` | 0 |
| `Q25_A5_S15b_NEXT_20261109` | `q25-a5-s15b-observed-alignment-20261109` | `22b7449f5c597816365e39e90162f99b4f3f053a` | 1 |
| `Q25_A5_S15b_OPTION_20261108` | `q25-a5-s15b-option-20261108` | `b5902bfd841ea42448954ff2c0f7b13b68ad7335` | 0 |
| `Q25_S5_POLICY_20261109` | `q25-a5-s5-policy-20261109` | `4bd9d67c24ccd4c450e735031b60809b6a6c4f1a` | 6 |

## Sensitive-data handling

Five Caddy paths are named as OAuth client/tunnel state or backups. Only paths and file sizes were inspected; no file content or token value was displayed. They are classified as restricted/sensitive pending local secret review. No credential scan was run against file contents in the original folder.

## Decision / next handling

- Preserve all 224 original status entries exactly as found.
- Do not delete backups, logs, evidence, nested worktrees, or Graphify outputs in this classification stage.
- Do not merge the original working-folder changes into the integration branch yet.
- C4/C5 and any cleanup, selective migration, or synchronization require their own approved stage.

## Verification

- Original HEAD unchanged: `b060fa57d3801e8227e88c8e54df8d2f9ffe7407`.
- Original status count unchanged: 224.
- Original branch unchanged: `cleanup/p2-quarantine-20261026`.
- Integration worktree remains separate; this report is stored there.
