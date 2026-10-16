# Strategy 1–9 integrated decision matrix — Strategy 2 delta v0.4

- 작성일: 2026-10-13; 상태: draft / unverified / unapproved.
- 기존 `02_decision_factor_integrated_design_matrix_v0.3.md` 및 이미 존재하는 overall v0.4–v0.7 파일은 보존한다. 이 문서는 S2 delta이며 전체 matrix를 대체하지 않는다.
- Basis: `strategy_2_asymmetric_trap_spec_v0.3.md` §1. No code/test/commit/push/Live order.

## 1. F01–F29 classification

| Classification | F IDs | Count | Meaning |
|---|---|---:|---|
| 확정 해결 | F01,F02,F03,F05,F06,F07,F09,F12,F13,F16,F20,F23,F25 | 13 | Intent/policy confirmed only; not implementation PASS |
| 설정 이관 | F04,F10,F11,F14,F18,F19,F26,F27,F28 | 9 | Versioned settings/source gates; null or PROVISIONAL blocks entry |
| 사용자 확인 필요 | F08,F15,F17,F21,F22,F24,F29 | 7 | New ambiguity/evidence gap; see S2-U16–U21 |

## 2. S2 I01–I16 interaction register delta

| ID | Interaction | Updated S2 target | Status |
|---|---|---|---|
| I01 | Capital/premium/max-loss/margin | Reserve one four-leg group budget before first leg; versioned editable settings; null blocks | 설정 이관 / BLOCKED |
| I02 | Shared Futures hedge identity | S2 has no Futures hedge/conversion | 확정 해결 for S2 only |
| I03 | Option lots/Greeks ownership | Strategy/group/leg ownership and actual fills required; no assumed hedge credit | 사용자 확인 필요 / BLOCKED |
| I04 | Overlapping insurance/correlated tail | Aggregate S2 with S1/S6/S7/S8/S9 by expiry, strike, premium, margin, stress | 설정 이관 / BLOCKED |
| I05 | Multi-leg partial/cancel race | Inner PUT BUY → inner CALL BUY → outer PUT SELL → outer CALL SELL; cancel-confirm/fill reconciliation before next leg; recovery S2-U16 | Policy set; runtime unverified |
| I06 | Strategy/account P&L | Option-group mark/fill P&L replaces underlying proxy; multiplier/fees/slippage attributed by actual lot | 설정 이관 / BLOCKED |
| I07 | Expiry/session/overnight | Monthly only; first 3 days entry, daily 15:00 cutoff, expiry day 15:10 close; calendar proof pending | Policy set; source unverified |
| I08 | Exit trigger priority | 15:10 terminal close intent; exit-pending blocks entry; no completion until actual flat | Policy set; runtime unverified |
| I09 | Freshness/unavailable | Fail-closed on missing/stale/mismatch; freshness settings and enforcement verified separately | 설정 이관 / BLOCKED |
| I10 | Restart/idempotency | Reconcile orders/fills/positions/config before resume; no reset before flat; durable proof S2-U19 | Policy set; runtime unverified |
| I11 | S5 Futures role | S2 does not use/convert Futures; S5 role remains separate | 확정 해결 for S2 only |
| I12 | S3 spread identity | S2 is not a Futures spread; S3 remains separate | 확정 해결 for S2 only |
| I13 | S4 hedge ownership | Keep S2 option inventory separate from S4 delta/hedge inventory | 사용자 확인 필요 for cross-strategy integration |
| I14 | S8 add-on/resolver | Never reinterpret S2 four-leg entry as single PUT SELL or other structure | Intent set; code mismatch remains |
| I15 | Re-entry | One cycle per monthly expiry; no same-expiry re-entry; account exposure still aggregated | Policy set; cross-strategy validation pending |
| I16 | Editable config consistency | Version/hash/effective settings logged; null/provisional critical value blocks | 설정 이관 / BLOCKED |

## 3. Global U01–U15 classification (preserve shared IDs)

| ID | Existing topic | S2 disposition | Scope/evidence |
|---|---|---|---|
| U01 | S1 payoff/structure | 사용자 확인 필요 — unchanged | S1 only |
| U02 | S2 4-leg payoff/stop/trailing basis | 확정 해결 — intent only | Four-leg structure and option-price basis set; payoff/mark validation remains S2-U18 |
| U03 | S3 tradable spread identity | 사용자 확인 필요 — unchanged | S3 only |
| U04 | S4 option lots/Greeks/basecamp | 사용자 확인 필요 — unchanged | S4 only |
| U05 | S5 Futures role | 사용자 확인 필요 — unchanged | No.1151 applies to S5; retired No.1168 not revived |
| U06 | S6 pair MTM/partial/cutoff | 사용자 확인 필요 — unchanged | S6 only |
| U07 | S7 IV skew/expiry | 사용자 확인 필요 — unchanged | S7 only |
| U08 | S8 add-on/rounding/DTE | 사용자 확인 필요 — unchanged | S8 only |
| U09 | S9 entry/open/close | 사용자 확인 필요 — unchanged | S9 only |
| U10 | Account capital/risk values | 설정 이관 | Versioned config; null/provisional blocks entry |
| U11 | Common partial/cancel/restart | 확정 해결 — policy only | Reconcile before resume/reset; runtime proof pending S2-U19 |
| U12 | Account aggregate exposure/correlation/netting | 설정 이관 | S2 participates in account aggregation; model not validated |
| U13 | Authoritative P&L/fee/multiplier | 사용자 확인 필요 | Mark/fee source semantics under S2-U18 |
| U14 | Exact expiry/session service | 확정 해결 — S2 intent only | Monthly expiry 15:10 intent; calendar/master proof pending |
| U15 | Shrimp Resume Context | 사용자 확인 필요 / UNAVAILABLE | Not inspected or updated in this task |

## 4. G01–G12 gate disposition

| Gate | S2 disposition | Remaining evidence |
|---|---|---|
| G01 payoff/role | 설정 이관 | signed net premium, payoff/stress validation |
| G02 entry/scale/exit | 설정 이관 | feature definitions, thresholds, trigger formulas |
| G03 contract/expiry/qty/multiplier | 설정 이관 | exact contract identity, listed strike rounding, calendar |
| G04 partial/reject/cancel/timeout | 확정 해결 — policy only | per-leg state/recovery tests NOT_RUN |
| G05 hedge/rebalance/overlay | 확정 해결 | no unapproved overlay |
| G06 stop/trailing/time exit | 설정 이관 | group P&L formula, marks/fills/fees |
| G07 session/expiry/rollover | 확정 해결 — policy only | official calendar/broker semantics |
| G08 account risk | 설정 이관 | numeric values null/provisional; enforcement unverified |
| G09 failure/restart/recovery | 사용자 확인 필요 | S2-U16/U19 and durable evidence |
| G10 traceability | 사용자 확인 필요 | exact test IDs/evidence not run/mapped |
| G11 assumptions/dependencies | 확정 해결 — register created | S2-U16–U21 listed; registration is not resolution |
| G12 validation vs approval | 확정 해결 | v0.3 remains draft/unverified/unapproved |

## 5. Cross-strategy interaction notes

- S1/S6/S7/S8/S9 may overlap S2 by strike/expiry. Aggregate premium, margin, Greeks/delta and stress; do not assume independent protection or silently net strategy-owned lots.
- S2 has no Futures hedge and must not inherit quantities from S3/S4/S5.
- Shared account limits and common multi-leg execution are separate gates; S2 intent does not prove global risk enforcement.
- Preserve Decision Log history. If a former decision conflicts with this new S2 intent, propose `폐기됨` plus reason/alternative; do not delete or mutate it here.

## 6. Status

Planning delta only. No code edits/tests/commit/push/Live orders. Existing overall matrix versions remain unchanged.
## New S2 ambiguity supplement (added after cross-checking S6 v0.3)

| ID | New ambiguity | Disposition / safety boundary | Classification |
|---|---|---|---|
| S2-U20 | User instruction says cancel-confirm then next order, but also says do not submit the next leg when the previous leg is unfilled. Does a zero-fill timeout/cancel-confirm advance to another leg or abort the monthly entry cycle? | This is a direct-instruction boundary ambiguity. Until clarified, zero-fill cancel must not automatically advance to another leg; block and preserve monthly-cycle state. Partial fill always requires reconciliation and no blind continuation. | 사용자 확인 필요 / BLOCKED |
| S2-U21 | Exact per-leg limit price basis, tick rounding, quote max age and max spread gate | S6 v0.3 treats these as configurable validation items and blocks when null. Apply this as a fail-closed requirement without inheriting S6's daily no-retry rule, which conflicts with S2's direct sequential instruction. | 사용자 확인 필요 / BLOCKED |

---
## v0.5 — S2 취소·재주문 갱신
취소 요청과 취소 확정을 분리한다. 취소 확정 뒤 execution/fill/position을 대사해 잔여 목표 수량만 재주문한다. 취소 중 late/partial fill, 유효 working order, stale quote 또는 불일치가 있으면 중복 재주문을 차단한다. retry interval/attempts/slippage bounds는 REAL_VTS 검증 전 UNSET/BLOCKING. DRAFT / UNVERIFIED / UNAPPROVED.
