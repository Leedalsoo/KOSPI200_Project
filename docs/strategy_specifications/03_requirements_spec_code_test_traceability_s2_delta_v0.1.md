# Requirements–spec–code–test traceability — Strategy 2 delta v0.1

- 작성일: 2026-10-13; 상태: draft / unverified / unapproved.
- Existing `03_requirements_spec_code_test_traceability_v0.1.md`–`v0.4.md` and S5/S9 deltas are preserved. Planning only; no tests run/code edits.

## A. S2 F01–F29 traceability

| Req | Current spec | Code/source paths | Planned evidence | Status |
|---|---|---|---|---|
| S2-F01 | S2 spec v0.3 §1.1 | `core/strategy/track2_asymmetric_trap.py`; `core/oms/multi_leg_plan.py` | Exact-contract four-leg payoff/net cost/stress; no zero-cost assumption | NOT_RUN / BLOCKED |
| S2-F02 | §1.1 | `track2_option_contract_source.py`; Option Master; `resolve_track2` | Standard KOSPI200 only; Mini reject; contract IDs | NOT_RUN |
| S2-F03 | §1.4 | MarketSessionPolicy; KRX calendar; S2 state | Monthly start + 3 days; 15:00 entry cutoff; expiry 15:10; no same-expiry re-entry | NOT_RUN |
| S2-F04 | §1.3, §1.7 | `core/analytics/track2.py`; `track2_analytics_provider.py`; KIS metrics/IV source | Source/as-of/received time/unit/freshness/identity per feature | NOT_RUN |
| S2-F05 | §1.3 | `track2_asymmetric_trap.py`; `core/analytics/track2.py` | All feature conditions and boundary cases | NOT_RUN / definitions provisional |
| S2-F06 | §1.4–1.5 | S2 strategy state; group/order/position store | Active/pending/partial blocks duplicate entry; same expiry cannot re-enter | NOT_RUN |
| S2-F07 | §1.5 | `track2_execution_plan_adapter.py`; `core/oms/multi_leg_plan.py`; OMS/router | Exact sequence, 10-minute timeout, cancel-confirm and late-fill reconcile | NOT_RUN |
| S2-F08 | §1.2, §1.4 | `track2_option_contract_source.py`; Option Master/calendar | Exact YYYYMMDD, monthly series, standard product, listed strike/ATM tie-break | NOT_RUN / S2-U17 |
| S2-F09 | §1.2 | contract source; listed Option Master | wide/narrow offsets, listed strike/tick/rounding | NOT_RUN |
| S2-F10 | §1.2 | analytics provider; `track2_market_metrics_source.py`; `core/analytics/track2.py` | Ratio 0.8499/0.8500/0.8501; base<=0; insufficient sample | NOT_RUN |
| S2-F11 | §1.3 | metrics source; `track2_option_iv_source.py` | z/OBI/basis/POC thresholds, matched IV identity, missing/stale inputs | NOT_RUN |
| S2-F12 | §1.1, §2 | `core/risk/multi_leg_risk.py`; risk config/account/margin/fee providers | Qty 1/leg; null risk config blocks before first order | NOT_RUN |
| S2-F13 | §1.5 | `core/oms/multi_leg_plan.py`; adapter; OMS/router | Four sequential limit orders; no legacy 1-tick fallback; per-leg limit prices | NOT_RUN |
| S2-F14 | §1.7 | `core/risk/multi_leg_risk.py`; quote/contract/account sources | Any missing leg/cost/risk data blocks whole group before first order | NOT_RUN |
| S2-F15 | §1.5, S2-U16 | OMS/router; execution reports; position lots | Per-leg partial/reject/cancel race; no next leg until full fill/reconciliation; safe recovery | NOT_RUN / BLOCKED |
| S2-F16 | §1.1 | strategy plan/resolver; multi-leg adapter | Assert no unauthorized Futures/overlay leg | NOT_RUN |
| S2-F17 | §1.5–1.7, S2-U19 | fills, position lot store, account position read model | Side/qty/fill/mark/multiplier/group provenance reconciles | NOT_RUN / BLOCKED |
| S2-F18 | §1.6, S2-U18 | option mark/quote source; fills; P&L ledger | Option group P&L stop boundary after formula approved; no underlying proxy | NOT_RUN |
| S2-F19 | §1.6, S2-U18 | option marks/P&L ledger/high-water state | 30/50/100 tier boundaries using option P&L after formula approved | NOT_RUN |
| S2-F20 | §1.4, §1.6 | KRX calendar; expiry source; terminal batch | 15:09:59/15:10:00/15:10:01; no false flat | NOT_RUN |
| S2-F21 | §1.5–1.6, S2-U16 | OMS/router; position lot store; terminal batch | Close direction/remaining qty per actual lot; partial close/late fill | NOT_RUN |
| S2-F22 | §1.6, S2-U18 | execution fills; option marks; multiplier/fee/slippage ledger | Realized/unrealized group/account P&L and net-cost denominator | NOT_RUN / BLOCKED |
| S2-F23 | §1.6 | S2 strategy lifecycle | No `SHORT_SWITCH_TIMEOUT_EXIT`; exit pending suppresses entry; 15:10 terminal close | NOT_RUN |
| S2-F24 | §1.7, S2-U19 | run manifest; group/leg/order/execution IDs; position/P&L model | Config hash/provenance continuity across restart | NOT_RUN |
| S2-F25 | §1.5–1.7, S2-U19 | strategy persistence; OMS/router; position model | Restart with pending/cancel/late fill/stale timer; reconcile before resume | NOT_RUN |
| S2-F26 | §1.7 | common risk; S1/S6/S7/S8/S9 positions | Shared expiry/strike premium/margin/stress; no silent netting | NOT_RUN |
| S2-F27 | §1.3, §1.7 | analytics provider; metrics/IV/quote source | Missing/stale/identity mismatch yields BLOCKED/UNAVAILABLE | NOT_RUN |
| S2-F28 | §1.7, §2 | config loader; run manifest/hash; risk preflight | Null/provisional block; config version/hash recorded every run | NOT_RUN |
| S2-F29 | §10 | `tests/strategy/test_strategy2.py`; Virtual/REAL_VTS evidence | Exact test IDs/logs/dataset/config hash; tuning/validation split | NOT_RUN |

## B. Common completeness gates

| Gate | Trace requirement | Status |
|---|---|---|
| G01 | F01 + payoff/stress evidence | BLOCKED |
| G02 | F05/F10/F11 + threshold boundary evidence | BLOCKED |
| G03 | F02/F08/F09 + exact contract/expiry/multiplier evidence | BLOCKED |
| G04 | F07/F15/F21 + per-leg fill/cancel-race evidence | BLOCKED |
| G05 | F16 + no-extra-leg evidence | NOT_RUN |
| G06 | F18/F19/F20/F23 + option P&L/terminal close evidence | BLOCKED |
| G07 | F03/F20 + calendar/broker semantics | BLOCKED |
| G08 | F12/F14/F26/F28 + account risk enforcement | BLOCKED |
| G09 | F24/F25 + durable restore/reconciliation | BLOCKED |
| G10 | Every F linked to exact tests and logs | BLOCKED / NOT_RUN |
| G11 | S2-U16–U21 and dependencies registered | DRAFT |
| G12 | Verification separated from approval | Process PASS only; spec unapproved |

## C. Evidence boundary

Old test descriptions in v0.2 are historical coverage evidence, not v0.3 acceptance. Scenario IDs are planned groups, not claims that executable tests already exist. REAL_VTS must be distinguished from synthetic/derived data and Live. Every future run should record branch/commit, config version/hash, exact expiry, input source timestamps, per-leg orders/fills/cancel state, actual positions, P&L and logs. No tests were run in this task.
## S2-U20/U21 additional traceability

| ID | Requirement | Code/source | Planned evidence | Status |
|---|---|---|---|---|
| S2-U20 | Resolve zero-fill timeout/cancel-confirm progression versus abort; preserve no-next-leg-before-full-fill rule | S2 sequential state machine, OMS/router and monthly cycle state | zero fill timeout, cancel complete, fill-during-cancel, no following order before policy resolved | BLOCKED / NOT_RUN |
| S2-U21 | Versioned per-leg limit price basis, tick rounding, quote freshness and max spread | option quote source, `core/oms/multi_leg_plan.py`, execution router/config loader | null config blocks; stale/wide/missing quote; tick boundary; executable limit audit per leg | BLOCKED / NOT_RUN |