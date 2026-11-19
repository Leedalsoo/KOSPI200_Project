# Q25 A8 T28 — Graphify Watcher / Auto-Regeneration Read-Only Audit

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: inspect the Windows scheduled task, watcher scripts, Graphify CLI, logs, update marker and active processes. No task/script/process/configuration changes.

## Decision reconciliation

- No.1534: preserve the original working folder, raw sources, Canonical/accepted data and user-generated artifacts. Reuse and inspect existing evidence before any regeneration.
- No.1534 explicitly distinguishes original Raw, Canonical and generated artifacts; Graphify output is generated evidence and must not overwrite original data.
- Current AGENTS.md: operating settings, scheduler and process changes require separate approval; Graphify output must not be included in commits without review.
- T27''s three pre-existing dirty files remain user work and were not modified or staged.

## Findings

### 1. Scheduled task is not currently operating

Task: `KOSPI200 Graphify Auto Watch`

- State: Ready.
- LastRunTime: 2026-10-20 08:40:40 KST.
- LastTaskResult: 1 (failure).
- NextRunTime: none.
- Trigger: user logon only.
- RestartOnFailure: false.
- ExecutionTimeLimit: PT0S (no time limit).
- Current Graphify watcher process: none found.
- The task is therefore registered, but there is no evidence of a running watcher now. The latest recorded run failed and there is no automatic retry-on-failure policy.

### 2. Task targets the wrong worktree

- Scheduled task action runs:
  `C:\Users\white\Desktop\MovingProject\KOSPI200_Project\.codex\graphify-watch.ps1`
- That script hardcodes ProjectRoot to the original `KOSPI200_Project`.
- The copied script in active `Q25_A8_R10\.codex\graphify-watch.ps1` contains the same original-root path.
- Both scripts have identical SHA-256:
  `95AA7794DE0A394B24A57A93A88DA9F808EFF2F0404B16AC051162DA34AB9494`.
- Thus neither the scheduled task nor its copied script watches the active R10 worktree.

### 3. Historical watcher log explains incomplete refresh

Original-folder log: `KOSPI200_Project\graphify-out\watcher.log`

- 2026-10-16 first start failed because Python watchdog was not installed.
- Later starts on Oct 17–20 report the watcher entered watch mode.
- Last log line is 2026-10-20 12:47:56 KST; no later start/heartbeat/exit entry.
- Log reports that code changes rebuild the graph automatically, but non-code/doc/image changes require semantic re-extraction via `/graphify --update`.
- A `needs_update` marker was written on 2026-10-17 and remains in the original folder. It is absent from R10.
- The existing `.codex/hooks.json` only runs `graphify hook-check` on a Bash PreToolUse hook; it does not start a watcher and is not a general file-change trigger.

### 4. Active R10 graph is stale

- Graphify CLI is installed and reports version 0.9.91.
- R10 graph metadata `built_at_commit`:
  `574c9c428a3b5ee1db9088af76825fed4e9959d5`.
- Current R10 HEAD at audit time: `fb968b16a4e095dbe2a4524dcca6afb7e6ae5c5e`.
- The graph source commit is 25 commits behind current R10 HEAD.
- R10 has no watcher.log and no needs_update marker.
- No graphify watch or update command was run during this audit.

## Root cause

The auto-watch setup does not meet the active-worktree requirement:
1. The logon task points at the original folder, not R10.
2. The task''s last execution failed (result 1) and it has no restart-on-failure setting.
3. There is no active watcher process now.
4. Even when the watcher ran, documentation/non-code changes only produced a needs_update marker and required separate semantic update.
5. The R10 watcher script was copied with the original path unchanged.

## Safe next implementation boundary

A corrected per-worktree watcher would require:
- an explicit root path for the active R10 worktree;
- a task action that references that R10 script;
- a reliable start/restart policy and process/log health checks;
- separation of code AST refresh from LLM-dependent semantic refresh;
- generated output review and no automatic commit;
- no writes to the original Project200 working folder.

The next implementation must not modify the existing original-folder task or start/stop/reconfigure Windows scheduled tasks without separate approval. A new isolated R10 watcher script can be prepared and reviewed first; task registration/activation remains a separate approval gate.

## Preservation and Git

- Read-only audit; no code, task, script, process, Graphify output, Raw/REST/WS/Canonical/accepted/manifest, .env or credential changes.
- R10 local/origin HEAD before this report: `fb968b16a4e095dbe2a4524dcca6afb7e6ae5c5e`.
- Project200 remote HEAD remains `4ef1c3b76c657843c6acdb814be98f593252854c`.
- Existing dirty files remain untouched and unstaged:
  - `application/composition/validation_only_runtime_invariant_checker.py`
  - `graphify-out/GRAPH_REPORT.md`
  - `graphify-out/graph.json`
- `git diff --check`: PASS.

## Next step

T29: prepare a new isolated watcher script for R10 only, with a parameterized project root, startup diagnostics, single-instance protection, process health logging and clear distinction between automatic code AST refresh and LLM-dependent semantic refresh. Do not register or activate a scheduled task until the user separately approves that operating change.
