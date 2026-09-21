# KIS REST Market Observation Archive Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve KIS VTS REST option snapshots as raw and canonical market observations that can traverse HistoricalMarketStore → Replay → MarketDataHub without breaking the existing tick contract.

**Architecture:** Add an environment-neutral observation contract in `contracts`, a KIS REST normalizer in `infrastructure`, and additive storage/replay adapters around the existing `ReferenceCanonicalMarketTick`. Keep raw payloads separate from canonical records and keep REST snapshot semantics explicit.

**Tech Stack:** Python 3, dataclasses, Decimal, JSONL, pytest, existing KIS adapter contracts, existing Virtual HistoricalMarketStore/Replay.

**Spec:** `docs/superpowers/specs/2026-09-21-kis-rest-market-observation-archive-replay.md`

## Global Constraints

- Python is executed with the Windows launcher `py`.
- Existing `reference-canonical-market-tick-v1` storage and replay behavior must remain compatible.
- Missing authoritative values remain absent/UNAVAILABLE; no zero/False/synthetic fallback is introduced.
- REST snapshots are never represented as WebSocket ticks.
- Raw records never contain App Key, App Secret, access token, or other credentials.
- No KIS real-account order path is added or invoked.
- Original, Scenario, and Synthetic provenance remain distinguishable.

## Review Focus

- Missing KIS contract identity must fail closed rather than create a guessed instrument.
- Missing order-book levels must remain absent rather than become zero-valued levels.
- KIS responses without an authoritative observation timestamp must retain `collected_at` without inventing `observed_at`.
- Quote and OrderBook responses with different source timestamps must not be silently treated as one simultaneous market event.
- A canonical REST observation must not accidentally enter the legacy tick path without an explicit projection.

### Task 1: Baseline and exact boundary inventory

**Files:**
- Read: `contracts/types.py`, `contracts/market_data.py`
- Read: `application/market_data_hub.py`, `application/historical_market_data_provider.py`
- Read: `environments/virtual/market/canonical.py`, `environments/virtual/market/historical_market_store.py`, `environments/virtual/market/replay_engine.py`
- Read: `infrastructure/kis/option_historical_recorder.py`
- Test: existing historical/replay test files identified by repository search

**Interfaces:**
- Confirm the exact existing `CanonicalMarketTick`, `ReferenceCanonicalMarketTick`, `HistoricalMarketStore`, and `HistoricalReplayEngine` signatures before editing.
- Preserve all unrelated working-tree changes in the user's main checkout.

- [ ] **Step 1: Verify isolated branch and baseline state.**
Run `git status --short` and `git branch --show-current` in the isolated worktree. Record any baseline test failures without modifying unrelated code.

- [ ] **Step 2: Run focused historical/replay tests.**
Run `py -m pytest -q tests/unit/test_historical_market_store.py tests/unit/test_historical_market_capture.py tests/unit/test_kis_option_historical_capture.py` and record the exact exit code.

- [ ] **Step 3: Search for all consumers of the existing historical schema.**
Run repository content search for `reference-canonical-market-tick-v1`, `ReferenceCanonicalMarketTick`, and `HistoricalReplayEngine` and map each consumer into the implementation plan before touching interfaces.

### Task 2: Add canonical observation and raw/provenance contracts

**Files:**
- Modify: `contracts/types.py`
- Modify: `contracts/market_data.py` only if the standard observation port requires an additive protocol
- Create: `tests/unit/test_market_observation_contract.py`

**Interfaces:**
- Produce immutable dataclasses for contract identity, quote, order-book levels, analytics, provenance/raw reference, and the top-level market observation.
- The top-level observation must expose `observation_id`, `observed_at`, `collected_at`, `source`, `provider`, `schema_version`, `run_id`, `contract`, `quote`, `order_book`, `analytics`, `provenance`, and raw reference information.

- [ ] **Step 1: Write failing tests for immutable observation construction.**
Test that a complete observation retains Decimal values, timestamps, contract identity, quote, order-book levels, analytics, source, provider, schema version, run ID, and raw reference without mutation.

- [ ] **Step 2: Write failing tests for missing identity and absent fields.**
Test that required broker symbol/identity is rejected or represented as explicit unavailable state, and that missing bid/ask levels and analytics remain `None` rather than zero-filled.

- [ ] **Step 3: Implement minimal immutable contracts.**
Use frozen dataclasses and typed mappings/sequences consistent with existing `contracts/types.py`; do not introduce KIS-specific response fields into Core contracts.

- [ ] **Step 4: Run the focused contract tests.**
Run `py -m pytest -q tests/unit/test_market_observation_contract.py` and require PASS before moving to the normalizer.

### Task 3: Implement KIS REST normalizer

**Files:**
- Create or modify: `infrastructure/kis/` KIS REST normalizer module selected from the boundary inventory
- Create: `tests/unit/test_kis_rest_market_observation_normalizer.py`
- Test fixtures: existing KIS fixture location selected from repository conventions

**Interfaces:**
- Consume parsed KIS REST price and asking-price payloads plus `collected_at`, `run_id`, and authoritative contract identity lookup.
- Produce one canonical observation only when the quote and order-book responses can be safely associated; preserve each endpoint/TR in provenance.

- [ ] **Step 1: Add a fixture from the verified VTS REST response shape.**
Include a real-shape option such as `B01610C41` with non-zero last/bid/ask/volume, strike/expiry identity, order-book levels, total quantities, and KIS analytics fields. Redact credentials and request secrets.

- [ ] **Step 2: Write failing normalization tests.**
Assert broker symbol, expiry, strike, option type, quote values, order-book levels, IV/delta, source, TR IDs, collection time, and run ID are preserved in the canonical observation.

- [ ] **Step 3: Write failing provenance tests.**
Assert price and asking-price endpoint metadata remain distinct beneath one observation and that a missing source timestamp does not become an invented `observed_at`.

- [ ] **Step 4: Implement the normalizer.**
Parse only fields present in the KIS payload; use `Decimal` for monetary/price quantities where the existing contracts do so; never synthesize contract identity or missing levels.

- [ ] **Step 5: Run normalizer tests.**
Run `py -m pytest -q tests/unit/test_kis_rest_market_observation_normalizer.py` and require PASS.

### Task 4: Add raw and canonical archive persistence

**Files:**
- Modify: `environments/virtual/market/historical_market_store.py`
- Create: focused archive/provenance helper module only if the existing store would otherwise mix schemas
- Create/modify: `tests/unit/test_historical_market_observation_store.py`

**Interfaces:**
- Add an explicit observation schema alongside, not instead of, `reference-canonical-market-tick-v1`.
- Add raw-record persistence that accepts sanitized request metadata, HTTP status, response metadata, payload, `collected_at`, and `run_id`.

- [ ] **Step 1: Write failing schema-separation tests.**
Verify legacy tick records remain loadable and new observation records use a distinct schema version.

- [ ] **Step 2: Write failing raw-secret exclusion tests.**
Attempt to persist metadata containing credential-like keys and verify the persistence boundary rejects or sanitizes those fields before writing.

- [ ] **Step 3: Write failing provenance-link tests.**
Verify canonical records reference the raw record/hash and preserve source, provider, TR/endpoint, collection time, and run ID.

- [ ] **Step 4: Implement additive store methods.**
Keep `append`, `append_many`, `records`, and `load_ticks` behavior unchanged for legacy data; add explicit observation/raw methods and schema dispatch.

- [ ] **Step 5: Run storage tests.**
Run `py -m pytest -q tests/unit/test_historical_market_observation_store.py tests/unit/test_historical_market_store.py` and require PASS.

### Task 5: Connect Observation to Replay without replacing the legacy path

**Files:**
- Modify: `environments/virtual/market/replay_engine.py` only through additive APIs
- Modify: `application/historical_market_data_provider.py` only where an explicit observation projection is needed
- Modify/create: `environments/virtual/market/canonical.py` only if the compatibility projection belongs there
- Create: `tests/unit/test_market_observation_replay.py`

**Interfaces:**
- Consume stored canonical observations selected by source/run ID.
- Produce an explicit `ReferenceCanonicalMarketTick` projection for legacy Runtime consumers, while retaining the observation outside that projection for provenance-aware consumers.

- [ ] **Step 1: Write failing projection tests.**
Verify a REST observation projects to the existing tick fields using authoritative values only and that legacy fixture replay remains unchanged.

- [ ] **Step 2: Write failing time-axis tests.**
Verify `observed_at` is preferred when authoritative, otherwise `collected_at` is used by an explicit rule; neither timestamp is silently relabeled as a fill time.

- [ ] **Step 3: Implement additive replay loading.**
Add observation-aware loading/projection without changing the existing `next_tick()` contract or rewriting historical JSONL.

- [ ] **Step 4: Run replay compatibility tests.**
Run `py -m pytest -q tests/unit/test_market_observation_replay.py tests/unit/test_historical_market_store.py tests/unit/test_historical_market_capture.py` and require PASS.

### Task 6: Add MarketDataHub integration and scenario provenance

**Files:**
- Modify: `application/market_data_hub.py` only if an additive observation snapshot/subscription port is required
- Modify: `application/historical_market_data_provider.py` for standard projection
- Create: `tests/integration/test_market_observation_archive_replay_hub.py`
- Create/modify: scenario provenance test module at the existing scenario-test location

**Interfaces:**
- MarketDataHub receives only standard contracts, never raw KIS payloads.
- Scenario transformation consumes a canonical observation and emits a separately identified scenario record containing source observation reference, scenario ID, transformation metadata, and independent run ID.

- [ ] **Step 1: Write failing Hub integration test.**
Construct a fixture observation, store it, replay it, project it through the historical provider, and assert Runtime-facing `MarketState` contains the expected canonical instrument/price without exposing KIS-specific payload fields.

- [ ] **Step 2: Write failing scenario provenance test.**
Verify transformed data has a different provenance identity and does not overwrite the original observation.

- [ ] **Step 3: Implement the smallest additive Hub/provider bridge.**
Do not add KIS-specific dependencies to `MarketDataHub`; keep provider-specific normalization below the application boundary.

- [ ] **Step 4: Run integration tests.**
Run `py -m pytest -q tests/integration/test_market_observation_archive_replay_hub.py` plus the scenario provenance test and require PASS.

### Task 7: Verification and VTS REST integration evidence

**Files:**
- Modify: no production files unless a test-discovered defect requires it
- Test: all new focused tests plus existing historical/replay suites

**Interfaces:**
- Use the project `.env` only through the existing KIS authentication boundary.
- Use the already verified VTS REST endpoints and real option symbol shape; never log secrets.

- [ ] **Step 1: Run focused regression.**
Run all new observation/normalizer/store/replay/Hub tests together with the existing historical and KIS option historical tests. Expected: PASS with exit code 0.

- [ ] **Step 2: Run a safe VTS REST integration probe.**
Use the existing VTS credentials through `KISAuthManager`, query one authoritative option, and verify Quote + OrderBook + identity + time-axis data can be normalized. Do not submit orders.

- [ ] **Step 3: Verify raw/canonical round trip.**
Persist one sanitized raw response and its canonical observation, reload both, and assert provenance and contract identity survive serialization.

- [ ] **Step 4: Run full regression.**
Run `py -m pytest -q`. Any pre-existing baseline failure must remain distinguished from this feature's failures.

- [ ] **Step 5: Run static hygiene checks.**
Run `git diff --check` and `py -m compileall -q application core contracts environments infrastructure tests`.

- [ ] **Step 6: Run Project200 deterministic gate.**
Run the repository's existing Project200 gate command exactly as documented by `AGENTS.md`. Treat Live runtime evidence as BLOCKED when Live credentials/frames are absent; do not weaken the gate to manufacture PASS.

- [ ] **Step 7: Inspect final diff and commit only intended files.**
Run `git status --short` and `git diff --stat`; exclude all unrelated pre-existing changes from the commit.

- [ ] **Step 8: Commit and push after verification.**
Use a focused commit message such as `feat: archive kis rest market observations`; push the isolated branch only after all feature verification is PASS and the Project200 gate has no feature-related FAIL.

- [ ] **Step 9: Verify remote state.**
Confirm the remote branch HEAD equals the pushed commit SHA and record the SHA, test results, and any Live BLOCKED status in Notion under the next `[No.xxx 답변내용요약]` page.

## Plan Self-Review

- Spec coverage: Sections 1–6 map to Tasks 2–3; Sections 7–9 map to Task 4 and Task 6; Sections 10–13 map to Task 5; Sections 14–17 map to Tasks 2–7.
- Placeholder scan: no TBD/TODO implementation placeholders are used; each implementation step names the boundary and verification command.
- Type consistency: observation contracts are introduced before the normalizer; storage consumes them before replay; replay projection remains compatible with the existing tick types.
- Review focus coverage: missing identity is tested in Task 2/3; missing levels in Task 2/3; missing timestamp in Task 3/5; source timestamp separation in Task 3/5; legacy projection isolation in Task 5/6.

## Execution Handoff

Implementation has not started. The isolated worktree is `feature/kis-rest-market-observation` under `.worktrees/kis-rest-market-observation`.
The current main checkout contains unrelated pre-existing changes that must remain untouched.
