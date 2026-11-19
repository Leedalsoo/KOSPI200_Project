# Q25 A8 T10 — Isolated S2 Evidence-Only Virtual Replay

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Scope: one-candidate, quote-only, no-order Virtual replay

## Safety boundary

- This mode is explicit opt-in only: validation_only_s2_replay=True.
- Requires VIRTUAL environment, supported CALM simulator scenario, no external option master, no historical replay store, no selected strategies, no externally supplied supervisor, and an existing original-source root.
- The external KIS option master is forbidden in this mode to prevent future-dated Master lookahead. No strategy, decision, order, cancellation, liquidation, Live, REAL_VTS, or account/order API is invoked.
- A single quote-only event is published. last_price and volume remain None. The VMS market receives exactly four T7 SYNTHETIC:DERIVED_SCENARIO quotes from the verified sidecar.
- The runtime evidence supervisor executes before quote-only validation. If X2 is not ARMED or evidence evaluation raises, the event is blocked and no further evaluation occurs.
- On successful S2 evidence-only replay, strategy context and strategy execution are skipped entirely. The result is EVIDENCE_VALIDATED_NO_EXECUTION.

## Implementation

- Added T7 option_quotes_at() and build_quote_only_tick() to publish the exact four sidecar legs through the Virtual Market quote-only boundary.
- Added X1/U19/freshness/X2 supervision to AutomatedVirtualTradingLoop.on_quote_only_tick.
- Added explicit session attachment helper and replay callback: loop.replay_validation_only_s2_candidate().
- create_virtual_run_session now constructs T6 VSSF evidence adapter, T9 accepted/original and Notion/source reconciliation providers, T7 synthetic fallback, U19 recovery store/coordinator and T5 supervisor, sharing the exact same X2 switch.
- U19 recovery state is isolated per run under LocalAppData; no project Raw/Canonical/accepted files are changed.
- The quote-only event carries no trade fields; the evidence-only branch does not call strategy context, strategy hub, decision arbitration, or order routing.

## Actual isolated Virtual replay

Run ID: SYNTHETIC:S2_EVIDENCE_ONLY_20261119T1245

- Event status: EVIDENCE_VALIDATED_NO_EXECUTION.
- Order routing: NOT_INVOKED.
- Four synthetic option quotes published to the Virtual Market.
- Primary accepted/original provider: exact original four-leg coverage 0/4.
- Notion/source reconciliation: original WS raw SHA-256 matched; all 12/12 source anchors present; exact original four-leg coverage 0/4.
- T7 provenance-preserving synthetic alternative: VALIDATED.
- U19: FLAT_CONFIRMED.
- X1: VALIDATION_ONLY_RUNTIME_INVARIANTS_PASS.
- X2: ARMED.
- signal_observation_only and validation_only_s2_replay: true.
- No strategies, decisions, orders, cancels or liquidations were run.

## Validation

- Combined T5-T10/X1/X2/U19/FRESH31/freshness regression suite: 177 passed, 0 failed.
- Actual end-to-end isolated Virtual evidence-only replay: PASS.
- compileall: PASS.
- Ruff on new provider/test files: PASS.
- Ruff critical syntax/undefined-name checks on modified runtime/session files: PASS.
- git diff --check: PASS.

## Boundaries and next step

- This is a one-candidate evidence-only replay. It does not certify multi-tick strategy performance, order execution, actual broker positions, fees, margin, or real account behavior.
- No.1534 and No.1535/1538/1554/1555 references remain mandatory. The provider records decision references and verifies local source lineage; live Notion fetching remains an external orchestration responsibility.
- Synthetic contract IDs, quote prices and the broker flat snapshot remain validation-only, not actual KIS identity or account facts. Actual account API connection will trigger field-by-field matching across the full codebase.
- Next T11: expand the isolated evidence-only replay to a deterministic multi-tick scenario and test freshness expiry, X2 latch persistence, and recovery without enabling order execution.
- Original Raw/Canonical/accepted data and sidecar remain read-only. Project200 unchanged. Existing unrelated T2 invariant-checker working diff and Graphify outputs remain uncommitted and preserved.
