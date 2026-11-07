# KIS Strategy Capability / Evidence Matrix v0.1
**As of:** 2026-10-14 KST  
**Status:** Evidence inventory only — not a strategy approval, not an execution authorization.

## Decision rules
- KIS API responses and official KIS master files are the only runtime authority.
- VTS and LIVE evidence are separate. VTS PASS never means LIVE PASS.
- A known endpoint/sample is not proof of complete coverage, freshness, live order readiness, or strategy readiness.
- Missing mandatory fields, incomplete identity/expiry/multiplier, unknown annual calendar, account binding errors, stale/unproven quotes, or unverified order/fill/position reconciliation keep the affected strategy BLOCKED.
- Do not alter strategy intent to accommodate API gaps. Do not infer missing fields or replace them with another runtime provider.

## Shared platform inputs

| Capability | Evidence available | Current decision |
|---|---|---|
| KIS option master | `verification/evidence/fo_idx_code_mts_20261014.zip`; 7,713 rows, SHA-256 `f0205b443b0680bcfc93d310a30636d4fa4a08ebc2a63c3742ad59cf38bf557e`; candidate option codes 5/6/D/E/L/M/N/O: 6,976 rows; weekly L/M/N/O: 474 rows | Master download PASS; complete identity/expiry/multiplier coverage NOT_PROVEN |
| Exact expiries | Existing KIS response evidence for 23 sampled expiries (15 monthly, 5 Thursday weekly, 3 Monday weekly) | Sample evidence only; full future coverage BLOCKED |
| Daily trading dates | KIS VTS `HHMCM000002C0`, HTTP 200 / `rt_cd=0`, rolling dates 2026-10-12 through 2026-10-16; common factory and consumers integrated | PASS_DAILY_SOURCE_INTEGRATED for dates explicitly returned |
| Annual holidays | VTS `CTCA0903R` 2026 and 2027 returned HTTP 500 / `EGW02006`; LIVE credentials unavailable | BLOCKED; no dates outside rolling response inferred |
| Option WebSocket quote | H0IOASP0 actual VTS frame count 0; user instructed to hold further attempts | BLOCKED; no inference that VTS does not support it |
| Option REST quote | Existing VTS option REST success sample (No.1252) | Endpoint/sample evidence only; does not replace WebSocket or prove every contract/field |
| Subscription coverage | Existing configuration: 29 subscriptions (26 monthly option trades + 2 futures trades + 1 index); weekly option 0, H0IOASP0 0, H0IFASP0 0 | Planner dry-run PASS; live collector integration/actual subscriptions not proven |
| Account / margin | VTS `VTFO6118R` returned HTTP 200, `rt_cd=1`, `msg_cd=90070000`; account number shape appears valid but binding unresolved | Account, balance, margin, buying power, and actual positions BLOCKED |
| Runtime freshness | REST normalizer checks response success, contract identity, underlying identity, and timestamp equality; no maximum age gate proven; `observed_at=None`, `raw_reference=None` | End-to-end provenance/freshness-to-order-admission BLOCKED / NOT_PROVEN |
| Cancel/fill recovery | G4 path traced in `07_g4_cancel_race_recovery_traceability_v0.1.md`; virtual cancel confirmation and durable idempotency unresolved | Live execution readiness BLOCKED |

## Strategy matrix

| Strategy | Required KIS-backed inputs | Evidence-backed partial capability | Missing mandatory evidence / blockers | Status |
|---|---|---|---|---|
| S1 — Monthly directional option selling + hedge | Exact monthly contract identity/expiry/multiplier; premium/quote; fills and positions; D-4 exit; flat confirmation | Monthly option master and sampled exact-expiry evidence; KIS REST quote sample exists | Complete expiry/multiplier coverage, quote freshness/orderbook coverage, account/position binding, cancel/late-fill reconciliation, annual calendar beyond rolling window | BLOCKED |
| S2 — Four-leg asymmetric options | Four exact monthly contracts; synchronized quotes/order books; BBW, volume z-score, OBI, basis, POC, IV with source lineage | Master candidates and a REST option quote sample | Actual H0IOASP0 frame evidence is held; complete four-leg synchronized inputs and documented KIS-derived analytics are not proven; account risk and G4 blockers | BLOCKED |
| S3 — Near/far futures calendar spread | Both exact futures identities/expiries/multipliers; synchronized quotes; fees/costs; two-leg fills and position reconciliation | Futures trade subscription slots are present in the existing collector configuration | Authoritative futures identity/multiplier coverage, synchronized quote evidence, complete costs and account-wide risk/fill reconciliation not proven | BLOCKED |
| S4 — Option-position delta hedge | Actual held option lots; KIS-validated Greeks/IV; hedge futures identity/quote; post-hedge position reconciliation | REST normalizer has fields for Greeks/IV and validates identity/timestamp consistency | Field-level real response validation, freshness bound, actual KIS position and account/margin binding, end-to-end hedge reconciliation | BLOCKED |
| S5 — Gap-direction ATM buy + opposite-option hedge | Session open/previous close with timestamps; exact ATM and opposite contract identities; quotes/fills; position reconciliation | KIS REST normalizer requires KOSPI200 underlying identity/price; monthly master evidence exists | Session/previous-close provenance and boundary semantics not proven; option WebSocket evidence held; no KRX runtime substitute; account/G4 blockers | BLOCKED |
| S6 — Daily sequential option buying | Exact daily target expiry; both legs’ identity/quote/fill/mark; sequencing and exposure limits | Monthly option master and REST sample evidence | H0IOASP0 frame evidence held; exact daily expiry coverage and synchronized quote/fill/position evidence incomplete | BLOCKED |
| S7 — Weekly sequential option buying | Exact weekly expiry; both legs’ liquidity/quotes; rank-5/rank-6 sequential orders and fills | Weekly master subset (474 rows) and 8 sampled Monday/Thursday expiry records within the 23-record set | Full weekly expiry coverage and live quote evidence absent; actual strategy selection/fill behavior not proven | BLOCKED |
| S8 — Monthly wide straddle buying | Exact monthly CALL/PUT identities; rank-5/rank-6 sequencing; per-leg fills, costs and P&L; account risk | Monthly master and sampled expiry evidence | H0IOASP0 frame evidence held; complete order-book, fills, cost/P&L and account risk/reconciliation not proven | BLOCKED |
| S9 — S1-linked OTM PUT insurance | KIS-confirmed S1 short-PUT residual position; exact insurance PUT identity/expiry/quote/fill; S1/S9 coordination | Shared monthly option master evidence | Actual S1 position unavailable due account binding; option quote frame held; D-4 S1 flat vs D-7 S9 retention conflict remains unresolved | BLOCKED |

## Evidence paths
- Master: `verification/evidence/fo_idx_code_mts_20261014.zip`
- Daily calendar: `verification/evidence/kis_daily_trading_day_provider_smoke_20261014.json`
- Shared calendar contract: `verification/evidence/shared_calendar_factory_contract_20261014.json`
- Annual holiday retry: `verification/evidence/kis_holiday_api_retry_20261014.json`
- Account binding: `verification/evidence/kis_vts_account_readonly_capability_20261014.json`, `verification/evidence/kis_vts_account_config_check_followup_20261014.json`
- G4 call path: `docs/strategy_specifications/07_g4_cancel_race_recovery_traceability_v0.1.md`

## Next work items
1. Obtain correct LIVE credentials before a read-only annual KIS holiday retry; do not reuse VTS credentials.
2. Resolve VTS account/API registration binding outside repeated API retries; then repeat only the approved read-only balance/position check.
3. Define and approve quote freshness limits before implementation; then add a common provenance/freshness gate and prove it reaches final order admission.
4. Build G4 tests only after the scenario/evidence mapping and explicit approval; do not restore deleted tests.
5. Keep H0IOASP0 on hold until explicitly instructed to resume.
