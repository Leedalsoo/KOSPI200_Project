# Q25 A8 T7 — Independent S2 Synthetic Broker and Freshness Alternative

Date: 2026-11-19 (KST)
Branch: work/q25-a8-r10-order-lineage-u19-20261118
Base commit: fe7b0ddb76efa0b03d90e7d9e86fd003e5810c9a
Scope: validation-only S2-CANDIDATE-001 alternative evidence path

## Decisions and source reconciliation

- Mandatory No.1534 was reviewed first. Existing accepted Runtime v2 manifest/partitions and the derived S2 sidecar were hash-checked before use. No Raw/Canonical/accepted data/manifest was rewritten.
- No.1535/1538/1554/1555 policy was applied: preserve original source lineage, distinguish accepted observation anchors from generated scenario quotes, prohibit future anchors, and keep synthetic contract IDs/quotes/broker snapshots validation-only.
- The sidecar explicitly states that four synchronized quotes are synthetic scenarios derived from prior non-simultaneous accepted L1 observations; generated prices are not KIS quotes or actual fills, synthetic IDs are not KIS identities, and execution/Live APIs are disabled.
- Scenario role mapping was cross-checked against the manifest's execution-plan mapping: inner PUT/CALL are LONG; outer PUT/CALL are SHORT. The fixture quantity is explicitly one per leg and is a scenario parameter, not an account or position fact.

## Implementation

- Added application/composition/validation_only_s2_scenario_alternative_provider.py.
- Added tests/application/composition/test_validation_only_s2_scenario_alternative_provider.py.
- The provider implements the T5 alternative-provider call contract and reads only the existing accepted Runtime v2 manifest/partitions, S2 candidate input, quote JSONL, sidecar manifest and validation profile.
- It verifies pinned SHA-256 values, accepted-manifest crosswalk, partition hashes, profile/manifest validation-only flags, four-leg role/expiry/strike/type identity, synthetic contract namespace, source-manifest hash, source observation references and source-anchor timestamp/reference counts.
- It rejects future anchors and anchors older than the manifest's 900-second validation limit. Candidate 001's sidecar maximum anchor age is 833 seconds.
- It independently creates a synthetic broker-exchange snapshot from the sidecar's four-leg role map and explicit quantity. It does not read or copy VSSF account/ledger positions. The source tag is VALIDATION_ONLY:BROKER_EXCHANGE, never KIS/LIVE/REAL_VTS.
- It creates a separate synthetic event-time freshness verdict using the sidecar's U21 validation-only 5-second age policy and zero future skew. This is scenario-time semantics only, not proof of KIS source-time semantics or current market freshness.
- The provider is intended only for the T5 alternative path and only when the incoming replay tick carries the exact S2 candidate_id. It is not automatically enabled in the default Virtual session.

## End-to-end validation

- S2-CANDIDATE-001: four synthetic broker positions matched the VSSF-derived U19 ledger positions; U19 returned RESTORE_ALLOWED; X1 invariant/lot/fee/VSSF PnL checks passed; synthetic freshness returned FRESH.
- A tick unrelated to the candidate returns no candidate. A tick six seconds after the scenario is STALE. A tick before scenario time is rejected as a future-anchor/time-order violation.
- T5 integration test: primary accepted/original unavailable → Notion/source reconciliation unavailable → S2 synthetic alternative VALIDATED; supervisor selected the alternative and X2 remained ARMED. No immediate block on the first two missing evidence paths.
- Combined T5/T6/T7, X1, X2, U19, FRESH31 and freshness regression suite: 154 passed / 0 failed.
- compileall PASS; Ruff on new adapter/provider/tests PASS; git diff --check PASS.

## Source hashes

- Accepted Runtime v2 manifest: 7657c90f13a81a7f98a8ccd075a259c8ec9795477a2a0541366094cd87e0360f
- S2 sidecar manifest: 13580e010c34c74a1787bffb6b6b72adebdc4964f848937c0894bfa0fd4918b7
- S2 four-leg quote JSONL: 466c796c536d48a91fd548e6c61c597da4bde558bd56a079cc8956a9f882786e
- S2 candidate inputs: d2d96b35d0402c1bdf8a6b07e771e9bdc593772985610dc68d3fd74f615b5a32
- S2 validation profile: c0607c405abba4d2500bd8d5572db0270a9bdc61ab7e4943b1fd3c73d6181b18

## Boundary and next work

- This is a deterministic, validation-only alternative for one sidecar replay candidate. It is not a general broker snapshot, not an actual account snapshot, and not an execution/position assertion for arbitrary Virtual runs.
- It is not wired into the default Virtual session; the default still requires explicit primary accepted/original and Notion/source reconciliation providers, with the S2 provider supplied as the alternative only for the matching replay.
- Next step: implement the primary accepted/original and Notion/source-lineage reconciliation providers for the per-run VSSF state, then inject the complete provider chain into an isolated validation-only replay session. Preserve this synthetic alternative as fallback.
- No KIS Live, REAL_VTS, real-account/order/cancel/liquidation API, new REST/WS collection, or collector restart was performed.
- Existing T2 invariant-checker working diff and Graphify output changes were preserved and excluded from this commit.
