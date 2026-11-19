# Q25 A8 T29 — R10-Isolated Graphify Watcher Script Preparation

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: prepare and validate a separate watcher launcher for R10 without modifying or activating the existing Windows scheduled task.

## Basis

- T28 established that the current task watches the original Project200 folder, is not currently running and last exited with result 1.
- No.1534 and AGENTS.md require preserving existing user-generated Graphify outputs and require separate approval for scheduler/process changes.
- The three pre-existing dirty files remain protected and excluded from staging.

## New isolated script

Created:
`.codex/graphify-watch-r10.ps1`

SHA-256:
`AB0B93FF5474AE6FDF69D00A15BC4876B4D0BF311801B7D41FAEADC5BEE9A9A4`

Behavior:
- Defaults the project root to the parent of the script''s `.codex` directory; also accepts an explicit `-ProjectRoot`.
- Uses a per-root global mutex to prevent duplicate watcher instances.
- Writes startup, Git root, Graphify version, output-state, watcher output and exit diagnostics to a per-root log under `%LOCALAPPDATA%\KOSPI200_Project\graphify-watch\`; it does not write logs into Raw/data or Graphify output directories.
- Checks the two tracked Graphify output files before starting. If either already has Git changes, refuses to start with exit code 23, preventing the watcher from overwriting pre-existing user changes.
- Delegates code AST refresh to `graphify watch`.
- Detects and logs the semantic `needs_update` marker but does not invoke LLM extraction or silently change semantic labels.
- Returns Graphify''s exit code so a separately configured scheduler can apply restart policy later.

The existing `.codex\graphify-watch.ps1`, `.codex\hooks.json`, scheduled task and original Project200 folder were not changed.

## Validation

- PowerShell AST parse: PASS.
- Fail-closed test against current R10 state: expected exit code **23**, PASS.
- Log verification: refusal reason recorded and `graphify watch` was not started, PASS.
- `git diff --check`: PASS.
- No Graphify update/extraction or watcher process was started. Existing Graphify output files are dirty, so the new guard correctly prevents automatic refresh until those artifacts are reviewed or safely versioned.

## Scheduler boundary

The existing scheduled task remains unchanged. The new script is not registered or activated. A future task must explicitly point to:
`Q25_A8_R10\.codex\graphify-watch-r10.ps1`

Before activation:
1. Review/version the pre-existing dirty Graphify outputs so the guard can pass.
2. Confirm Graphify watcher runtime dependencies in the execution environment.
3. Obtain approval to register/enable a new R10-only scheduled task with restart-on-failure and logon/startup behavior.
4. Verify actual process health and file-change detection after activation.

## Git and preservation

- Changed files in this commit: new isolated watcher script and this report only.
- Existing dirty files excluded:
  - `application/composition/validation_only_runtime_invariant_checker.py`
  - `graphify-out/GRAPH_REPORT.md`
  - `graphify-out/graph.json`
- Raw/REST/WS/Canonical/accepted/manifest/synthetic source tree, .env and credentials unchanged.
- Existing original-folder task/script and Project200 remote branch unchanged.
- No Live/REAL_VTS/real-account API, data collection or trading actions.

## Next step

T30: review the three pre-existing dirty artifacts and determine a non-destructive versioning/backup plan. Then verify the Graphify runtime dependency without starting the watcher. Scheduler registration/activation remains a separate explicit approval gate.
