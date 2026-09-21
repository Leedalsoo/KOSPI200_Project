# KIS REST 실제 시장데이터 수집기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** authoritative Option Master 대상만 VTS REST 1 req/sec 예산 안에서 Price + OrderBook을 수집하고 Raw + Canonical Observation을 Historical Store와 Replay로 연결한다.

**Architecture:** `KISRestMarketObservationCollector`가 인증, 대상 계약, rate limiter, Price/OrderBook transport, 기존 normalizer, HistoricalMarketStore를 조합한다. 각 cycle은 run/cycle/request provenance를 보존하고 Raw hash와 canonical Observation을 연결하며, 실패 시 canonical 승격을 차단한다. Replay는 기존 Observation store/replay 경계를 재사용한다.

**Tech Stack:** Python, pytest, urllib.request, existing KISAuthManager, existing KISRestMarketObservationNormalizer, HistoricalMarketStore JSONL, Project200 verification gate.

**Spec:** `docs/superpowers/specs/2026-09-21-kis-rest-market-observation-collector.md`

## Global Constraints

- authoritative Option Master가 제공한 계약만 수집하며 symbol/contract identity가 불완전하면 fail-closed한다.
- VTS REST 계좌별 1 req/sec 제한을 넘지 않으며 Price와 OrderBook 사이에도 limiter를 적용한다.
- 실제 KIS 주문 API는 호출하지 않는다.
- Raw KIS response와 Canonical Observation을 함께 보관하고 credential은 Raw에 저장하지 않는다.
- `observed_at`은 KIS가 제공할 때만 사용하고 REST snapshot을 WebSocket tick으로 재해석하지 않는다.
- KIS 응답에 없는 값을 0/False/fixed/synthetic 값으로 채우지 않는다.
- Original / Scenario / Synthetic provenance와 Run ID를 분리한다.
- Live credentials가 없는 동안 Live evidence는 BLOCKED이며 VTS 결과로 대체하지 않는다.
- 검증 명령은 Windows `py` launcher를 사용한다.

## Review Focus

- 동일 cycle의 Price/OrderBook timestamp 불일치 → canonical Observation을 생성하지 않는다.
- 1 req/sec 미만 요청 간격 보장 → 두 REST 호출 사이에도 limiter가 실제 대기한다.
- Option Master identity 누락/불완전 → 대상에서 제외하고 BLOCKED/UNAVAILABLE 결과를 남긴다.
- Raw 저장 후 canonical 저장 실패 → 불완전 cycle을 정상 Observation으로 노출하지 않고 재처리 provenance를 남긴다.
- 동일 응답 중복 → raw hash/observation identity로 중복 승격을 방지한다.

### Task 1: Collector transport/rate-limit contract

**Files:**
- Create: `infrastructure/kis/kis_rest_market_observation_collector.py`
- Test: `tests/unit/test_kis_rest_market_observation_collector.py`

**Interfaces:**
- `KISRestMarketObservationCollector(identity_source, auth, store, normalizer, transport, clock, limiter)`
- `collect_cycle(targets, run_id, cycle_id) -> tuple[CollectionResult, ...]`
- transport must expose `request_price(symbol)` and `request_order_book(symbol)`.
- result preserves symbol, run_id, cycle_id, request sequence, timestamps, status/reason, observation_id.

- [ ] **Step 1: Write the failing test for two requests being rate-limited**
- Test records request timestamps and asserts the second request is not issued before the configured one-second interval.

- [ ] **Step 2: Run the focused test and verify RED**
Run: `py -m pytest -q tests/unit/test_kis_rest_market_observation_collector.py::test_price_and_orderbook_requests_respect_one_second_interval`
Expected: FAIL because the collector module/class does not yet exist.

- [ ] **Step 3: Write minimal limiter and collector skeleton**
Implement a monotonic-clock based limiter with `wait()`; do not use sleep on the first request.

- [ ] **Step 4: Run the focused test and verify GREEN**
Run the same command.
Expected: PASS.

- [ ] **Step 5: Commit**
`git add tests/unit/test_kis_rest_market_observation_collector.py infrastructure/kis/kis_rest_market_observation_collector.py && git commit -m "feat: add KIS REST collector rate limit boundary"`

### Task 2: Authoritative target selection and fail-closed cycle handling

**Files:**
- Modify: `infrastructure/kis/kis_rest_market_observation_collector.py`
- Test: `tests/unit/test_kis_rest_market_observation_collector.py`

**Interfaces:**
- identity source returns authoritative `OptionInstrumentIdentity` records.
- collector accepts only targets whose identity contains non-empty `instrument_id` and `symbol`.
- invalid targets produce `AUTHORITATIVE_OPTION_IDENTITY_REQUIRED` without any REST request.

- [ ] **Step 1: Write failing tests for missing and incomplete identities**
Assert no transport calls occur and result status is BLOCKED/UNAVAILABLE with the explicit reason.

- [ ] **Step 2: Run tests to verify RED**
Run: `py -m pytest -q tests/unit/test_kis_rest_market_observation_collector.py -k identity`
Expected: FAIL on the new result behavior.

- [ ] **Step 3: Implement target filtering**
Resolve identity before scheduling requests; never synthesize symbol, strike, expiry, option type, or multiplier.

- [ ] **Step 4: Run focused tests to verify GREEN**
Run the same command.
Expected: PASS.

- [ ] **Step 5: Commit**
`git add infrastructure/kis/kis_rest_market_observation_collector.py tests/unit/test_kis_rest_market_observation_collector.py && git commit -m "feat: enforce authoritative option targets"`

### Task 3: Raw + canonical archive linkage and hash

**Files:**
- Modify: `infrastructure/kis/kis_rest_market_observation_collector.py`
- Modify: `environments/virtual/market/historical_market_store.py`
- Test: `tests/unit/test_kis_rest_market_observation_collector.py`

**Interfaces:**
- Raw record receives `raw_id`, endpoint/TR, collected_at, run/cycle metadata, sanitized request/response metadata, payload, HTTP status.
- canonical Observation receives `RawMarketDataReference(raw_id, content_hash)`.
- raw hash is deterministic over the stored raw payload pair.

- [ ] **Step 1: Write failing test for Raw/canonical linkage**
Assert both raw records exist, canonical raw_reference points to the raw hash, and credentials never enter the archive.

- [ ] **Step 2: Run test to verify RED**
Run: `py -m pytest -q tests/unit/test_kis_rest_market_observation_collector.py -k archive`
Expected: FAIL because collector does not yet persist the linked pair.

- [ ] **Step 3: Implement sanitized raw persistence and canonical linkage**
Persist Price and OrderBook raw responses before canonical append; only attach canonical reference after both raw writes and normalization succeed.

- [ ] **Step 4: Run focused archive tests**
Expected: PASS.

- [ ] **Step 5: Commit**
`git add infrastructure/kis/kis_rest_market_observation_collector.py environments/virtual/market/historical_market_store.py tests/unit/test_kis_rest_market_observation_collector.py && git commit -m "feat: link KIS raw responses to observations"`

### Task 4: KIS REST transport using existing auth and official TRs

**Files:**
- Modify: `infrastructure/kis/kis_rest_market_observation_collector.py`
- Test: `tests/unit/test_kis_rest_market_observation_collector.py`

**Interfaces:**
- Price endpoint: `/uapi/domestic-futureoption/v1/quotations/inquire-price`, TR `FHMIF10000000`.
- OrderBook endpoint: `/uapi/domestic-futureoption/v1/quotations/inquire-asking-price`, TR `FHMIF10010000`.
- transport obtains auth headers from existing `KISAuthManager`; it never invokes any order/submit endpoint.

- [ ] **Step 1: Write failing transport tests**
Use a deterministic injected HTTP opener and assert exact endpoint, TR ID, symbol request parameter, and response propagation.

- [ ] **Step 2: Run tests to verify RED**
Run: `py -m pytest -q tests/unit/test_kis_rest_market_observation_collector.py -k transport`
Expected: FAIL because transport methods are absent.

- [ ] **Step 3: Implement minimal GET transport**
Use `urllib.request.Request`; parse JSON; preserve HTTP status and raw KIS payload; map non-2xx/network failures to explicit collection failure without retry storms.

- [ ] **Step 4: Run focused transport tests**
Expected: PASS.

- [ ] **Step 5: Commit**
`git add infrastructure/kis/kis_rest_market_observation_collector.py tests/unit/test_kis_rest_market_observation_collector.py && git commit -m "feat: add KIS REST price orderbook transport"`

### Task 5: Normalizer integration and fail-closed response validation

**Files:**
- Modify: `infrastructure/kis/kis_rest_market_observation_collector.py`
- Test: `tests/unit/test_kis_rest_market_observation_collector.py`

- [ ] **Step 1: Write failing tests for rt_cd failure, timestamp mismatch, missing market value, and identity mismatch**
Expected result: no normal Observation is stored.

- [ ] **Step 2: Run focused tests to verify RED**
Run: `py -m pytest -q tests/unit/test_kis_rest_market_observation_collector.py -k fail_closed`
Expected: FAIL on at least one new behavior.

- [ ] **Step 3: Integrate existing KISRestMarketObservationNormalizer**
Map its explicit exceptions to collection results; do not manufacture fallback values.

- [ ] **Step 4: Run focused tests**
Expected: PASS.

- [ ] **Step 5: Commit**
`git add infrastructure/kis/kis_rest_market_observation_collector.py tests/unit/test_kis_rest_market_observation_collector.py && git commit -m "feat: fail closed on invalid KIS observations"`

### Task 6: Replay provenance and duplicate prevention

**Files:**
- Modify: `environments/virtual/market/historical_market_store.py`
- Modify: existing replay adapter only if required by current Observation replay boundary.
- Test: `tests/unit/test_kis_rest_market_observation_collector.py`
- Test: existing Observation replay tests as needed.

- [ ] **Step 1: Write failing tests for duplicate raw hash and Original/Scenario separation**
Original records must remain immutable; scenario transformation must use an independent run ID/source and must not overwrite original records.

- [ ] **Step 2: Run tests to verify RED**
Run: `py -m pytest -q tests/unit/test_kis_rest_market_observation_collector.py -k provenance`
Expected: FAIL on duplicate/separation behavior.

- [ ] **Step 3: Implement idempotent observation/raw lookup and explicit provenance checks**
Do not deduplicate across different contract identities or different raw payloads.

- [ ] **Step 4: Run focused replay/provenance tests**
Expected: PASS.

- [ ] **Step 5: Commit**
`git add environments/virtual/market/historical_market_store.py tests/unit/test_kis_rest_market_observation_collector.py && git commit -m "feat: preserve observation replay provenance"`

### Task 7: Real VTS one-cycle collector integration

**Files:**
- Create/Modify: `infrastructure/kis/kis_rest_market_observation_collector.py`
- Test: `tests/integration/test_kis_rest_market_observation_collector_vts.py` only if an existing integration convention requires it.
- Test data: authoritative Option Master already present in repository; credentials remain external.

- [ ] **Step 1: Add a guarded VTS integration test/runner that is skipped or BLOCKED when credentials are absent**
The test must never call order endpoints and must not print tokens.

- [ ] **Step 2: Run without forcing credentials**
Expected: explicit BLOCKED/SKIPPED when credentials are unavailable, not PASS.

- [ ] **Step 3: Run one real VTS cycle only when existing VTS credentials are present**
Target a contract already proven to return real values, such as the authoritative `B01610C41` identity used by No.706/707, and collect exactly one Price + OrderBook cycle with the 1 req/sec limiter.

- [ ] **Step 4: Verify archive/replay round-trip**
Load the stored Observation and replay it through the existing Observation replay boundary at 1x and accelerated timing without changing contract identity or market values.

- [ ] **Step 5: Commit only after verification**
Commit the integration implementation/test changes; never commit `.env`, token cache contents, or collected credentials.

### Task 8: Full Project200 verification and documentation

**Files:**
- Modify: Notion `질문과답변` with next `[No.xxx 답변내용요약]`.
- Repository docs only if a permanent implementation record is required.

- [ ] **Step 1: Run focused collector tests**
`py -m pytest -q tests/unit/test_kis_rest_market_observation_collector.py`

- [ ] **Step 2: Run full regression**
`py -m pytest -q`

- [ ] **Step 3: Compile and diff checks**
`py -m compileall -q application core contracts environments infrastructure tests`
`git diff --check`

- [ ] **Step 4: Run Project200 gate**
`py verification/project200_gate.py`
Record individual PASS/FAIL/BLOCKED results; Live credential evidence remains BLOCKED until real Live credentials/frame evidence exists.

- [ ] **Step 5: Verify git state and remote HEAD**
Run `git status --short --branch` and verify `origin/Project200` points to the intended commit SHA.

- [ ] **Step 6: Record Notion evidence**
Record purpose, files changed, focused/full test results and exit codes, compile/diff/gate results, commit SHA, push state, and remaining Live BLOCKED status.
