# Runtime Market-Data Provenance / Freshness Gate — Impact Plan v0.1
**As of:** 2026-10-14 KST  
**Status:** Static audit and implementation plan only; no freshness threshold approved; no runtime gate implemented.

## 1. Decision boundaries
- KIS REST/WS and official KIS master are the only runtime authority for this KIS path. Virtual/replay evidence is not LIVE proof.
- Do not invent a max quote age, tolerate missing timestamps, derive exchange time from local receive time, or substitute another provider.
- If required provenance/freshness cannot be established, block new risk-increasing orders. Position-reducing orders also require valid contract identity and actual position/terminal-order reconciliation; do not presume an exception.
- No Live order endpoints, Manifest changes, strategy-specific freshness logic, or existing deleted test restoration in this work item.

## 2. Verified current contract and source behavior
### REST normalization
File: `infrastructure/kis/kis_rest_market_observation_normalizer.py`
- Requires both price and order-book responses to have `rt_cd=0`.
- Requires an authoritative option identity from `OptionIdentityLookup`.
- Rejects mismatched price/order-book source timestamps when both are present.
- Requires underlying code `2001`, name `KOSPI200`, and an underlying price.
- Emits endpoint/TR-ID provenance and a source timestamp if one is present.
- Does **not** parse source timestamp into an authoritative timezone-aware `observed_at`; currently sets `observed_at=None`.
- Sets `raw_reference=None`; no raw response hash/reference is propagated in the observation.
- Does not compute age, stale/fresh verdict, max-age policy version, or a fail-closed admission token.

### Shared data contracts
File: `contracts/types.py`
- `MarketObservation` has `observed_at`, `collected_at`, `provenance.source_timestamps`, and optional `raw_reference`.
- `DataQuality` has `is_fresh`, `is_complete`, `source_available`, and `reason`.
- `CanonicalMarketTick` requires an `observed_at`, but its contract does not itself prove that a KIS source timestamp was parsed correctly or that the timestamp is within an approved age limit.

### Runtime and order boundary
- `application/composition/virtual_runtime_data_provider.py::VirtualRuntimeDataProvider.snapshot()` derives a Virtual runtime data view from injected VMS ticks and sources. Several source statuses are set from source presence/completeness; they are not a demonstrated common KIS raw-provenance-to-order-admission gate.
- `core/runtime/reference_execution_pipeline.py::route_from_authoritative_sources()` builds account/position risk inputs, calls `risk_gate.admit_order()`, and routes only if admitted.
- `core/oms/order_router.py::StandardOrderRouter.register_and_route()` requires a risk approval token before broker submission.
- The static review has not demonstrated one authoritative KIS observation/freshness verdict is mandatory and preserved across all strategy paths up to the final admission call.

## 3. Current decision
**BLOCKED / NOT_PROVEN** for end-to-end KIS provenance/freshness enforcement. The normalizer's timestamp-equality check is not a freshness check. No source-age threshold has been selected or implemented.

## 4. Proposed common implementation seam (not yet implemented)
1. Add a shared, environment-neutral freshness policy/config contract in the common data/risk boundary; do not put thresholds in individual strategies.
2. Preserve the original KIS source timestamp, parsed timezone, local receive timestamp, endpoint/TR ID, exact contract identity/master snapshot reference, raw payload SHA-256/reference, and policy version.
3. Validate source timestamp format and timezone, future skew, missing timestamp, clock assumptions, response-pair timestamp equality, and source age. A failed parse or missing source timestamp must not silently fall back to `collected_at`.
4. Compute a typed freshness result (`FRESH`, `STALE`, `UNKNOWN`, `IDENTITY_CONFLICT`) with explicit reason and provenance; do not reduce UNKNOWN to boolean false/true without preserving reason.
5. Require the result at the shared runtime/order admission seam before `RiskGate.admit_order()`; ensure every S1–S9 route reaches that seam. If any route bypasses it, keep that route BLOCKED until wired.
6. Fail closed on STALE/UNKNOWN/IDENTITY_CONFLICT for risk-increasing orders. Recovery requires new authoritative data plus any required account/position/order reconciliation; receipt of a later quote alone must not automatically clear unrelated blockers.
7. Log evidence identifiers and hashes only; never log credentials or full account identifiers.

## 5. Policy decisions required before coding
These are deliberately UNSET; no defaults are authorized:
- Maximum quote age by input type (option quote, order book, underlying index/futures, Greeks/IV).
- Whether REST/WS inputs have distinct limits and what exact KIS source timestamp field/timezone semantics are authoritative.
- Allowed future clock skew and how to handle source timestamps with date rollover/session boundaries.
- Required number of synchronized inputs for multi-leg snapshots and maximum cross-leg timestamp spread.
- Reduction/hedge exception policy when quotes are stale but exposure exists; no implicit exception.
- Policy versioning, configuration ownership, and evidence retention period.

## 6. New test plan (new tests only; NOT RUN)
- FRESH-01: missing source timestamp → UNKNOWN and order blocked.
- FRESH-02: unparseable/ambiguous timezone → UNKNOWN and order blocked.
- FRESH-03: timestamp exceeds approved max age → STALE and order blocked.
- FRESH-04: source timestamp is beyond allowed future skew → UNKNOWN and order blocked.
- FRESH-05: price/order-book timestamps differ → IDENTITY/TIME conflict and order blocked.
- FRESH-06: contract identity/expiry/multiplier differs from authoritative master snapshot → blocked.
- FRESH-07: one leg stale or timestamp spread exceeds approved bound → whole multi-leg entry blocked.
- FRESH-08: valid fresh data plus valid identity and approved policy → gate may pass; downstream RiskGate must still independently approve.
- FRESH-09: restart/replay preserves raw reference, policy version and deterministic result.
- FRESH-10: every S1–S9 order path is proven to call the same gate; any uncovered path is BLOCKED.
- Each test must record input source, source/receive timestamps, policy version, raw hash, guard reason, and whether the RiskGate/OMS/broker boundary was reached. Unit/contract tests use controlled fixtures; they do not count as REAL_VTS or LIVE evidence.

## 7. Required next sequence
1. Obtain user-approved freshness policy values and source timestamp semantics.
2. Trace each S1–S9 runtime path to the final admission function and create a path-coverage checklist.
3. Implement the shared contract/gate only after policy approval.
4. Add new tests without restoring deleted tests; run targeted tests and preserve evidence.
5. Repeat read-only KIS VTS validation only after test results are clean; LIVE remains blocked without proper LIVE credentials and separate approval.

## 8. Execution record
- Static audit completed 2026-10-14.
- `py_compile` and shared-calendar offline contract checks passed in this work session.
- No freshness threshold was guessed; no runtime freshness code changed.
- LIVE credentials: no LIVE/REAL/PROD credential keys matching the expected naming patterns were found in the checked `.env` file. No credential values were read or recorded; this does not rule out an external secret store or differently named configuration.
- VTS account binding: existing read-only evidence shows `VTFO6118R` HTTP 200, `rt_cd=1`, `90070000`; retry remains held pending account/API registration confirmation.
- No orders, Manifest changes, Git stage/commit/push, or deleted-test restoration.
