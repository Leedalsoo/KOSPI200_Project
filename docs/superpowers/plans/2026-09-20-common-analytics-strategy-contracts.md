# Common Analytics + Strategy Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 공통 시장분석/Greeks/지표 계산을 단일 Analytics 계층으로 이동하고 Strategy 2~9를 판단 전용 plug-in으로 이식한다.

**Architecture:** MarketDataHub가 canonical MarketSnapshot을 만들고 Analytics Engine이 active strategy들의 feature 요구를 union하여 한 번 계산한다. 각 Strategy는 immutable AnalyticsSnapshot과 자기 상태만 소비하며 Decision/Risk/OMS/Execution은 기존 표준 경계를 유지한다.

**Tech Stack:** Python, dataclasses/Protocol, pytest, 기존 Virtual Runtime/Hub, KIS/KRX adapters.

**Spec:** `docs/superpowers/specs/2026-09-20-common-analytics-strategy-contracts.md`

## Global Constraints
- Python 실행은 `py`를 사용한다.
- Real KIS 주문은 어떤 단계에서도 실행하지 않는다.
- authoritative source가 없으면 `UNAVAILABLE`/`BLOCKED`이며 fallback을 만들지 않는다.
- Strategy는 KIS/Broker/History/UI/Scenario Store를 직접 호출하지 않는다.
- identity/expiry/strike/option type/symbol/multiplier는 authoritative source에서만 공급한다.
- 같은 canonical input/as_of/window/version의 metric은 evaluation cycle에서 한 번만 계산한다.
- unrelated pre-existing worktree changes는 staging하지 않는다.

## Review Focus
- 동일 metric을 여러 전략이 요구할 때 실제 계산 횟수가 1회인지 → Task 3.
- history 부족/Greeks source 부족 시 zero/default가 아니라 unavailable인지 → Task 2/3.
- 서로 다른 timeframe/window가 cache collision을 일으키지 않는지 → Task 3.
- 전략 제거가 다른 전략의 snapshot/state를 바꾸지 않는지 → Task 4.
- 기존 identity/provenance/ExecutionReport 경계를 깨지 않는지 → Task 6.

### Task 1: Dependency Inventory and Contract Test Skeleton
**Files:** Create `tests/unit/analytics/`; Create `docs/superpowers/specs/`; inspect `core/strategy/track1~9_*.py`.
- [ ] 각 전략의 계산/외부호출/입력 dependency inventory를 고정한다.
- [ ] metric key naming/unit/timeframe 규칙 테스트를 먼저 작성한다.
- [ ] `py -m pytest` focused test를 실행해 RED를 확인한다.
- [ ] 테스트 실패가 계약 부재를 정확히 가리키는지 확인한다.

### Task 2: Public Analytics Contracts
**Files:** Create/modify `contracts/` analytics DTO/port files; tests in `tests/unit/analytics/`.
**Interfaces:** `MarketSnapshot`, `AnalyticsRequest`, `AnalyticsMetric`, `AnalyticsSnapshot`, `AnalyticsStatus`, `AnalyticsProvenance`.
- [ ] immutable DTO와 status/provenance 테스트를 작성한다.
- [ ] RED를 확인한다.
- [ ] 최소 계약을 구현한다.
- [ ] focused tests GREEN을 확인한다.

### Task 3: Single Analytics Engine
**Files:** Create `core/analytics/`; tests `tests/unit/analytics/`.
**Interfaces:** request union, dependency graph, metric evaluator, evaluation-cycle cache.
- [ ] same metric multi-consumer single-compute 테스트를 작성한다.
- [ ] missing dependency fail-closed 테스트를 작성한다.
- [ ] timeframe/window/version cache separation 테스트를 작성한다.
- [ ] RED를 확인한다.
- [ ] 최소 engine을 구현한다.
- [ ] GREEN 후 property/regression tests를 추가한다.

### Task 4: Strategy Plugin Contract
**Files:** modify `core/strategy/contracts.py`; add plugin requirement types; tests `tests/unit/strategy/`.
**Interfaces:** strategy feature declaration, required freshness/source status, immutable analytics view.
- [ ] strategy가 source를 직접 호출하지 않는 경계 테스트를 작성한다.
- [ ] feature declaration/availability 테스트를 작성한다.
- [ ] RED → minimal implementation → GREEN을 수행한다.

### Task 5: Strategy 2~9 Migration
**Files:** `core/strategy/track2_*.py` through `track9_*.py`, related materializers/providers/tests.
- [ ] 한 전략씩 기존 계산 owner를 Analytics로 이전한다.
- [ ] 이전 계산을 strategy에서 제거한다.
- [ ] strategy-specific state/rules만 남긴다.
- [ ] 각 전략 focused pytest를 GREEN으로 만든 뒤 다음 전략으로 이동한다.
- [ ] S2~S9 모두 같은 plugin harness에서 attach/detach를 검증한다.

### Task 6: Runtime/Execution Integration
**Files:** application composition/runtime hub and integration tests.
- [ ] Runtime에서 MarketSnapshot → AnalyticsSnapshot → StrategyContext 연결을 구현한다.
- [ ] Decision → Risk → OMS/Router → Broker → ExecutionReport identity/provenance 회귀를 검증한다.
- [ ] Virtual E2E를 실행한다.

### Task 7: Replay/VTS Parity
**Files:** replay/runtime integration and tests.
- [ ] Virtual과 Replay이 같은 Analytics implementation을 사용하는지 테스트한다.
- [ ] VTS provenance와 synthetic provenance를 분리한다.
- [ ] 실제 VTS 데이터가 필요한 부분은 데이터가 없으면 BLOCKED로 유지한다.

### Task 8: Full Verification and Cleanup
- [ ] focused suites.
- [ ] 필요한 Virtual E2E.
- [ ] `py -m pytest -q`.
- [ ] `py -m compileall -q application core contracts tests`.
- [ ] `git diff --check`.
- [ ] `py verification\project200_gate.py`.
- [ ] `git status`, local/remote HEAD 확인.
- [ ] migration으로 중복 계산/직접 source 호출이 남지 않았는지 정적 검색.

### Task 9: Git and Notion
- [ ] 의도된 파일만 stage.
- [ ] 검증 결과가 commit 조건을 충족하면 commit/push.
- [ ] remote `Project200` HEAD가 commit SHA를 가리키는지 확인.
- [ ] `[No.689 답변내용요약]`에 설계 승인, 실제 변경, 테스트, gate, SHA, push, BLOCKED 사항을 기록한다.

## Rollback
각 Task는 독립적으로 revert 가능한 작은 commit 단위로 유지한다. migration 중 실패하면 해당 전략만 이전 상태로 되돌리고 공통 Analytics 계약/테스트의 검증된 변경은 보존한다.