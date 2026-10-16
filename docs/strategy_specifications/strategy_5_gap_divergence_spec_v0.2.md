# Strategy 5 — Gap Divergence 판단요소별 상세 명세 v0.2
- 상태: **초안 v0.2 / 판단요소별 구조 보강 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- v0.2 변경: F01~F29 판단요소별 현행 사실/목표 규칙/미결정 상태, 상태 전이, 수용 게이트 추가
- 현 코드: core/strategy/track5_gap_divergence.py v2.0
- 연결: Track5ExecutionInput, AnalyticsSnapshot, Option Contract Source, Futures identity, resolve_track5, MultiLegBridge.

## 1. 목적
현재 코드는 opening gap/초반 과도한 이동의 mean reversion을 거래하고 option BUY + Mini Futures 5계약을 묶어 진입, Futures first exit 후 옵션을 관리한다. No.1151 기준으로 Futures가 alpha인지 hedge인지 실제 역할·자본·비용을 검토하며 5 futures를 5 options로 단순 치환하지 않는다.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- Required metrics: price.open/gap/last/previous_close, expected_move, z_score, regime.
- effective z threshold: HIGH_VOL/NOISE_CHOPPY/CIRCUIT_BREAKER=1.8; NORMAL/NEUTRAL=1.1; else constructor default 1.5.
- opening gap: abs(z)>=threshold and abs(z)<4; entry=open, target=previous close.
- intraday candidate: within 30 minutes from first recorded session tick; move >= max(1.0, expected_move*1.1), z threshold <= abs(z)<4.
- positive z → SHORT/CALL BUY/Futures SELL; negative z → LONG/PUT BUY/Futures BUY. Option qty=1, Mini Futures qty=5.
- stop distance=max(1.0, expected_move*0.8).
- session_start_price is set to first observed last price, not guaranteed official session open.
- gap starts filling → Futures close request first. Only confirmed fill + position_flat sets futures_closed.
- option exits after futures flat at target, stop, timeout=30 evaluate calls, or trailing reversal. Trailing activation=max(0.3, expected_move*0.3); reversal=max(0.1, expected_move*0.1) scaled 1.0/0.80/0.67.
- entry rejection/no-route resets only when no fills; partial fill preserves state for reconciliation. Close reports validate FILLED, execution ID/time/price, filled qty, remaining qty=0 and position_flat.
- 30 timeout is number of evaluate calls, not elapsed time. Option P&L is underlying-price proxy, not actual premium/mark-to-market. Explicit expiry/roll policy is missing.

## 3. 목표 lifecycle
WAITING_FOR_SESSION → OPEN_REFERENCE_CONFIRMED → GAP_SIGNAL_VALIDATED → CONTRACT/RISK_PREFLIGHT → ENTRY_WORKING → PARTIAL/ACTIVE → FUTURES_FIRST_EXIT_PENDING → FUTURES_FLAT_CONFIRMED → OPTION_EXIT_PENDING → FLAT_CONFIRMED → CLOSED.

If Futures exit rejects/partials/unknown, use approved recovery policy; do not assume hedge is flat or blindly close/reset the option state. Actual remaining lots govern close quantity.

## 4. 필수 데이터
Official session open/previous close/calendar; expected_move/z-score/regime definitions; exact option expiry/type/strike/ID/multiplier/quotes; Mini Futures identity/point value/margin/quote; actual fills/fees/slippage/P&L; group/leg provenance and idempotency.

## 5. 미결정 항목
1. official open vs first tick and gap reference.
2. regime thresholds and z-score normalization.
3. futures qty 5 and option qty 1; alpha vs hedge role.
4. contract expiry/strike rank/liquidity selection.
5. stop/target uses underlying or actual combined net P&L.
6. exact “gap starts filling” trigger and Futures-first rule.
7. partial/rejected Futures exit recovery and option protection.
8. timeout by evaluations vs elapsed time.
9. trailing rule, fees/slippage, max loss and account margin.
10. expiry/overnight/restart and all partial-fill combinations.

## 6. 검증 시나리오
z threshold and abs(z)=4 boundaries; official open missing/late; 30-minute window; stale quote/wrong contract; option-only/futures-only/partial entry; Futures exit reject/partial/cancel-race; stop/target/timeout/trailing overlap; option close partial/reject; 30th evaluation; restart/session/expiry; account aggregate risk.

## 7. 추적/판정
관련 코드: track5_gap_divergence.py, Track5 contract/runtime sources, resolve_track5, Futures identity, MultiLegBridge/PositionLotStore.
**BLOCKED** — P&L proxy, fixed quantity and partial-entry recovery need review.

---

## 8. 판단요소별 상세 정의 — v0.2 핵심

| ID | 판단요소 | 현재 코드에서 확인된 사실 | 신규 명세의 목표 규칙 | 결정 상태 / 차단 사유 |
|---|---|---|---|---|
| F01 | 전략 목적·경제적 역할 | Opening gap/초반 급격한 이동의 mean reversion을 시도하고 Option BUY+Mini Futures SELL/BUY로 진입한다. | Alpha/spread leg와 protective hedge를 실제 payoff/stress/cost로 구분하고 각각의 경제적 역할을 승인한다. | **미결정** — No.1151에 따라 Futures 역할 재분류 필요 |
| F02 | 적용 시장·상품 | General KOSPI200 option multiplier 250,000 기준의 contract source; Mini Futures separate identity. | 일반 KOSPI200 옵션만 사용하고 Mini option 제외; Futures는 실제 role 검토 후 identity/master로 선택. | 상품 경계는 확정; 최종 legs 미결정 |
| F03 | session/lifecycle | Opening-gap uses analytics open; intraday uses first recorded last price and 30-minute window. | Official KRX open/session calendar, delayed first tick, previous close, intraday activation and exact expiry policy. | **미결정** — first tick is not official open |
| F04 | 기준가격·시점 | Required analytics: open/gap/last/previous close/expected move/z/regime. Session start is first observed last tick. | Source/as-of/received time, instrument identity and freshness preserved; open/previous-close provenance validated. | **미결정** |
| F05 | entry signal | Effective z: HIGH_VOL/NOISE_CHOPPY/CIRCUIT_BREAKER=1.8, NORMAL/NEUTRAL=1.1, else configured default 1.5; abs(z)<4. | Threshold definitions and opening/intraday signal boundaries approved with explicit equality rules. | **미결정** |
| F06 | repeat entry/rebuild | state.is_active prevents a second gap entry while active; no scale-in policy. | One active lifecycle/group at a time; no repeat until actual flat and reconciled. | **부분 확인** — restart/flat reconciliation still required |
| F07 | pending/cancel entry | grouped entry has option and futures legs; entry callback resets only if no fills and all terminal failures/no route. | Per-leg order ACK/working/partial/cancel/reject/timeout/cancel-race; idempotent group recovery. | **미검증** — scenario coverage needed |
| F08 | option/Futures identity | Track5OptionContractSource selects standard multiplier contracts and 2nd/3rd OTM candidate with liquidity score; futures identity is separate resolver input. | Exact YYYYMMDD expiry, contract ID, multiplier, quote, tradability, Futures identity/point value verified. | **부분 확인** — expiry input and end-to-end provenance require validation |
| F09 | strike/tick/liquidity | Option source selects 2nd or 3rd OTM strike by top-3 bid/ask quantity sum; strike tick/quote price behavior is outside strategy signal. | Strike rounding, option tick, quote age/spread/depth and tie-break are specified and tested. | **미결정** — liquidity score alone does not guarantee executable price |
| F10 | expected move/regime | required expected_move>0; regime changes z threshold; stop distance=max(1.0, expected_move*0.8). | Define expected_move model/source/window, regime enum, unit and freshness. | **미결정** |
| F11 | gap/mean-reversion trigger | opening candidate abs(z)>=threshold and <4; intraday within 30 minutes, move>=max(1, expected_move*1.1), derived z threshold and <4. | Exact gap fill trigger, target reference and threshold boundaries with timestamp scenarios. | **미결정** |
| F12 | quantity/capital/cost | Option qty=1, Mini Futures qty=5, open timeout=30 evaluations. No strategy/account premium/max-loss enforcement proven here. | Editable total capital, per-strategy max premium, strategy/account max loss, margin/fees/slippage and role-based qty cap. | **수치 미확정** — No.1151 requires evidence-based sizing |
| F13 | order pricing/reprice | proposals requested_price absent; contract source has liquidity score but does not itself specify submitted limit price. | per-leg bid/ask/tick/limit collar, net group risk, reprice/timeout/cancel/replace and idempotency. | **미결정** |
| F14 | group risk preflight | entry plan contains Option and Mini Futures; virtual execution has group/risk path and Strategy 5 risk diagnostic JSONL exists. | All required legs pass group-wide preflight including capital, margin, premium, max loss, costs and partial-fill stress before submission. | **미검증** — JSONL is observation, not risk approval |
| F15 | partial/reject/unknown | Entry callback resets only for no-fill no-route or all terminal rejects; partial state remains active for reconciliation. Futures exit requires correlated FILLED report with execution fields and position_flat. | Each leg’s actual fill and remaining lots govern exposure; unknown/partial/cancel-race stays PARTIAL/BLOCKED/RECONCILIATION_REQUIRED. | **부분 확인** — every entry/exit permutation not verified |
| F16 | Futures role/hedge conversion | Current code uses Mini Futures 5 and option 1. No.1151 says classify PRIMARY_ALPHA/SPREAD vs HEDGE; do not blanket remove all Futures or replace 5 futures with 5 options. No.1168 option BUY 2 alternative is 폐기됨. | Reclassify role with evidence; only convert confirmed hedge-purpose exposure to option-based risk structure after contract/Greeks/premium/max-loss analysis. | **미결정 / 사용자 승인 필요** — do not adopt old BUY-2 proposal |
| F17 | position/exposure state | Track5State records futures side/closed flag and one option type/strike; actual leg fills/quantities are confirmed via execution reports and open lots. | Maintain authoritative per-leg identities, actual qty, fill price, remaining qty and current net exposure. | **미검증** |
| F18 | stop/max loss | stop distance=max(1, expected_move*0.8); option stop signal may first request Futures exit. | Strategy/account max-loss and stress scenarios; separate underlying trigger from actual combined option/Futures P&L. | **미결정** |
| F19 | target/trailing | P&L proxy uses underlying move; target previous close; trailing activates max(0.3, expected_move*0.3), reversal max(0.1, expected_move*0.1), scale 1/.80/.67. | Actual fill/mark/multiplier/fees P&L, peak watermark, target/stop/trailing priorities and per-leg attribution. | **미결정** — underlying proxy is not option MTM |
| F20 | time exit/expiry/roll | MAX_OPEN_EVALUATIONS=30 calls, not elapsed minutes. Explicit expiry/roll policy absent. | Decide elapsed time vs call count; exact YYYYMMDD, final trading session, overnight and terminal flat requirements. | **BLOCKED** — expiry policy absent |
| F21 | exit scope/quantity | Futures-first exit on gap starts filling; option exits only after futures_closed at target/stop/timeout/trailing. Resolver close plan is built from open lots. | Preserve Futures-first only if approved by role analysis; close direction/remaining qty from authoritative lots; never assume requested close = flat. | **미결정** — economic sequence needs approval |
| F22 | P&L/cost | Option stop/trailing use underlying proxy; per-leg actual option premium P&L not used in strategy evaluation. | Per-leg option/Futures realized/unrealized P&L, multiplier, fees, slippage and account attribution. | **BLOCKED** — authoritative combined P&L needed |
| F23 | trigger priority | gap-fill futures exit is checked before target/stop/timeout/trailing; option close request suppresses subsequent evaluations. | Deterministic terminal priority and simultaneous-trigger policy; explicit state for futures-close pending and option-close pending. | **미결정** |
| F24 | lifecycle/provenance | group entry uses run_id+signal id; reports validate execution id/time/price/fill qty/remaining qty/position flat. | run/group/evaluation/exit_batch/leg/client_order/execution/position/P&L provenance and config hash. | **부분 확인** — full end-to-end evidence required |
| F25 | restart/duplicate/timeout | state is immutable dataclass reset; restore across restart not shown. | Restore all open orders/fills/lots/close flags before evaluation; never blind retry or reset on timeout. | **미결정** |
| F26 | cross-strategy/account risk | no explicit account aggregate risk calculation in strategy logic; risk diagnostic JSONL captures execution preflight observations. | Aggregate all strategy premium, margin, correlated stress loss and shared exposure before entry/scale/rebalance. | **미결정** — diagnostic is not enforcement |
| F27 | data errors | required analytics must be AVAILABLE and positive expected_move/previous close; invalid Futures side stores reconciliation error. | stale/missing open/expiry/quote/fill/position inputs fail closed; retain open positions and block new entry. | common principle aligned; **runtime coverage incomplete** |
| F28 | editable settings | ENTRY_QUANTITY, MINI_FUTURES_QUANTITY, MAX_OPEN_EVALUATIONS are configurable class parameters; total capital/premium/max-loss enforcement not proven. | Versioned editable total capital, strategy premium max, strategy/account max loss, fees/margin, qty and timeouts; effective time/hash. | **수치·강제경로 미확정** |
| F29 | tests/acceptance | tests cover z regime, entry signal, 30-minute window and many execution callback cases; no complete all-factor/account stress acceptance evidence. | Map all F01~F29 to tests; add expiry, actual P&L, product identity, account risk and restart scenarios. | **미완료** |

## 9. Strategy 5 목표 상태 전이표 — 구현 전 계약

| 현재 상태 | 이벤트/조건 | 다음 상태 | 필수 가드·행동 | 실패 처리 |
|---|---|---|---|---|
| DISABLED | ON/config valid | WAITING_FOR_SESSION | entry permission and config version | unknown → BLOCKED |
| WAITING_FOR_SESSION | official calendar/open and source available | OPEN_REFERENCE_CONFIRMED | distinguish official open from first tick | mismatch/late open → UNAVAILABLE |
| OPEN_REFERENCE_CONFIRMED | gap/z/regime/expected move valid | GAP_SIGNAL_VALIDATED | threshold and 30-minute boundary | incomplete data → BLOCKED |
| GAP_SIGNAL_VALIDATED | role/contract/quotes/risk pass | ENTRY_PLANNED | approved option/Futures leg roles and qty | role unresolved → BLOCKED |
| ENTRY_PLANNED | group id/idempotency persisted | ENTRY_WORKING | per-leg orders/fills and shared provenance | uncertain route → RECONCILIATION_REQUIRED |
| ENTRY_WORKING | all required legs filled | ACTIVE | actual open lots and roles reconcile | partial/reject → PARTIALLY_EXPOSED |
| ACTIVE | gap starts filling | FUTURES_FIRST_EXIT_PENDING | only if Futures-first sequence approved | unknown Futures position → BLOCKED |
| FUTURES_FIRST_EXIT_PENDING | Futures fills/partial/reject | FUTURES_FLAT_CONFIRMED or RECONCILIATION_REQUIRED | actual Futures lots flat confirmed | partial/reject → remain active and reconcile |
| FUTURES_FLAT_CONFIRMED | option target/stop/time/trailing trigger | OPTION_EXIT_PENDING | actual option lots/quantity | missing lot → BLOCKED |
| OPTION_EXIT_PENDING | option fill pending | OPTION_EXIT_PENDING | per-leg fills/cancel race and remaining qty | unknown → RECONCILIATION_REQUIRED |
| OPTION_EXIT_PENDING | all required lots flat | FLAT_CONFIRMED | authoritative position read model matches | mismatch → RECONCILIATION_REQUIRED |
| FLAT_CONFIRMED | P&L/fees final | CLOSED | save final attribution/config hash | accounting mismatch → BLOCKED |
| any active state | restart/API/source failure | RECONCILIATION_REQUIRED | restore orders/fills/positions before evaluation | cannot reconcile → BLOCKED |

## 10. 명세-코드-테스트 추적 및 수용 게이트

| 추적 ID | 관련 경로/기준 | 검증 산출물 | 현재 판정 |
|---|---|---|---|
| S5-F01~F06, F10~F12, F16, F18~F20, F23 | core/strategy/track5_gap_divergence.py | thesis, role, threshold, stop/target/expiry scenarios | BLOCKED |
| S5-F08~F09, F13~F14 | track5_option_contract_source.py, resolve_track5, virtual_multi_leg_execution.py | contract identity, quote, liquidity, group risk preflight | INCOMPLETE |
| S5-F07, F15, F17, F21, F24~F25 | on_execution_result, MultiLegBridge, PositionLotStore | entry/exit partial/reject/cancel-race/restart reconciliation | INCOMPLETE |
| S5-F22, F26, F28 | strategy5 risk diagnostic, core/risk, fee/margin/account sources | actual P&L, account max-loss and config enforcement | BLOCKED |
| S5-F29 | tests/strategy/test_strategy5.py and Virtual E2E | F01~F29 test-evidence map | INCOMPLETE |

Acceptance gates:
- A01: official opening reference and gap calculation are source-backed.
- A02: Futures leg roles are classified under No.1151; No.1168 is not used as target.
- A03: exact option/Futures identity, multiplier, quotes, fees and margin are authoritative.
- A04: group-wide preflight and every per-leg partial/reject/cancel-race path is verified.
- A05: actual option and Futures P&L/fees are authoritative; underlying proxy remains only a market trigger if separately approved.
- A06: expiry, 30-evaluation timeout, session close and overnight rules are deterministic.
- A07: editable capital/premium/strategy/account max-loss settings are enforced and versioned.
- A08: all F01~F29 map to tests and evidence.
- A09: validation and user approval remain separate.

## 11. 미결정·승인 필요 항목

| ID | 결정 필요 사항 | 필요한 근거 | 현재 영향 |
|---|---|---|---|
| D01 | Official open vs first tick | KRX session/source timestamps | opening-gap entry blocked |
| D02 | Futures PRIMARY_ALPHA/SPREAD vs HEDGE role | payoff, stress, margin and fee analysis | current qty=5 is observation, not target |
| D03 | Option expiry/strike/liquidity selection | exact contract master and executable quotes | contract choice not fully approved |
| D04 | Stop/target/trailing actual P&L basis | option marks/fills, Futures fills, multiplier/fees | exit economics unresolved |
| D05 | Futures-first sequence and recovery | per-leg fill/partial/reject stress scenarios | terminal sequence needs approval |
| D06 | timeout evaluations vs elapsed time | runtime cadence and session scenarios | 30-call rule unapproved |
| D07 | expiry/overnight/restart | exact expiry/calendar and persisted position evidence | lifecycle incomplete |
| D08 | editable total capital/premium/max-loss values | account capital, quotes, fees, margin, stress loss | numerical values require separate approval |
| D09 | account aggregate risk | all strategy positions/margin/correlated stress | enforcement not proven |
| D10 | Strategy 5 diagnostics vs risk decisions | risk preflight and JSONL evidence | observation artifact must not be treated as approval |

## 12. v0.2 판정

- 상태: **초안 / 미검증 / 미승인**.
- 판단요소: **F01~F29 29/29 작성**.
- No.1151 is the relevant current design direction; No.1168 is 폐기됨 and must not be treated as approved target.
- 주요 차단: Futures role/quantity, official open, actual option P&L, expiry, account risk and complete partial-fill scenarios.
- 문서 구조 검사 only; no strategy tests/E2E/Live orders.
- Code changes/commit/push: none.
- Next: Strategy 6 same F01~F29 depth.
