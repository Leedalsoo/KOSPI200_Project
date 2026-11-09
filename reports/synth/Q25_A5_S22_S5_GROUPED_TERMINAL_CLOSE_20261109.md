기준: Current Baseline v2 @E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D, 적용한 SSOT 항목 ID: CB2-01, CB2-02, CB2-03, CB2-04, CB2-05, CB2-06, CB2-08, CB2-09

# Q25 A5 S22 — Strategy 5 authoritative grouped terminal close

## 1. 기준 및 안전 Gate

- SSOT: Current Baseline v2 — 2026-11-09. Local `docs/CURRENT_BASELINE.md` SHA-256 matches the recorded SSOT hash above; Notion SSOT page was fetched and reviewed.
- `AGENTS.md` was read first in this isolated worktree. Applicable rules: PSB validation-only scope, S5 entry remains BLOCKED, authoritative open-lot quantity/identity, no production/Live API, isolated worktree, no push during S22.
- Confirmed references: No.1132 (all terminal open legs in one grouped plan), No.1134 (side/quantity from authoritative open-position lots; signal quantity is not close quantity), No.1167 (additive diagnostics only), No.1168 (retired BUY2 entry), No.1474 (current S5 entry fail-closed), No.1475 (S21 identified terminal grouped-close and residual-lot gap).
- Policy conflict: none identified for this narrow terminal-close implementation. S5 new-entry/hedge/re-entry policy remains blocked and was not changed.

## 2. Scope

- Target branch/worktree: `q25-a5-s22-s5-group-close-20261109`, based on target branch remote HEAD `f30fd3e0aa84751971538c5b5e59f08becfbb590`.
- Original working folder and its dirty/untracked files were not modified.
- Changed files: `core/strategy/track5_gap_divergence.py`, `tests/core/test_track5_spec_alignment.py`, `tests/application/composition/test_strategy_spec_alignment_close_lots.py`, `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`, this report.
- `docs/CURRENT_BASELINE.md` was copied into the isolated worktree solely for SSOT gate verification; it remains untracked and is excluded from the commit.

## 3. Implementation

- Futures/Option exit proposals now carry `EXIT_PROPOSAL_QUANTITY=1` as a positive trigger marker only. It is not executable close sizing.
- The retired `MINI_FUTURES_QUANTITY=5` setting remains only for manifest/config compatibility; no close signal or execution plan uses it. `ENTRY_QUANTITY` remains retired-entry compatibility only.
- Strategy-local `build_execution_plan` no longer creates Futures/Option close legs from cached constants. It fails closed with `TRACK5_CLOSE_REQUIRES_AUTHORITATIVE_OPEN_LOT_RESOLVER`.
- Runtime resolver continues to route terminal Futures-tagged signals to the unfiltered grouped close builder, which reads all open lots for the run/strategy, requires one unambiguous group, aggregates remaining quantities by authoritative identity/side/role, and reverses each lot side.
- Gap-fill remains Futures-only non-terminal. When the Futures hedge is already closed, the existing Option-only exit path remains available.
- Risk policy, diagnostic JSONL behavior, manifest, operational settings, and all new-entry policy were not changed.

## 4. Verification evidence

| Check | Command/method | Result |
|---|---|---|
| Focused tests | `py -m pytest tests/core/test_track5_spec_alignment.py tests/application/composition/test_strategy_spec_alignment_close_lots.py tests/application/test_track5_option_contract_source.py tests/core/test_strategy_registry_required_source_diagnostics.py -q` | 26 passed, exit 0 |
| Syntax | `py -m py_compile core/strategy/track5_gap_divergence.py tests/core/test_track5_spec_alignment.py tests/application/composition/test_strategy_spec_alignment_close_lots.py` | PASS, exit 0 |
| Whitespace | `git diff --check` | PASS, exit 0 |
| Graphify | `graphify update .` then `graphify query "Track5GapDivergence EXIT_PROPOSAL_QUANTITY authoritative open lots"` | Update exit 0; query exit 0; 7,195 nodes / 20,481 edges / 368 communities |

Focused unit tests use synthetic in-memory lot fixtures: two Futures lots (remaining 2+1) and two Option lots (remaining 1+3) produce a two-leg grouped plan with close quantities 3 and 4, opposite sides, and preserved authoritative identities. A separate test confirms gap-fill filters to Futures only. Stop, timeout, and trailing triggers each produce the terminal-close route marker. The direct strategy builder rejects close plans without the authoritative lot resolver.

Graphify reported one pre-existing syntax warning in `application/composition/virtual_composition_root.py:54` and 28 files with no extracted symbols. Graphify update itself completed successfully.

## 5. Result and limits

- S22 implementation and focused verification: complete.
- Overall verdict: `PSB_UNVERIFIED` — unit/contract wiring only. No Virtual Runtime E2E, replay, strategy matrix, or full pytest was run; S23 owns natural-signal Runtime E2E and FAST/DETAILED verification.
- KIS, REAL_VTS, Live, real-account, order/modify/cancel/balance/margin APIs: not called.
- No push, merge, rebase, reset, force-push, or history rewrite.
- Original workfolder and its 224 dirty/untracked items remain untouched. Five A6 uncommitted documents in the A6 worktree remain untouched.
- Implementation commit SHA: `5c089f47700556ab77d1148650948912ecd12089` (`fix(s5): derive grouped terminal close from open lots`).
