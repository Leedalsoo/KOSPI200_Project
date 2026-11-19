# Q25 A8 T8 — S2 Pre-entry Evidence Scope Alignment

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: validation-only replay admission evidence

## Why this change was required

The T5 supervisor runs at the beginning of each Virtual tick, before pending multi-leg work and new order admission. The T7 S2 alternative had previously synthesized four broker positions from the entry role map. Those positions describe a post-entry state, but the supervisor evaluates the tick before entry orders are submitted. Comparing those four positions with the still-flat VSSF ledger could therefore create an artificial U19 mismatch.

The T7 provider also required an explicit candidate_id field, while the actual replay tick carries timestamp and underlying_price rather than candidate_id.

## Implementation

- T7 provider now supports explicit PRE_ENTRY and POST_ENTRY evidence phases. PRE_ENTRY is the default and supplies an independently generated, validation-only flat broker snapshot; POST_ENTRY remains available for explicit post-fill lifecycle tests.
- The scenario candidate is matched to ordinary replay ticks by exact timezone-aware timestamp and underlying price when candidate_id is not present.
- T5 supervisor now respects provider is_applicable(tick) scope. If every configured provider declares that a tick is outside its evidence scope, the supervisor returns the existing X2 snapshot without treating the unrelated tick as missing evidence and without tripping X2.
- If at least one provider applies, the normal accepted/original -> Notion/source reconciliation -> alternative sequence and X2 exhaustion behavior remain unchanged.
- No change was made to X1, U19 decision rules, U21 freshness limits, order admission boundaries, or Live/REAL_VTS behavior.

## Validation

- Combined T5/T6/T7/X1/X2/U19/FRESH31/freshness regression suite: 157 passed, 0 failed.
- compileall: PASS.
- Ruff on all three changed Python source/test files: PASS.
- git diff --check: PASS.
- Tests cover PRE_ENTRY flat broker/ledger reconciliation (U19 FLAT_CONFIRMED and X1 PASS), explicit POST_ENTRY evidence, candidate matching without candidate_id, stale/future time checks, and unrelated ticks not tripping X2.

## Data and safety boundaries

- No.1534 and No.1535/1538/1554/1555 provenance and no-lookahead decisions remain mandatory.
- Existing accepted Runtime v2 and S2 sidecar remain read-only; no Raw/Canonical/manifest files were modified or recopied.
- Synthetic broker snapshot and freshness remain scenario-only validation evidence, not a real account, KIS broker, or current-market assertion.
- No new collection, KIS Live/REAL_VTS/account/order/cancel/liquidation API, collector restart, or real order action was performed.
- Existing unrelated T2 invariant-checker working diff and Graphify outputs were preserved and excluded from this commit.

## Remaining next step

T8 fixes replay applicability and pre-entry state alignment; it does not create the missing concrete primary accepted/original and Notion/source-lineage reconciliation providers, nor inject a complete provider chain into the default Virtual session. The next step is to implement those two scoped providers from the existing original/accepted evidence inventory, then wire the chain only into an isolated validation replay. The T7 S2 synthetic alternative remains the last fallback.
