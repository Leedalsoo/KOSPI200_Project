# Runtime Order-Admission Path Coverage — v0.1
**Date:** 2026-10-14 KST  
**Status:** Static audit / draft / not approved / no runtime changes.  
**Purpose:** Identify where a future shared KIS provenance/freshness verdict must be enforced. This document is not an implementation authorization.

## 1. Confirmed shared boundaries

| Boundary | Actual code | Evidence from static inspection | Finding |
|---|---|---|---|
| KIS REST observation normalization | `infrastructure/kis/kis_rest_market_observation_normalizer.py::normalize` | Constructs `MarketObservation`; sets `observed_at=None`, `raw_reference=None` | Contract identity and timestamp equality checks exist; age/freshness result not computed |
| Observation contract | `contracts/types.py::MarketObservation`, `MarketDataProvenance`, `DataQuality` | Fields include source timestamps, collected/observed times, raw reference, quality status | Data structures exist; their required enforcement at order boundary is not proven |
| Virtual runtime assembly | `application/composition/virtual_runtime_data_provider.py::snapshot` | Builds runtime data from injected sources/ticks | Source-presence statuses are not proof of KIS source-age enforcement |
| Generic risk-to-router boundary | `core/runtime/reference_execution_pipeline.py::route_after_risk`, `route_from_authoritative_sources` | Calls `risk_gate.admit_order`; routes only after approval | Risk approval exists; no required KIS freshness verdict parameter observed |
| Virtual runtime risk/router adapter | `application/composition/runtime_authoritative_risk_router_adapter.py::route_from_runtime_authoritative_sources` | Builds account/position inputs, calls risk gate, requires token, routes | Shared virtual risk seam; no freshness verdict parameter observed |
| Order router | `core/oms/order_router.py::StandardOrderRouter.register_and_route` | Validates/registers order and routes with risk token | No independent raw market-data provenance/freshness validation established here |
| Live composition | `application/composition/live_runtime_authoritative_composition.py::create_authoritative_kis_live_runtime_composition` | Assembles futures market provider, Live broker, safety gate, execution and recovery components | Separate Live futures runtime graph; do not assume it is the S1–S9 option runtime path. `observed_at_resolver=lambda obs: obs.observed_at` forwards source field but does not prove an age limit |

## 2. Strategy 1–9 path coverage matrix

The static scan found strategy modules and shared risk/OMS seams, but did not prove all nine strategies' production callers from signal generation through final order admission. The matrix therefore records the shared seam as a candidate, not confirmed coverage.

| Strategy | Strategy module observed | Signal → command caller | Final risk/admission seam | Freshness verdict mandatory end-to-end | Status |
|---|---|---|---|---|---|
| S1 | `core/strategy/track1_tail_defense.py` | NOT_PROVEN | Candidate shared Risk/OMS seams above | NOT_PROVEN | BLOCKED |
| S2 | `core/strategy/track2_asymmetric_trap.py` | NOT_PROVEN | Candidate shared Risk/OMS seams above | NOT_PROVEN | BLOCKED |
| S3 | `core/strategy/track3_statistical_arbitrage.py` | NOT_PROVEN | Candidate shared Risk/OMS seams above | NOT_PROVEN | BLOCKED |
| S4 | `core/strategy/track4_gamma_scalping.py` | NOT_PROVEN | Candidate shared Risk/OMS seams above | NOT_PROVEN | BLOCKED |
| S5 | `core/strategy/track5_gap_divergence.py` | NOT_PROVEN | Candidate shared Risk/OMS seams above | NOT_PROVEN | BLOCKED |
| S6 | `core/strategy/track6_*` (exact active registry binding not proven) | NOT_PROVEN | Candidate shared Risk/OMS seams above | NOT_PROVEN | BLOCKED |
| S7 | `core/strategy/track7_volatility_skew_weekly_insurance.py` | NOT_PROVEN | Candidate shared Risk/OMS seams above | NOT_PROVEN | BLOCKED |
| S8 | `core/strategy/track8_*` (exact active registry binding not proven) | NOT_PROVEN | Candidate shared Risk/OMS seams above | NOT_PROVEN | BLOCKED |
| S9 | `core/strategy/track9_*` (exact active registry binding not proven) | NOT_PROVEN | Candidate shared Risk/OMS seams above | NOT_PROVEN | BLOCKED |

A strategy source file existing, being registered, or containing a signal method does not prove that its production route reaches the same admission seam. Exact registry binding, invocation chain, order transport, and fail-closed behavior need per-strategy caller tests.

## 3. Findings / blockers
1. KIS normalizer currently emits `observed_at=None` and `raw_reference=None`; source timestamp equality is not a max-age check.
2. No approved quote-age/future-skew/cross-leg skew policy is available. Do not add defaults.
3. The shared risk/router methods do not expose a required typed KIS freshness verdict in their visible signatures.
4. The Live authoritative composition shown here is a separate futures-focused graph; it cannot be assumed to cover option Strategy 1–9.
5. Full S1–S9 caller-chain proof remains incomplete; exact active registry bindings for S6/S8 were not proven by this pass.
6. VTS account/API registration binding remains unresolved from existing evidence (prior `90070000` response). Do not retry the same failing request until registration/account context is confirmed.
7. No valid LIVE credential key pattern was found in the checked `.env`; no LIVE endpoint was called.

## 4. Next steps (non-implementation)
1. Obtain explicit policy values for quote age by data type, authoritative timestamp field/timezone, future clock skew, multi-leg timestamp spread, and stale-data exposure-reduction policy.
2. Confirm the VTS account/API product binding through the account/API registration configuration; do not expose secret values.
3. Trace exact registry → strategy invocation → signal → command → risk gate → OMS → broker call chain for S1–S9, including S6/S8 active module binding.
4. Produce requirement → approved spec → code symbol → test ID → evidence path/hash mapping.
5. After user approval of the freshness policy and implementation scope, implement one common gate and new tests only. Do not restore deleted tests.
6. Run deterministic offline tests first; separate Virtual/replay, VTS read-only, VTS order evidence, and Live evidence. No Live orders without explicit separate approval.

## 5. Scope and safety
- Read-only static code inspection only.
- No strategy logic, architecture, risk limits, Manifest, or data threshold changed.
- No account/order/modify/cancel API call; no Live order.
- No test restoration, Git stage/commit/push, or deletion/cleanup of existing worktree content.
- Status of this document: **Draft / not approved / not an implementation basis**.
