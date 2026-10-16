# Strategy 7 — Weekly Volatility Skew Insurance 판단요소별 상세 명세 v0.2
- 상태: **초안 v0.2 / 판단요소별 구조 보강 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- v0.2 변경: F01~F29 판단요소별 현행 사실/목표 규칙/미결정 상태, 상태 전이, 수용 게이트 추가
- 현 코드: core/strategy/track7_volatility_skew_weekly_insurance.py v1.0
- 연결: Track7ExecutionInput/OptionContractSource, AnalyticsSnapshot, calendar features, resolve_track7, MultiLegBridge.

## 1. 목적 — 미확정
현 코드는 주 시작 시 weekly PUT+CALL insurance pair를 매수하고 pair value 고점 대비 20% 하락 또는 해당 계약 expiry 시점에 청산한다. 이름에 포함된 “volatility skew”는 현재 진입 판단에 사용되지 않으므로 의미를 확정해야 한다.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- Entry requires calendar.is_new_week_start exactly True, valid Track7ExecutionInput and positive contract multiplier.
- Input provides expiry, reference price, put/call strike and multiplier. STRIKE_OFFSET=12.5 is configurable but strategy consumes provider-selected strikes.
- State becomes insurance_active before actual pair fills.
- Entry proposal PUT BUY; resolver builds equal-quantity PUT+CALL pair.
- Pair current value=(PUT mark+CALL mark)*multiplier; quantity is not multiplied if configured insurance_qty >1.
- Close trigger is current <= peak*(1-0.20); expiry trigger compares state.expiry to analytics date ISO string and closes at >=15:00.
- Expiry input format must be normalized: YYYYMMDD will not equal YYYY-MM-DD. calendar.is_expiry_day is declared but not used.
- Close proposal PUT SELL; resolver builds close plan from open lots. Pending clears only on group_complete and position_flat.

## 3. 목표 lifecycle
WAITING_FOR_WEEK_START → CONTRACT_SELECTION → QUOTE/RISK_PREFLIGHT → ENTRY_PLANNED → ENTRY_WORKING → PARTIAL/ACTIVE → TRAILING/EXPIRY_EXIT_PENDING → FLAT_CONFIRMED → CLOSED. No new weekly lifecycle until prior position is reconciled flat.

## 4. 필수 데이터
Official trading calendar including holiday-shortened weeks; authoritative weekly Option Master exact expiry/strikes/IDs/multiplier; both option marks and timestamps; actual fills/qty/fees; session cutoff; order/fill provenance and open lots.

## 5. 미결정 항목
1. What “skew” means and whether IV skew is a trigger.
2. weekly contract selection and strike offset.
3. exact expiry and holiday/week-start semantics.
4. quantity-aware valuation and actual pair P&L.
5. 20% drawdown definition: pair mark, profit or net P&L.
6. exact expiry cutoff and fallback close.
7. quote freshness/liquidity/limit pricing.
8. partial pair fill and cancel-race response.
9. restart/missed close/residual position policy.
10. max premium/max loss and account-level risk.

## 6. 검증 시나리오
Normal/holiday week start; expiry YYYYMMDD vs ISO; stale/negative marks; qty>1; one-leg/partial fill; 20% drawdown boundary; expiry at 14:59/15:00/cutoff; new week while prior group not flat; restart and reconciliation.

## 7. 추적/판정
관련 코드: track7_volatility_skew_weekly_insurance.py, Track7OptionContractSource, resolve_track7, MultiLegBridge/PositionLotStore.
**BLOCKED** — expiry normalization, actual skew definition, quantity-aware valuation and pre-fill state require resolution.

---

## 8. 판단요소별 상세 정의 — v0.2 핵심

| ID | 판단요소 | 현재 코드에서 확인된 사실 | 신규 명세의 목표 규칙 | 결정 상태 / 차단 사유 |
|---|---|---|---|---|
| F01 | 전략 목적·경제적 역할 | Weekly PUT+CALL long insurance; strategy name says volatility skew but entry does not use IV skew. | Define weekly tail-risk protection thesis, target exposure, hedge horizon and expected payoff/cost. | **미결정** — skew meaning absent |
| F02 | 적용 시장·상품 | Track7OptionContractSource selects listed PUT/CALL at provided expiry, matching positive equal multiplier; product class filter needs proof. | General KOSPI200 option only, exact identity/expiry/multiplier, Mini option excluded. | **부분 확인** — product filter/quotes need validation |
| F03 | weekly lifecycle/session | entry only when calendar.is_new_week_start exactly True; expiry close checks own expiry date at >=15:00. | Official KRX trading calendar including holiday-shortened week, exact weekly start/end and expiry cutoff. | **부분 확인** — lifecycle rules need review |
| F04 | reference price/time | input carries reference_price; analytics as_of controls current date/time and pair marks. | Reference price and both leg marks need source/as-of/freshness and same-snapshot consistency. | **미결정** |
| F05 | entry signal | Entry requires new-week flag, valid input and positive multiplier; no volatility or IV-skew entry gate. | Decide whether skew/volatility metrics are true entry triggers or rename strategy; approve explicit gates. | **미결정** |
| F06 | repeated entry/rebuild | insurance_active prevents repeated entry while in-memory state active; state becomes active before pair fill. | One active weekly lifecycle; no new week entry while old lots/order state unresolved. | **BLOCKED** — pre-fill state and restart |
| F07 | pending/cancel lifecycle | No explicit entry fill callback; close has exit_pending callback requiring group_complete + position_flat. | Track per-leg entry ACK/partial/reject/cancel-race; cancellation/reprice and re-entry after authoritative reconciliation. | **BLOCKED** |
| F08 | contract selection | source targets reference±12.5 and chooses nearest PUT/CALL from all listed identities at supplied expiry; checks equal positive multipliers. | Exact YYYYMMDD and listed product type, quote tradability, expiry ownership and contract IDs per leg. | **미결정** — source may select nearest strike but no quote liquidity |
| F09 | strike/tick/quote | fixed target offset 12.5; selector can choose nearest listed strikes, actual offset may differ; no explicit quote/tick validation here. | Define strike rounding/tick, offset tolerance, quote spread/depth/freshness and fallback acceptance. | **미결정** |
| F10 | volatility/skew regime | No IV skew metric in feature_requirements or entry conditions. | Define skew formula (PUT IV vs CALL IV, same expiry/moneyness) and source/window if intended; otherwise explicitly remove skew from thesis. | **미결정** |
| F11 | weekly calendar signals | calendar.is_new_week_start used; calendar.is_expiry_day required but not used by strategy logic. | Use authoritative calendar and own exact expiry; reconcile is_expiry_day with state expiry. | **미검증** |
| F12 | quantity/capital/cost | INSURANCE_QTY=1; constructor qty configurable. Pair value ignores qty if qty>1. No premium/max-loss/account gate. | Editable total capital, per-strategy premium cap, strategy/account max-loss, fees/slippage, quantity-aware valuation. | **수치 미확정** |
| F13 | order price/reprice | proposal requested_price absent; entry/close plan only defines sides/strikes/qty. | Per-leg limit/tick/price source, pair net debit cap, reprice/timeout/cancel/replace and liquidity gate. | **미결정** |
| F14 | group preflight | resolver builds pair plan; complete premium/risk preflight not proven in this strategy source. | Both legs must pass contract/quote/budget/max-loss/account risk before any order. | **미검증** |
| F15 | partial/reject/unknown | State active before pair fills; exit pending stays until group_complete and position_flat. Entry failure recovery not shown. | Per-leg actual fills/lots determine active state; partial pair follows approved wait/cancel/complete/reduce policy. | **BLOCKED** |
| F16 | hedge/extra leg | No Futures hedge; only long PUT/CALL pair. | Do not add hedge legs without separate approved strategy role; preserve option pair lifecycle. | **부분 확인** |
| F17 | holdings/exposure | state tracks expiry, strikes, multiplier and peak value; not per-leg actual fills/qty. | Authoritative open lots and actual per-leg quantities/marks/Greeks/exposure. | **미검증** |
| F18 | stop/max loss | No hard max-loss exit; paid premium theoretically limits loss only if pair fully filled at known cost. | Max premium and account max-loss gates, stress scenarios and emergency exit. | **미결정** |
| F19 | trailing/P&L | current=(PUT mark+CALL mark)*multiplier, without multiplying by insurance_qty; peak is pair value not net profit; exit if current <= peak*(1-20%). | Quantity-aware actual pair MTM/P&L with fees, cost basis and mark timestamps; define drawdown from value vs profit. | **BLOCKED** — quantity and P&L semantics |
| F20 | time/expiry/rollover | close if state.expiry == as_of.date().isoformat and time>=15:00; exact string format mismatch can skip expiry. | Canonical exact YYYYMMDD at source boundary, normalized date internally; official final-trading cutoff and fallback. | **BLOCKED** — expiry format contract |
| F21 | close scope/qty/side | PUT SELL proposal resolves to PUT+CALL close plan; close callback only after group_complete + flat. | Close actual open lots and quantities for both legs; verify every required lot flat. | common principle aligned; per-leg quantity evidence **미검증** |
| F22 | P&L/fees/slippage | Uses pair mark value, not cost-basis net P&L; fees/slippage are not used. | Realized/unrealized per-leg and group P&L with cost basis, multiplier, fees/slippage and account attribution. | **BLOCKED** |
| F23 | trigger priority | trailing drawdown check occurs before expiry close; a drawdown signal may preempt expiry signal on same evaluation. | Define expiry/hard risk/market close/trailing priority and fallback order behavior. | **미결정** |
| F24 | lifecycle/provenance | close plan from open lots; state group/provenance and per-leg order state not persisted here. | run/group/evaluation/leg/order/execution/position/P&L and config hash across lifecycle. | **미검증** |
| F25 | restart/duplicate/timeout | reset clears state; no durable restore for prior-week open positions. | Restore orders/fills/lots/expiry/watermark before new-week logic; no blind reset or duplicate entry. | **미결정** |
| F26 | cross-strategy/account risk | No aggregate account premium/tail-risk check in strategy logic. | Aggregate premium, margin, correlated tail stress and duplicated protection across strategies. | **미결정** |
| F27 | data error/unavailable | required analytics statuses checked; marks must be nonnegative Decimals to update current pair value; unavailable marks suppress trailing but expiry may still close. | Stale/missing marks are UNAVAILABLE; expiry/close management must continue via authoritative position state. | **미검증** |
| F28 | editable settings | STRIKE_OFFSET and TRAILING_DRAWDOWN configurable; qty constructor setting; account capital/premium/max-loss enforcement not proven. | Versioned editable total capital, strategy premium max, strategy/account max-loss, qty, strike offset, trailing, fees/margin and effective time. | **수치·강제경로 미확정** |
| F29 | tests/acceptance | Tests cover pair plan, flat confirmation, mark-based trailing and exact expiry date test; no qty>1/account risk/partial pair completeness proof. | Test expiry formats, qty>1, marks/fills/cost, partial entry/close, week-start holidays, restart and account limits. | **미완료** |

## 9. Strategy 7 목표 상태 전이표 — 구현 전 계약

| 현재 상태 | 이벤트/조건 | 다음 상태 | 필수 가드·행동 | 실패 처리 |
|---|---|---|---|---|
| DISABLED | ON/config valid | WAITING_FOR_WEEK_START | entry permission/config version | unknown → BLOCKED |
| WAITING_FOR_WEEK_START | official new trading week start | CONTRACT_SELECTION | previous group must be flat/reconciled | residual position → RECONCILIATION_REQUIRED |
| CONTRACT_SELECTION | exact weekly expiry and listed pair | QUOTE_BUDGET_PREFLIGHT | both leg IDs/quotes/multiplier/budget | missing leg → BLOCKED |
| QUOTE_BUDGET_PREFLIGHT | group risk pass | ENTRY_PLANNED | stable group ID, premium reserve | risk fail → no order |
| ENTRY_PLANNED | plan persisted | ENTRY_WORKING | PUT/CALL independent order state | unknown route → RECONCILIATION_REQUIRED |
| ENTRY_WORKING | both legs filled/reconciled | ACTIVE | actual lots and pair cost confirmed | partial/reject → PARTIALLY_EXPOSED |
| ACTIVE | drawdown/expiry/max-loss | EXIT_PENDING | deterministic trigger priority and both open lots | missing close plan → BLOCKED |
| EXIT_PENDING | partial/cancel race | EXIT_PENDING | per-leg remaining qty and fill reconciliation | unknown → RECONCILIATION_REQUIRED |
| EXIT_PENDING | both lots flat confirmed | FLAT_CONFIRMED | position read model and executions agree | mismatch → RECONCILIATION_REQUIRED |
| FLAT_CONFIRMED | P&L/fees finalized | CLOSED | persist expiry/config hash and result | mismatch → BLOCKED |
| any active state | new week/restart/source failure | RECONCILIATION_REQUIRED | reconcile old group before any new entry | cannot reconcile → BLOCKED |

## 10. 명세-코드-테스트 추적 및 수용 게이트

| 추적 ID | 관련 경로/기준 | 검증 산출물 | 현재 판정 |
|---|---|---|---|
| S7-F01~F06, F10~F12, F18~F20, F23 | core/strategy/track7_volatility_skew_weekly_insurance.py, Track7CalendarSource | skew thesis, week/expiry, trigger priority tests | BLOCKED |
| S7-F02, F08~F09, F13~F14 | track7_option_contract_source.py, resolve_track7, MultiLegBridge | product identity, quotes, pair budget and risk preflight | INCOMPLETE |
| S7-F07, F15, F17, F21, F24~F25 | close callback, PositionLotStore, Virtual integration | per-leg partial/reject/restart/all-flat evidence | BLOCKED |
| S7-F19, F22, F26, F28 | mark/P&L, fee/margin providers, editable risk config | quantity-aware MTM and account risk limits | BLOCKED |
| S7-F29 | tests/strategy/test_strategy7.py, tests/unit/test_strategy7_virtual_runtime_integration.py | F01~F29-to-test map | INCOMPLETE |

Acceptance gates:
- A01: strategy name/thesis specifies whether IV skew is a trigger.
- A02: exact weekly option identities and product class verified.
- A03: pair value and drawdown use quantity-aware authoritative marks and fees.
- A04: entry state only becomes active after authoritative fills; partial pair has approved recovery.
- A05: exact expiry normalization and holiday-shortened week behavior tested.
- A06: deterministic trailing/expiry/max-loss priority and all-flat confirmation.
- A07: editable capital/premium/max-loss/account risk settings enforced.
- A08: F01~F29 map to tests and evidence.
- A09: validation and user approval remain separate.

## 11. 미결정·승인 필요 항목

| ID | 결정 필요 사항 | 필요한 근거 | 현재 영향 |
|---|---|---|---|
| D01 | meaning of volatility skew | IV surface definition and same-expiry/moneyness data | thesis incomplete |
| D02 | weekly start and holiday-shortened week | authoritative trading calendar | entry date policy unresolved |
| D03 | strike offset/fallback selection | listed strikes, quotes, tick/liquidity | contract selection not approved |
| D04 | qty-aware mark value and net P&L | actual fills/marks/multiplier/fees | trailing policy blocked |
| D05 | exact expiry/cutoff normalization | canonical YYYYMMDD and KRX calendar | expiry close can be skipped |
| D06 | partial pair entry/exit recovery | per-leg fill/risk scenarios | execution blocked |
| D07 | premium/max-loss/account capital values | capital, quotes, fees, margin, stress loss | values require separate approval |
| D08 | restart/missed weekly close | persistent order/fill/position evidence | no new weekly lifecycle until reconciled |
| D09 | account aggregate tail exposure | all strategy positions and correlation | enforcement unproven |
| D10 | trailing vs expiry priority | market/session and risk scenarios | terminal policy unresolved |

## 12. v0.2 판정

- 상태: **초안 / 미검증 / 미승인**.
- 판단요소: **F01~F29 29/29 작성**.
- 주요 차단: IV skew not used, pre-fill active state, pair valuation not qty-aware, expiry format equality, no premium/max-loss/account risk.
- Document structure only; no strategy scenario/E2E tests run.
- Code changes/commit/push/KIS Live orders: none.
- Next: Strategy 8 same F01~F29 depth.
