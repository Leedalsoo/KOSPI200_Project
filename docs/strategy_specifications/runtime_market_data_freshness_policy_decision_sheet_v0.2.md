# Runtime Market-Data Freshness Policy Decision Sheet v0.2
**Date:** 2026-10-14 KST  
**Status:** Numeric proposal for user decision / NOT APPROVED / no runtime changes.  
**Supersedes:** v0.1 as the current policy proposal; v0.1 remains historical evidence.

## 1. Official KIS evidence and what it proves

1. KIS official sample `examples_user/domestic_futureoption/domestic_futureoption_functions_ws.py` defines `H0IOCNT0` as index-option real-time trade-price data and includes `bsop_hour` among its fields. Its docstring explicitly says live accounts only; VTS is not supported. The adjacent `H0IOASP0` index-option quote function likewise says live accounts only; VTS is not supported. Source: https://github.com/koreainvestment/open-trading-api/blob/main/examples_user/domestic_futureoption/domestic_futureoption_functions_ws.py (functions `index_option_realtime_conclusion` and `index_option_realtime_quote`).
2. KIS Developers portal search for `H0IOCNT0` returns the official API document `[국내선물옵션] 실시간시세 / 지수옵션 실시간체결가[실시간-014]`. The public sample identifies `bsop_hour` as a returned field but does not establish its timezone, date association, or whether it represents event time versus a business-time label.
3. The KIS Developers portal search for `aspr_acpt_hour` returns the official REST `선물옵션 시세호가[v1_국내선물-007]` endpoint. The public search/detail surface inspected did not establish a complete date+timezone interpretation for this field.
4. Existing sanitized VTS REST capability evidence `verification/evidence/kis_api_capability_probe_20261014.json` shows `FHMIF10010000` response `aspr_acpt_hour` raw value `154500`, received around `2026-10-14 00:44 KST` (UTC evidence time `2026-10-13T15:44Z`). Because the response field has only time-of-day and no source date, it cannot safely be assigned to the receive date; it may represent the prior session's close. This sample is evidence of the ambiguity, not proof of actual source age.
5. The official KIS portal's VTS notice says `90070000` can occur when the HTS ID changed or the paper/live account was confused; it directs users to verify the VTS account separately from API application status and to remove old-ID application records before reapplying where applicable. Source: https://apiportal.koreainvestment.com/ (official “모의투자 API 사용 안내” notice). No account repair was performed.

## 2. Proposed numerical policy — requires explicit approval

These are conservative **candidate values**, not values proven by KIS documentation or market-cadence sampling. Do not implement until the user approves them and timestamp semantics/date association are documented.

| Parameter | Proposed candidate | Applicability / reason | Current enforceability |
|---|---:|---|---|
| WebSocket source quote/trade age | `<= 2,000 ms` | From parsed source event time to admission evaluation; only when the field is proven to be source event time and date/timezone is known | BLOCKED: `bsop_hour` semantics not fully documented; H0IOCNT0/H0IOASP0 are documented as LIVE-only, not VTS |
| REST source quote age | `<= 2,000 ms` | From parsed KIS source timestamp to admission evaluation; REST response receipt time alone does not satisfy this | BLOCKED: `aspr_acpt_hour` date/timezone and event semantics not proven; sample is time-of-day only |
| Allowed future source-time skew | `<= 1,000 ms` | Source timestamp may be ahead of trusted UTC receive/evaluation clock by at most 1 second; larger skew => `CONFLICT` | BLOCKED until source time can be parsed as an absolute instant and host clock is monitored |
| Maximum multi-leg source-time spread | `<= 1,000 ms` | Compare absolute source event instants across every required leg/input; missing source instant makes the group `UNKNOWN` | BLOCKED until source timestamps are absolute; second-resolution fields cannot substantiate sub-second spread |
| Collector receive-time skew diagnostic | `<= 500 ms` | Difference between leg receive times is diagnostic only; it cannot replace source-time coherence | Measurable after collector timestamps are consistently UTC-aware; not a substitute for source-time check |
| Missing/ambiguous timestamp | No numeric grace period; `UNKNOWN` | Fail-closed for new entries, adds, or other risk-increasing orders | Enforceable as interim policy only if wired into the admission path; currently not proven wired |

**Approval request:** approve/revise each numerical candidate and confirm that they remain provisional until the source timestamp field semantics are proven. If the user does not approve, all numeric policy values remain UNSET and no runtime gate implementation may begin.

## 3. Proposed stale-data exposure policy — requires explicit approval

- **New entry / add / increase risk:** deny if any required input is `STALE`, `UNKNOWN`, `CONFLICT`, wrong contract, or from an unsupported environment.
- **Close/reduce/hedge:** no blanket exception based on stale data. Automated reduction is permitted only when the current executable-side quote for the exact contract is independently `FRESH`, the actual position quantity is reconciled, and open/pending/cancel/fill states are reconciled. The reduction order must be marked reduce-only at the strategy/OMS policy layer and must not increase account-wide exposure.
- **No fresh executable quote or incomplete reconciliation:** automated close/hedge remains `BLOCKED`; raise an operational/manual-intervention alert. Do not estimate price from an old quote, substitute another source, assume flat, or send a speculative market order.
- **Partially filled multi-leg exposure:** reconcile every leg and outstanding order first. Do not submit a replacement leg or reset the strategy solely because a cancel was requested.

This policy intentionally has **no stale-quote age exception** for order execution. It distinguishes an existing position requiring attention from permission to trade on untrustworthy prices.

## 4. VTS account/API registration check required (no API retry)

Official KIS guidance indicates that `90070000` may be caused by HTS ID change or confusion between VTS and live accounts, and says the API application list and actual VTS account list are separate. User must verify, in the authenticated KIS Developers/HTS UI, without sharing secrets:

1. The HTS ID used for the currently issued VTS AppKey is the current HTS ID.
2. The selected account is the actual VTS futures/options account (not a live account; KIS notice says paper accounts beginning with `6` are futures/options).
3. The VTS account shown in the trading app/site's simulated futures/options balance matches the account selected for the API application.
4. The API application page's selected account/product is VTS domestic futures/options, and the AppKey belongs to that same current HTS ID.
5. If the HTS ID was changed, follow the official portal's “ID 변경 전 신청정보 삭제” procedure and reapply only after verifying the correct VTS account. Do not expose AppKey/AppSecret or full account numbers in chat/Notion.

After confirmation, report only a masked account suffix and confirmation of HTS ID / VTS account / product registration match. Do not repeat the same API request until this manual binding check is complete and a read-only retry is separately approved.

## 5. Implementation gate and proposed file scope (not authorization)

After timestamp semantics and policy approval, present a separate implementation approval request. Candidate scope only:
- `infrastructure/kis/kis_rest_market_observation_normalizer.py`: preserve raw source time and parse an absolute instant only if documented date/time semantics permit it; otherwise mark `UNKNOWN`.
- `infrastructure/kis/kis_websocket_market_observation_normalizer.py`: preserve `source_event_at` separately from `received_at`; never label receive time as source time.
- `contracts/types.py`: typed freshness state/verdict, source event time, evaluation time, policy version, reason, and evidence reference as needed.
- Shared admission boundary in `application/composition/runtime_authoritative_risk_router_adapter.py` and/or a common pre-admission policy component: require the verdict before `RiskGate.admit_order()` for single-order and each multi-leg leg.
- New tests/evidence only; do not restore deleted tests. Test `FRESH`, `STALE`, `UNKNOWN`, `CONFLICT`, future skew, cross-leg spread, source date rollover, unsupported VTS WS source, partial fill/cancel race, stale exposure, and reconciliation blockers.

No code change, test creation/execution, order API call, credential access, Git staging/commit/push, or account retry is authorized by this proposal.

## 6. Current state

- REST absolute source timestamp/date/timezone: `BLOCKED / NOT_PROVEN`.
- KIS official WS sample indicates H0IOCNT0 and H0IOASP0 index-option feeds are LIVE-only, not VTS; no retry performed. VTS WS index-option feed coverage: `UNAVAILABLE_BY_OFFICIAL_SAMPLE` pending current portal confirmation if needed.
- Numerical freshness thresholds: proposed only; user approval pending.
- Stale-position handling: proposed only; user approval pending.
- VTS account/API binding: `BLOCKED` until user confirms UI registration; no same-request retry.
- Common final-admission freshness enforcement: `BLOCKED / NOT_PROVEN`.
