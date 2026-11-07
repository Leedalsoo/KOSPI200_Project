# Runtime Market-Data Freshness Gate — File Scope and Test Plan v0.1

- Date: 2026-10-14 KST
- Status: **Draft / approval required / no implementation authorized**
- Repository: Project200
- Purpose: Submit file-level change scope and acceptance tests after checking the current KIS timestamp evidence.
- Policy candidate values already approved in principle: WS source age <= 2,000 ms; REST source age <= 2,000 ms; allowed future source-time skew <= 1,000 ms; multi-leg source-time spread <= 1,000 ms; receive-time spread <= 500 ms as a diagnostic only.
- Approved stale-data policy: block new/add/risk-increasing orders when required data is stale/unknown. Close/reduce/hedge only when the exact contract has a fresh executable-side quote and actual position plus open/pending/cancel/fill state are reconciled; otherwise block automation and alert for manual intervention.
- This approval does not authorize implementation. Source timestamp semantics and this file scope/test plan remain gates.

## 1. Timestamp verification result

### REST
- aspr_acpt_hour is documented in the official sample as a quote acceptance-time field, but publicly reviewed material does not establish its calendar date, timezone, source-clock semantics, or precision sufficiently to construct a reliable absolute instant.
- Existing VTS evidence uses a time-only HHMMSS value (154500) around a receive time of 2026-10-14 00:44 KST. The sanitized probe JSON preserves response hashes and field names but not the raw response body/value as a directly inspectable payload. A separate existing measurement note records the value. This is ambiguity evidence, not proof of source age.
- The REST normalizer currently compares price/book timestamp strings but does not convert them to an authoritative timezone-aware source instant; observed_at=None and raw_reference=None remain.

### WebSocket
- Official KIS sample lists bsop_hour for H0IOCNT0 and H0IOASP0, but the field is HHMMSS without a date. Date rollover, timezone, precision and event-time semantics are not established.
- The same official sample states these index-option WebSocket TRs are LIVE-only and unsupported in VTS. No retry was made. Historical archive labels that conflict with this statement must not be treated as proof of VTS support without verified provenance.
- Existing retrospective data is limited/uneven and cannot validate stable source-age bounds or source capability.

**Conclusion:** Source instant semantics are BLOCKED / NOT_PROVEN. Do not derive source age from client receive time or assign the receive date to a time-only source field. The approved numeric candidates remain unapplied until semantics are confirmed.

## 2. Proposed file-by-file scope — requires separate approval

| File | Proposed change after approval | Guardrails |
|---|---|---|
| contracts/types.py | Extend/reuse typed source timestamp, raw-reference and freshness verdict contracts; keep source time distinct from receive/collection time. | File already has unrelated uncommitted changes; merge narrowly and preserve them. |
| infrastructure/kis/kis_rest_market_observation_normalizer.py | Preserve raw aspr_acpt_hour, request/receive clocks, endpoint/TR and payload hash/reference; parse an absolute source instant only after documented semantics are confirmed. | File already has unrelated uncommitted changes; do not replace or reformat the file wholesale. |
| infrastructure/kis/kis_websocket_market_observation_normalizer.py | Preserve raw bsop_hour and receive timestamp separately; only derive source instant after KIS confirms date/timezone/event-time semantics and capability/provenance is valid. | Do not retry H0IOASP0 or H0IOCNT0; no LIVE subscription without separate explicit authorization. |
| contracts/market_data.py and/or a new shared freshness contract module (exact seam to be finalized) | Define typed verdicts FRESH, STALE, UNKNOWN, IDENTITY_CONFLICT, BLOCKED_SOURCE_CAPABILITY, with reason, policy version and evidence references. | Avoid strategy-specific thresholds; exact module placement is an approval item. |
| application/composition/runtime_authoritative_risk_router_adapter.py | Require validated freshness verdict before risk admission for covered routes; fail closed on missing verdict. | Existing unrelated changes must be preserved; prove callers before wiring. |
| core/runtime/reference_execution_pipeline.py | Carry the freshness decision through the shared admission boundary, if caller tracing confirms this is the correct common seam. | This file already has an uncommitted diff; preserve and merge narrowly. Do not assume every S1-S9 path uses it without trace evidence. |
| core/oms/order_router.py | Add a final defensive requirement only if architecture review confirms the freshness proof can be checked at this layer without bypassing existing approval-token contracts. | No broker call unless freshness and existing risk approval both pass. |
| New tests under tests/ (exact filenames to be chosen after scope approval) | Add new unit/contract/path-coverage tests; do not restore deleted tests. | tests/ is currently absent and Git reports existing test deletions; preserve that state. |
| verification/evidence/ | Store sanitized deterministic test results, policy version, source hash/reference and coverage evidence. | No credentials, tokens, full account identifiers or live orders. |

Potential final admission seam and exact S1-S9 caller graph are not fully proven for every runtime configuration. If a route cannot be proven to pass the shared gate, keep that route blocked rather than silently treating it as covered.

## 3. Required tests after approval

| ID | Scenario | Expected result |
|---|---|---|
| FRESH-01 | Missing, malformed or timezone/date-ambiguous source timestamp | UNKNOWN; risk-increasing order blocked; no broker call |
| FRESH-02 | Source time older than approved age limit | STALE; risk-increasing order blocked |
| FRESH-03 | Source time exceeds future-skew bound | UNKNOWN; blocked |
| FRESH-04 | REST price/book source timestamp mismatch | IDENTITY_CONFLICT or explicit timestamp-conflict reason; blocked |
| FRESH-05 | Raw payload reference/hash or exact contract identity missing | Blocked; no synthetic fallback |
| FRESH-06 | Multi-leg source-time spread > 1,000 ms or any leg stale/unknown | New multi-leg entry blocked; per-leg state preserved |
| FRESH-07 | Receive-time spread > 500 ms | Diagnostic recorded; not substituted for source-time age |
| FRESH-08 | Stale quote while exposure exists | No auto close/reduce/hedge unless fresh executable-side quote and position/order/fill/cancel reconciliation all pass; otherwise alert/manual intervention |
| FRESH-09 | Cancel requested but not confirmed; fill/late fill during cancel; partial fill | No next/replacement leg until terminal order state and remaining exposure are reconciled |
| FRESH-10 | Fresh quote returns after a gap/restart | Gate remains blocked until timestamp, identity, source capability and required account/order/position reconciliation pass |
| FRESH-11 | Every S1-S9 active registry/caller route | Prove mandatory shared gate before RiskGate.admit_order/broker; any uncovered route remains blocked |
| FRESH-12 | Risk gate rejects or approval token missing/invalid | No broker call even if data is fresh |
| FRESH-13 | Replay/restart determinism | Same inputs and policy version produce same verdict; evidence references survive restart |
| FRESH-14 | Unsupported/unverified source capability (including VTS option WS ambiguity) | BLOCKED_SOURCE_CAPABILITY; no relabeling as REAL_VTS or LIVE evidence |

All tests must assert broker-call count and record source timestamp, receive timestamp, policy version, contract identity, reason, evidence hash/reference, and route coverage. Fixture/replay tests do not count as REAL_VTS or LIVE proof.

## 4. Acceptance and sequencing gates

1. Obtain written KIS documentation/support confirmation for aspr_acpt_hour and bsop_hour: date association, timezone, event/acceptance-time meaning, precision, session rollover, and applicable REST/WS environment capability.
2. If official semantics cannot be established, keep absolute source age UNKNOWN/BLOCKED; do not enable the age gate by guessing.
3. Freeze the exact target-file list and common admission seam; reconcile existing uncommitted diffs before any edit.
4. Receive explicit user approval for this file scope and test plan.
5. Implement only approved files and rules; add new tests only.
6. Run offline unit/contract tests first, then path-coverage and controlled replay tests. Any real KIS read-only validation requires its own permitted scope; no H0IOASP0/H0IOCNT0 retries under the current instruction.
7. Report actual commands, exit codes, evidence hashes, test status and remaining gaps. No LIVE order, no Manifest change, no Git stage/commit/push without applicable approval.

## 5. Current state

- Timestamp semantics: BLOCKED / NOT_PROVEN.
- Policy values: approved in principle, not applied.
- Stale-data handling policy: approved, not implemented.
- Runtime gate and tests: NOT IMPLEMENTED / NOT RUN.
- User approval of this file scope/test plan: PENDING.
- No runtime code, Manifest, tests, order endpoints, Git index or remote branch changed by preparing this plan.

