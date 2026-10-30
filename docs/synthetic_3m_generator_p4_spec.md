# P4 — Synthetic Market Data Generator Specification

- Document ID: P4-SYNTHETIC-GENERATOR-SPEC
- Version: 0.2
- Status: **DRAFT — specification review only; no generator implementation authorized by this document; no production identity/runtime approval**
- Scope: three-calendar-month KOSPI200 option scenario dataset for signal/replay testing
- Related implementation: `scripts/generate_authoritative_option_synthetic_3m.py`, `scripts/generate_synthetic_3m_p5.py`, `scripts/validate_synthetic_3m_p5.py`, `scripts/validate_authoritative_option_synthetic_3m.py`
- Related existing contract: `docs/synthetic_3m_data_contract.md`

## 1. Purpose and boundaries

Define deterministic generation and validation of synthetic/derived market data without changing production code, existing data, Windows scheduler configuration, or prior verification evidence.

Generated scenario data is **not** a KIS VTS observation, Live observation, exchange quote, executable quote, order, fill, or production-performance result. The required provenance value is `DERIVED_SCENARIO`; a separate explicit `synthetic: true` flag is required so consumers can reject the data unless a synthetic-capable environment was explicitly selected.

The generator must not import or call strategy implementations. Strategies consume market data only through the same public runtime market-data interface used by other environments. Generator code, strategy code, and strategy-specific signal logic remain dependency-separated.

## 2. Existing authoritative-input rules to preserve

1. Calendar dates and session boundaries come from validated, source-attributed exchange-calendar snapshots. Do not infer holidays from weekdays or create a fallback calendar.
2. Contract attributes must come from a validated source record: product family, source instrument code, option type, strike, exact expiry where available, and multiplier source.
3. The initial underlying reference must come from the approved same-date regular KOSPI200 futures source. Mini futures and guessed prices are excluded.
4. Preserve the original source paths, source dates, hashes, schema/version information, and transformation assumptions in the manifest.
5. Unknown, missing, conflicting, or ambiguous required values fail closed as `BLOCKED`/`UNAVAILABLE`; never substitute zero, false, a guessed production expiry, or an inferred contract code. The only expiry exception is the explicitly labelled scenario-only calendar policy in §2.2.
6. Keep source provenance categories separate: `REAL_VTS`, `DERIVED_SCENARIO`, `SYNTHETIC`, and `VIRTUAL_EXECUTION` are not interchangeable labels.

### 2.1 Identity-source blocker

The current project evidence does not establish an authoritative owner for the production `Standard instrument_id`; the owner matrix explicitly leaves that decision unresolved. The existing synthetic contract's KRX snapshot requirements must not be interpreted as permission to promote KRX identifiers, KIS broker symbols, fixture IDs, or generated IDs into production Standard instrument identity.

Until the identity owner and permitted synthetic-runtime identity mapping are explicitly approved:

- the generator may preserve source-native contract identifiers as source evidence;
- it must not mint a production `instrument_id` or claim production order/position identity validity;
- any downstream runtime path requiring an unresolved Standard identity must report `BLOCKED_IDENTITY_OWNER_UNRESOLVED` or `UNAVAILABLE`;
- this blocker must not be bypassed by a synthetic ID, cross-source guess, or implicit alias.

Calendar authority and broker/contract-identity authority are separate questions and must be validated independently.

### 2.2 User-approved synthetic-only expiry fallback (2026-10-26)

If an approved source with explicit exact expiry fields cannot be confirmed, P5 may generate **scenario-only expiry dates** by applying the documented KOSPI200 option calendar rules to the versioned local holiday calendar. This is an explicit exception for `DERIVED_SCENARIO` generation only; it does not establish authoritative contract metadata.

- Monthly scenario expiry: second Thursday of the contract month; if not a trading day in the supplied calendar, move backward to the previous trading day.
- Weekly Monday scenario expiry: the series' declared ordinal Monday; if a holiday, move forward to the next trading day.
- Weekly Thursday scenario expiry: the series' declared ordinal Thursday, excluding the second Thursday; if a holiday, move backward to the previous trading day. A source-series label that conflicts with the exclusion rule blocks generation.
- Record the exact rule version, official rule reference URLs, calendar source paths/hashes, and source Option Master hash in the dataset manifest.
- The result must be labelled `SYNTHETIC_CALENDAR_DERIVED`; it must not be presented as an exact expiry supplied by the source master or as KIS runtime authority.
- Use a separate namespaced `synthetic_contract_id` such as `SYNTHETIC_CONTRACT:<stable-hash>` and preserve the source-native code separately. Do not create or alias a production `Standard instrument_id`.
- Keep `identity_source_status=BLOCKED_IDENTITY_OWNER_UNRESOLVED`, `production_runtime_eligible=false`, and `validation_only=true`. This data is for scenario/replay testing only and must be rejected by REAL_VTS/Live runtime paths.

This exception follows the user's direct instruction on 2026-10-26. It does not override the confirmed decision that KRX must not be a runtime authority, identity substitute, or fallback. KRX holiday data and rules are used here only to construct explicitly synthetic scenario data.

## 3. Horizon, calendar, and session semantics

1. Select the latest valid, approved source snapshot not later than the requested KST as-of date. Record the exact selection rule and chosen snapshot date.
2. The start boundary is inclusive; the end boundary is start date plus three calendar months, exclusive, with day-of-month clamped to the target month's last valid date.
3. Generate only source-confirmed trading dates in `[start, end_exclusive)`. Load every calendar year needed for the horizon and expiry resolution. Missing/invalid year data blocks generation.
4. Compute trading-day and event counts from the validated calendar and emitted contract coverage; do not use a hard-coded trading-day/event total as the correctness criterion.
5. Session values in `docs/synthetic_3m_data_contract.md` (regular session 08:45–15:45 KST; expiring option cutoff 15:20 KST) are **scenario assumptions for this validation-only dataset** until confirmed by an approved KIS master/API capability and direct REAL_VTS observations. Preserve the assumption and verification status in the manifest; do not present these values as KIS-authoritative evidence. Do not fabricate night-session records. If the runtime-authority requirement applies to a requested output, fail closed rather than treating the scenario assumption as authoritative.
6. Timestamps must be timezone-explicit (`Asia/Seoul` semantics), monotonic in the declared output order, and unique by the defined event key. Market/source time must remain distinguishable from collected/generated time.
7. Pattern selection may alter only scenario path/declared volatility assumptions. It must not change dates, exchange sessions, contract identity, expiry, multiplier, or provenance.

## 4. Required dataset metadata

Each dataset manifest must contain at least:

- `schema` and `schema_version`;
- `rules_version` and a distinct `generator_version`;
- `synthetic: true` and `provenance: DERIVED_SCENARIO`;
- `dataset`, `scenario_id`, `pattern`, integer `seed`, and `run_id`;
- exact `date_start`, `date_end`, `date_end_exclusive`, `horizon_months`, and timezone;
- authoritative calendar source paths, dates, versions/hashes, and trading-day list/count;
- contract-master source path, source date, schema, SHA-256, and explicit identity-source status;
- same-date underlying source path, source code/field, date, value, and SHA-256;
- session boundaries, bar interval, expiry cutoffs, and actual event/contract counts;
- valuation assumptions, tick-size rules, known market-rule limitations, and coverage gaps;
- deterministic ordering/key policy, output file list, per-file row counts, byte counts, and SHA-256;
- validation result and all blockers/limitations.

Every generated row must carry `synthetic: true`, `provenance: DERIVED_SCENARIO`, `generator_version`, `seed`, `scenario_id`, and a stable event/sequence identity. A consumer must be able to identify synthetic data from the row itself, without relying only on a directory name or manifest lookup.

Secrets, credentials, access tokens, and account identifiers must never be included in records, manifests, logs, test output, or Notion summaries.

## 5. Deterministic generation requirements

For the same validated source snapshots, rules/generator versions, pattern, seed, horizon, and configuration:

1. Repeated runs must produce the same ordered market-event rows and row-level values.
2. **High-speed and detailed modes must produce identical semantic rows and event ordering.** The modes may differ in instrumentation or batching only; they may not change rounding, random-number consumption, time calculations, coverage, or output values.
3. A one-shot generation and a generation split into date-aligned segments, then merged in canonical order, must produce identical event rows and identical per-day output bytes for the same inputs/configuration.
4. Segment boundaries must not reset or shift scenario randomness. Random values must be derived from a documented stable key (or a documented deterministic stream offset) so partitioning and processing speed cannot alter results.
5. Stable row identity must be derived from deterministic input fields and must not depend on wall-clock time, process scheduling, filesystem enumeration order, or random UUIDs.
6. Use explicit numeric precision and rounding rules. Do not rely on platform-dependent floating-point accumulation where it can alter emitted prices or event ordering.
7. Separate nondeterministic operational metadata (for example, invocation timestamp) from deterministic dataset content. Such metadata must not affect row identity, content hashes, or equivalence comparisons.
8. A seed is mandatory and must be recorded exactly. Missing seed is a validation error, not an implicit default.

## 6. Runtime integration contract

The generator produces files; it does not instantiate strategies, submit orders, or perform execution.

A synthetic-capable environment adapter may expose generated records through the public `MarketDataProvider` boundary (`snapshot`, `subscribe`, `health`) and the project's canonical market-data types. It must preserve source time, as-of time, instrument identity status, freshness/data-quality status, and provenance.

- Runtime/strategy code must not read generator-private structures or parse generator files directly.
- Synthetic input must be explicitly selected by environment configuration and visibly marked in runtime health/status.
- A REAL_VTS/Live environment must reject `synthetic: true` / `DERIVED_SCENARIO` input.
- Synthetic data must not be represented as a real market-data frame or real broker execution evidence.
- If a required authoritative identity, calendar, expiry, quote field, or freshness value is absent or contradictory, the affected contract/path is blocked; no fabricated fallback is permitted.
- Strategy signals and replay outcomes must retain the run/scenario/data provenance needed to trace each decision to its input rows.

## 7. Validator requirements

The validator is a separate pre-replay gate and must not silently repair data. It must verify:

1. manifest schema/version, `generator_version`, rules version, `synthetic: true`, and `DERIVED_SCENARIO` provenance;
2. required authoritative input existence, source metadata, source-date consistency, and actual SHA-256 values;
3. exact three-calendar-month boundaries and complete source-confirmed trading-day sequence;
4. session timestamp bounds, bar interval, ordering, uniqueness, expiry cutoffs, and absence of weekend/holiday rows;
5. row-level synthetic/provenance/version/seed/scenario identifiers and stable event IDs;
6. source-backed contract identity, option type, strike, exact expiry, product family, and multiplier provenance;
7. numeric validity, option-price tick alignment, bid/ask ordering, and declared valuation assumptions;
8. per-day/per-contract row counts, total event count, manifest-to-file references, and per-file checksums;
9. explicit reporting of missing weekly series, strike coverage gaps, unresolved identity, and market-rule limitations;
10. repeat-run, high-speed-versus-detailed, and one-shot-versus-segmented equivalence checks;
11. no output path overwrites prior run evidence unless an explicit, separately approved overwrite is supplied.

A structural or provenance failure must return `BLOCKED_DATASET_VALIDATION` (or a more specific `BLOCKED_*` reason) and prevent replay. A known limitation that does not invalidate structural data must be reported as `PASS_WITH_LIMITATION`, never as full exchange-mechanics compliance. Replay and UI smoke results remain separate gates.

## 8. Minimum acceptance tests for a future implementation phase

| ID | Test | Required outcome |
|---|---|---|
| P4-A01 | Same input/configuration/seed, two runs | Identical ordered event rows and deterministic content hashes |
| P4-A02 | High-speed vs detailed mode | Identical semantic rows, order, and counts |
| P4-A03 | One-shot vs segmented generation | Identical merged rows and per-day output bytes |
| P4-A04 | Change seed only | Scenario values change where randomized, while source identities/calendar/provenance remain unchanged |
| P4-A05 | Missing/invalid calendar or master | `BLOCKED`; no fallback output accepted |
| P4-A06 | Missing/conflicting underlying source | `BLOCKED`; no guessed/zero price |
| P4-A07 | Missing source exact expiry or unresolved production identity | Scenario-only expiry may use §2.2 calendar policy with full provenance; production identity remains blocked and is never inferred |
| P4-A08 | Remove/change a file after manifest creation | Validator fails checksum/reference verification |
| P4-A09 | Flip row/manifest synthetic flag or provenance | Validator fails |
| P4-A10 | Inject weekend/holiday/out-of-session/expired-contract row | Validator fails |
| P4-A11 | REAL_VTS/Live adapter receives synthetic input | Input rejected before strategy/order path |
| P4-A12 | Generator output consumed via public MarketDataProvider | Contract tests pass without strategy importing generator internals |
| P4-A13 | Prior output exists at target | New run preserves prior evidence or blocks; no silent overwrite |
| P4-A14 | Strategy signal/replay trace | Every signal/result is traceable to run, scenario, and source event provenance |

## 9. Operational safety and non-goals

- Do not modify, stop, disable, restart, or re-register the Windows scheduler in the specification phase.
- Do not modify `data/`, `.env`, KIS token caches, existing output datasets, code, tests, or prior evidence during P4.
- Do not install packages, call live endpoints, submit orders, or use Live credentials.
- Do not delete files or change output directories during implementation without the relevant phase approval.
- This document does not claim that current code already meets the requirements above.

## 10. Implementation-phase entry criteria

Implementation must remain blocked until the user explicitly approves the implementation phase and the following are resolved or formally scoped as blockers:

1. Review this draft against the latest active project decisions and current code.
2. Decide how source-native scenario contract IDs are represented without pretending the unresolved production Standard `instrument_id` owner is known.
3. Confirm the authoritative source/version rules for calendar, option master, and initial underlying.
4. Define deterministic random-access/stream semantics for segment equivalence.
5. Add the new metadata and validator checks without weakening existing gates.
6. Add acceptance tests before changing the generator implementation.
7. Validate only in an isolated output directory; preserve current data and evidence.

## 11. v0.2 dataset profiles and event scenarios

The generator specification must define these named profiles. These names describe validation datasets, not profitability experiments or production eligibility.

| Profile | Horizon | Intended sampling | Seeds/runs | Purpose / limitations |
|---|---:|---|---:|---|
| `SYN-EVT` | Event windows | Event-driven, source-interface resolution | Configured per event case | Targeted gaps, delayed/stale/duplicate/zero quotes, crossed/invalid book, price gaps, volatility bursts, whipsaws, trend/reversal, crash/rebound, expiry/D-4 and recovery cases. |
| `SYN-1M` | 1 calendar month | 1-second only where explicitly selected; otherwise declared base interval | 5 | Short-horizon smoke and lifecycle coverage; must include month-start → D-4 → expiry → next-start when the requested calendar/source coverage allows it, otherwise report the missing coverage. |
| `SYN-2M` | 2 calendar months | 1-second only where explicitly selected; otherwise declared base interval | 3 | Rollover and continuity validation across multiple monthly cycles. |
| `SYN-3M` | 3 calendar months | 1–5-second only for explicitly approved high-resolution strategy intervals; base profile may use 5-minute bars | 3 | Primary generator/replay contract and deterministic split/checkpoint validation. |
| `SYN-1Y` | 1 calendar year | Mostly 1-minute; high-resolution intervals are not the default | 2 | Longer lifecycle, rollover, and resource/capacity validation; no performance inference. |

All profile counts above are proposed configuration defaults, not immutable correctness constants. Record actual dates, sessions, contract coverage, event counts, row counts, and output bytes from emitted evidence. A missing authoritative calendar/master/underlying input remains BLOCKED; synthetic expiry derivation is permitted only under §2.2 and remains validation-only.

### 11.1 Event catalogue and invariants

`SYN-EVT` must have deterministic, separately named event cases covering at least: missing quote, delayed quote, duplicate event, zero/invalid quote, order-book gap, wide spread, insufficient depth, underlying gap, 1.3× volatility regime, two whipsaw reversals, trend and reversal, crash/rebound, D-4 transition, expiry cutoff, and recovery after a data-quality fault. The thresholds are config values only and must not be tuned in this phase. Each event case records seed, config hash, generator version, expected invariant, actual validator result, and source/provenance status.

No event case may bypass the normal public market-data interface, inject display/log-only values, create synthetic orders/fills, or relax orderbook gaps, limit-order wait/cancel, or one-order-at-a-time constraints. Limit fills require both price reach and adequate volume support in the existing Virtual Broker/execution implementation.

### 11.2 Monthly checkpoint and split equivalence

For `SYN-3M` and longer profiles, the design must support deterministic month-aligned checkpoints and resumable generation. A checkpoint must contain the profile/config hash, generator/rules versions, seed, source snapshot hashes, last committed deterministic event key, random-access/stream state (or stable-key derivation version), and per-output hashes. It must not contain credentials or mutable runtime order/position state.

Acceptance comparison must generate the same horizon both (a) as one uninterrupted run and (b) as month-aligned segments resumed from checkpoints. After canonical merge, compare ordered semantic rows, event IDs, counts, per-day bytes/hashes, and final manifest fields excluding explicitly nondeterministic operational metadata. Any mismatch is FAIL; a missing prerequisite or inability to execute is BLOCKED. Checkpoint/resume must not reset random-number consumption, change timestamps, or duplicate/drop boundary events.

## 12. Validation-only Option Master and identity boundary

- Treat the Option Master snapshot as validation input only unless its source, date, schema, completeness, and hash are verified. Preserve source-native codes separately from `synthetic_contract_id`.
- Until the production Standard `instrument_id` owner is resolved and approved, generated contracts remain namespaced synthetic identities. Set `identity_source_status=BLOCKED_IDENTITY_OWNER_UNRESOLVED`, `production_runtime_eligible=false`, and `validation_only=true` in every applicable manifest and runtime-health record.
- The synthetic expiry exception in §2.2 may fill scenario expiry dates only; it does not make the Option Master authoritative, validate production identity, or authorize REAL_VTS/Live consumption.
- Reject `synthetic: true` / `DERIVED_SCENARIO` at REAL_VTS and Live boundaries before strategy/order routing. A synthetic-capable validation runtime must use the public market-data provider contract and keep provenance visible end-to-end.
- If contract identity, expiry, multiplier, or required quote fields are missing/conflicting, mark the affected contract/input BLOCKED or UNAVAILABLE; never alias a synthetic ID to a production Standard ID.

## 13. High-resolution capacity and strategy interval scope

High-resolution generation is limited to the intervals explicitly needed to test Strategy 5 and Strategy 6. It must not silently make every strategy or every long-horizon profile run at one-second resolution. The selected interval for each strategy is a configuration input and remains unapproved until verified against the current strategy contract and source resolution.

Before implementation, estimate capacity from measured or reproducibly derived dimensions rather than a hard-coded row count:

`estimated_rows = trading_sessions × emitted_contracts_per_session × samples_per_contract_session + event_overhead`

`estimated_bytes = estimated_rows × measured_serialized_bytes_per_row + manifest/checkpoint/index overhead`

Report assumptions separately from measurements: session duration, interval, trading days, active contracts, contract churn, event overhead, bytes/row, peak working set, checkpoint size, and expected generation/replay throughput. Include a safety multiplier as a configurable planning assumption, not as a measured fact. Do not open or hash today's raw partition during the 08:29–16:01 KST guard. No capacity claim is PASS until measured on an isolated validation output with actual command output.

## 14. Specification acceptance and implementation gate

Before generator implementation, the user must review and explicitly approve this v0.2 specification. The implementation plan must then list exact files, backups/hashes for existing files to be edited, test cases, isolated output directory, rollback plan, and resource limits. Add acceptance tests before changing generator code.

Required acceptance extensions:

| ID | Test | Required outcome |
|---|---|---|
| P4-A15 | Validate-only Option Master and synthetic identity | No production Standard ID minted or aliased; production eligibility remains false |
| P4-A16 | SYN-EVT catalogue | Every configured event case has deterministic identity, expected invariant, and explicit PASS/FAIL/BLOCKED evidence |
| P4-A17 | Month-aligned checkpoint/resume vs one-shot | Ordered rows, event IDs, per-day bytes, and deterministic manifest fields match exactly |
| P4-A18 | Session-boundary provenance | 08:45/15:45/15:20 values are marked scenario assumptions until verified from KIS master/direct observations; no unsupported authoritative claim |
| P4-A19 | High-resolution scope and capacity | High resolution is restricted to approved Strategy 5/6 intervals; estimate inputs and measured values are distinguished |
| P4-A20 | Profile matrix | SYN-1M/2M/3M/1Y and SYN-EVT metadata, horizon, seeds, resolution, and actual coverage are recorded without hard-coded correctness counts |
| P4-A21 | Real-data boundary | Today's raw data is untouched during intraday guard; synthetic output is isolated and rejected by REAL_VTS/Live paths |

**v0.2 status:** specification draft only. No generator implementation, validator, tests, synthetic data, scheduler, Git staging/commit/push, or Decision Log registration is authorized by this document. Decision Log registration for the approved R1 policy set remains reserved for R7 as previously directed.