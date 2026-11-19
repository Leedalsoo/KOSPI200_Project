# Q25 A8 T6 — Read-only VSSF Runtime Evidence Adapter

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Base commit: 94c4bf89911972edd4a47a1e5b0746a51dc77cfd
Scope: validation-only Virtual Runtime evidence assembly

## Mandatory decisions applied

- No.1534 was reviewed first. Existing Raw/Canonical, KIS Master, REST, expiry cache, accepted manifests and derived scenario inventory are to be reconciled before judging a gap. Raw frame counts, parsed execution counts and Canonical observations remain distinct.
- No.1535 accepts existing observed data and provenance-preserving synthetic/complementary data as project validation inputs, but does not turn synthetic values into observed market facts. New REST/WS collection remains stopped.
- No.1538 source-anchor rules were applied: same-date accepted anchors, no future observations, separate source-anchor and scenario timestamps, explicit spread/depth proxy provenance.
- No.1554/1555 preserve the KIS authoritative identity and Production boundary. Synthetic contract namespace and complementary observations are validation-only; after a separately authorized real-account API connection, exact contract/account/order/fee/margin/tick/tradability fields must be reconciled field-by-field across the codebase.
- A first discrepancy or missing input does not itself trip X2. The T5 supervisor continues through Notion/source reconciliation and alternative evidence providers; X2 trips only after the configured paths are exhausted.

## Reusable evidence inputs inspected

- Accepted Runtime v2 manifest: data/accepted_market_data/runtime_v2/manifest.json
  - SHA-256: 7657c90f13a81a7f98a8ccd075a259c8ec9795477a2a0541366094cd87e0360f
  - Existing partitions: 20261012.jsonl and 20261013.jsonl.
- Market-calibrated S2 sidecar:
  data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115
  - manifest.json SHA-256: 13580e010c34c74a1787bffb6b6b72adebdc4964f848937c0894bfa0fd4918b7
  - four_leg_quotes.jsonl SHA-256: 466c796c536d48a91fd548e6c61c597da4bde558bd56a079cc8956a9f882786e
  - candidate_inputs.json SHA-256: d2d96b35d0402c1bdf8a6b07e771e9bdc593772985610dc68d3fd74f615b5a32
- These inputs were read-only. No Raw, Canonical, accepted partition, manifest or sidecar was rewritten or copied.

## Implementation

- Added application/composition/validation_only_vssf_runtime_evidence_adapter.py.
- Added tests/application/composition/test_validation_only_vssf_runtime_evidence_adapter.py.
- The adapter reads the same per-run VirtualMultiLegExecutionBridge and VSSF runtime used by the execution loop:
  - group execution reports, execution-to-leg metadata and provenance crosswalk;
  - VirtualPositionLotStore history/open lots/close events;
  - VirtualTrack9FeeLedger records;
  - VSSF account positions, realized/unrealized PnL and per-position mark prices.
- It creates a run-scoped U19 execution-ledger snapshot and X1 invariant inputs without mutating the source read models.
- It requires a separately supplied validation-only broker snapshot with exact U19 source tag VALIDATION_ONLY:BROKER_EXCHANGE and matching run scope/as-of. It never copies the VSSF account into the broker snapshot.
- It requires a separately supplied FRESH verdict. It does not manufacture a market freshness result.
- Provenance namespace, deterministic rule ID, source manifest SHA-256, anchor refs, timezone-aware source/scenario times, evidence refs and no-future-anchor order are validated.
- Missing execution provenance, order quantity, identity crosswalk, mark price or inconsistent account/ledger positions raises an evidence-contract error. The supervisor can then try Notion/source reconciliation and the synthetic alternative provider rather than treating the first missing field as a terminal stop.
- The adapter does not automatically wire itself into the default Virtual session: a distinct broker-side validation snapshot provider and a tick-freshness provider must be explicitly injected. This prevents a VSSF self-comparison from being misrepresented as independent broker or market evidence.

## Validation

- T6 adapter tests: 4 passed.
- Combined T5/T6, X1, X2, U19, FRESH31 and freshness regression suite: 149 passed / 0 failed.
- compileall on the new adapter and test: PASS.
- Ruff on the new adapter and test: PASS.
- git diff --check: PASS.
- The tests cover a valid read-only VSSF candidate, U19 matching, X1 lot/fee/PnL reconciliation, preservation of broker-position mismatch for U19 reconciliation, missing execution provenance rejection, and synthetic/no-future-anchor requirements.

## Boundaries and next step

- No KIS Live, REAL_VTS, real-account, broker order/cancel/liquidation API, new REST/WS collection or collector restart was performed.
- No production identity, account fact, fee schedule, exchange margin rule or Live readiness is inferred from the synthetic validation fixture.
- The default runtime still needs separately sourced validation-only broker-side snapshot and tick freshness providers before this adapter can be assembled into an automatically injected per-tick supervisor. The next step is to implement those providers using existing accepted/original evidence and independently generated, provenance-preserving synthetic fixtures; do not derive the broker snapshot from the same VSSF state.
- Existing T2 invariant-checker working diff and Graphify output changes were preserved and excluded from this T6 change.
