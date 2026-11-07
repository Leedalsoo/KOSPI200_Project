# Runtime Order-Admission Path Coverage v0.2
**Date:** 2026-10-14 KST  
**Status:** Static trace / draft / not approved / no runtime changes.  
**Supersedes:** v0.1 as the latest path-coverage snapshot; v0.1 remains historical evidence.

## 1. Confirmed Strategy registry and invocation

`core/strategy/standard_registry.py::build_standard_strategy_registry()` loads `config/strategies/strategy-manifest.v1.json`, requires exact strategy-ID set equality, validates code versions, instantiates each strategy, and registers it. `application/strategy_hub/hub.py::StrategyHub.run()` delegates to `core/strategy/orchestrator.py::StrategyOrchestrator.run()`. The orchestrator obtains each enabled strategy, validates its input/source declarations, calls initialize/on_market_state/evaluate, and returns signals/failures.

| Strategy | Active strategy ID / code version | Strategy class | Multi-leg resolver in `automated_virtual_runtime_factory.py` | Notes |
|---|---|---|---|---|
| S1 | `TRACK1_TAIL_DEFENSE` / `1.1.0` | `Track1TailDefense` | `resolve_track1` | Futures hedge/unwind may be converted to a multi-leg plan; non-futures proposal can use single-order path |
| S2 | `track2_asymmetric_trap` / `1.0` | `Track2AsymmetricTrap` | `resolve_track2` | Requires analytics/underlying before plan construction |
| S3 | `Strategy_3_StatArb` / `1.0` | `Track3StatisticalArbitrage` | `resolve_track3` | Futures identity and hedge identity are required for the non-synthetic runtime path |
| S4 | `track4_gamma_scalping` / `1.0` | `Track4GammaScalping` | `resolve_track4` | Futures hedge/unwind may use multi-leg bridge; option proposal can use single-order path |
| S5 | `track5_gap_divergence` / `2.0` | `Track5GapDivergence` | `resolve_track5` | Builds option/futures execution plan; exits may be constructed from open lots |
| S6 | `track6_daily_tail_insurance` / `1.0` | `Track6DailyTailInsurance` | `resolve_track6` | Active registry binding confirmed; entry plan and open-lot close path exist |
| S7 | `track7_volatility_skew_weekly_insurance` / `1.0` | `Track7VolatilitySkewWeeklyInsurance` | `resolve_track7` | Active registry binding confirmed; exact KIS option quote subscription/frame remains blocked |
| S8 | `track8_macro_regime_monthly_strangle` / `2.0` | `Track8MacroRegimeMonthlyStrangle` | `resolve_track8` | Active registry binding confirmed; resolver obtains `track8` by version `2.0` |
| S9 | `track9_event_overnight_insurance` / `3.0` | `Track9EventOvernightInsurance` | `resolve_track9` | Active registry binding confirmed; resolver obtains `track9` by version `3.0` |

Registry membership and resolver registration are confirmed from source code; this is not evidence that all inputs are available or that a signal has occurred in an actual KIS VTS run.

## 2. Confirmed shared Virtual route

`AutomatedVirtualTradingLoop.on_tick()` → runtime input/context builder → `StrategyHub.run()` / `StrategyOrchestrator.run()` → `RuntimeStrategyToDecisionAdapter.arbitrate()` → `DecisionArbiter` →
- single-order signal: `RuntimeDecisionCommandAdapter.build_commands()` → `AutomatedVirtualTradingLoop` command loop → `route_from_runtime_authoritative_sources()`; or
- multi-leg signal: `ExecutionMultiLegResolverRegistry.resolve()` → strategy-specific `resolve_trackN()` → `VirtualMultiLegExecutionBridge.execute()` → per-leg `route_from_runtime_authoritative_sources()`.

Common admission/submission path: `application/composition/runtime_authoritative_risk_router_adapter.py::route_from_runtime_authoritative_sources()` → `RiskGate.admit_order()` → approval token required → `core/oms/order_router.py::StandardOrderRouter.register_and_route()` → broker adapter `submit()` → OMS acknowledgement transition. The multi-leg path performs a group preflight and then routes individual legs through the same risk/router adapter. Actual fill/position reconciliation is a later boundary and is not implied by order submission.

## 3. Freshness coverage finding

- The REST normalizer reads `aspr_acpt_hour` from price/order-book responses, compares the two strings when both are present, and stores the raw value in provenance. It does not parse it into an absolute, timezone-aware source timestamp; `observed_at=None` and `raw_reference=None` remain.
- The WebSocket normalizer stores `received_at` as both `observed_at` and `collected_at`, while the source observation hour is retained as a string. This makes receive time available but does not prove that source-time age was computed.
- `route_from_runtime_authoritative_sources()` accepts order, risk gate, account/position/router context, and optional sensor snapshot; it has no required typed KIS freshness verdict parameter. `StandardOrderRouter` enforces a risk token but not source freshness/provenance independently.
- Therefore the Virtual strategy-to-risk/router route is traced, but **KIS source timestamp → canonical input → mandatory freshness verdict → every S1–S9 final admission** remains NOT_PROVEN. The Live composition is a separate futures-focused graph and is not proof of S1–S9 option Live coverage.

## 4. VTS account/API registration binding

Existing evidence `verification/evidence/kis_vts_account_readonly_capability_20261014.json` records `VTFO6118R` HTTP 200 with `rt_cd=1` and `msg_cd=90070000`. Configuration-only inspection previously established VTS mode, credential presence, account-number shape and product code 03, but did not establish the HTS user ID ↔ VTS account ↔ VTS AppKey/API product registration relationship. The local `.env` key-name check in this pass exposed only `KIS_MODE` among the queried names; no secret values were read or printed. Do not retry the same account endpoint or any order endpoint until the association is confirmed outside the failed response.

## 5. Status

| Work item | Status | Reason |
|---|---|---|
| S1–S9 registry/class/version binding | PASS_STATIC | Exact standard registry IDs and code versions matched to the resolver registrations |
| S1–S9 Virtual strategy-to-order admission map | PASS_STATIC_WITH_LIMITS | Shared path traced; per-run signal/REAL_VTS end-to-end evidence not claimed |
| KIS freshness enforcement on every final admission | BLOCKED / NOT_PROVEN | No required typed freshness verdict at the shared seam; REST absolute timestamp unresolved |
| VTS account/API registration binding | BLOCKED | `90070000` and registration/user association unresolved |
| Live KIS S1–S9 end-to-end path | BLOCKED | Separate Live graph and credentials/evidence do not prove option-strategy coverage |

## 6. Next actions

1. Prepare the freshness-policy decision sheet without inventing thresholds or timestamp semantics.
2. Confirm VTS account/API product registration via KIS Developers/HTS configuration without exposing credentials; then decide whether an approved read-only retry is warranted.
3. Build requirement → strategy ID/version → context/input → signal → execution plan → admission → OMS/broker → fill/position evidence traceability for each S1–S9 path.
4. After policy approval, report the exact file-level implementation scope and test plan for separate approval before changing runtime code.

## 7. Execution boundary

Static read-only source inspection only. No runtime code, strategy logic, Manifest, account config, tests, data files, Git staging/commit/push, or order/modify/cancel endpoint was changed or invoked. No tests were run in this pass. Existing worktree modifications/deletions/untracked files were preserved.
