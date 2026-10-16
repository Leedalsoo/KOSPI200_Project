# Strategy 1~9 판단요소별 통합설계표 v1.0

- 상태: 초안 v0.6 — v0.5를 보존하고 S7 v0.3 의도·상호작용 갱신 초안을 추가, 미검증, 미승인
- 작성일: 2026-10-13
- 기준 브랜치/HEAD: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- 이 문서는 현재 전략을 비교하거나 개선점을 나열하는 보고서가 아니다. **동일한 판단요소를 행으로 두고 Strategy 1~9를 열로 두어, 모든 전략을 같은 설계 틀에서 통합하는 주 설계표**다.
- 현 코드·과거 기록은 사실과 이력을 확인하는 자료다. 기존 동작이나 과거 PASS를 신규 요구사항 또는 승인으로 취급하지 않는다.
- 빈칸은 허용하지 않는다. 확인된 사실이 없거나 새 설계 결정이 필요한 칸은 미정/BLOCKED로 기록한다. 미정은 생략이 아니라 결정할 항목이다.
- Strategy 5의 과거 No.1168 옵션 BUY 2안은 Decision Log 상태가 폐기됨이다. 현재 승인 설계로 재사용하지 않는다. Futures 5의 역할과 옵션 헤지 대안은 새 명세에서 다시 결정한다.
- 이 문서 작성만으로 코드 변경, commit/push, KIS Live 주문을 승인하지 않는다.
- Strategy 1~9 각 v0.2 상세 명세는 동일 F01~F29를 포함한다. 아래 상호작용/충돌 표는 각 전략 상세본과 통합표의 재대조 결과를 기록하며, 미결정은 구현 허가가 아니다.

## A. 목적·진입·시장 판단 요소

| ID | 판단요소 | Strategy 1 Tail Defense | Strategy 2 Asymmetric Trap | Strategy 3 Statistical Arbitrage | Strategy 4 Gamma Scalping | Strategy 5 Gap Divergence | Strategy 6 Daily Tail Insurance | Strategy 7 Weekly Volatility Skew Insurance | Strategy 8 Macro Regime Monthly Strangle | Strategy 9 Event Overnight Insurance |
|---|---|---|---|---|---|---|---|---|---|---|
| F01 | 목적·보호 대상·경제적 역할 | 현행은 option fence와 조건부 Futures hedge. 목표 tail 방향, 보호 대상, payoff는 미정. | 현행은 short CALL/PUT와 안쪽 long CALL/PUT의 4-leg. trap의 경제적 정의와 정의위험 여부 미정. | 현행은 z-score/spread 신호. 실제 거래 가능한 spread 레그와 수익 원천 미정. | 현행은 delta 기반 Futures 조정. 옵션 inventory 소유자와 Basecamp 관계 미정. | 현행은 gap 신호와 option/Futures 결합. Futures 5의 실제 경제적 역할 미정. | 현행은 변동성 조건의 PUT+CALL pair. 보호 대상과 비용 대비 성능 미정. | 현행은 주간 PUT+CALL pair. skew의 정량 정의와 보험 목표 미정. | 현행은 월물 long strangle과 PUT overlay 후보. macro overlay의 경제적 목적 미정. | 현행은 overnight PUT+CALL pair. event 정의와 overnight 보호 목표 미정. |
| F02 | 진입 가능 상태·세션 | official calendar, warmup, fence/hedge 상태와 OFF 시 기존 포지션 처리를 정의. | daily cap/cooldown과 active trap을 분리; cutoff가 강제청산인지 별도 정의. | pending exit, regime, spread data warmup을 정의; pending 경로의 regime 참조 오류 후보 확인. | equity gate, Basecamp, 실제 hedge state를 구분. | official open과 first observed tick을 구분; opening-gap/intraday 상태 분리. | daily active와 실제 pair fills 완료 상태 분리. | new-week trigger와 pair fills 완료 상태 분리. | base strangle, overlay, pending tranche 상태 분리. | 15:10 진입과 공식 장 종료 관계, next-session 상태 정의. |
| F03 | 입력·데이터 계약 | underlying, volatility, momentum, option chain/quotes, Greeks, open lots, calendar. | BBW, volume z, OBI, basis, IV skew, POC, option quotes, positions. | spread, z-score/std, vol ratio, regime, expected cost, Futures identity/quotes. | Greeks/delta, volatility, equity, option positions, Futures lots. | open/previous close/last/gap/expected move/z/regime, option quote, Futures identity. | price, volatility, PUT/CALL contracts, expiry, multiplier, premium/fees. | weekly calendar, exact expiry, reference price, PUT/CALL quotes and multiplier. | monthly Option Master, DTE, CALL/PUT quotes, budget, macro regime. | event/time, prior close/open/last, ATM contracts, pair quotes, next-session calendar. |
| F04 | 데이터 유효성·동기화 | missing/stale delta, option identity or timestamp mismatch blocks new action. | required analytics unavailable/stale blocks entry; truthy value is not a validity check. | missing spread identity/cost/source blocks order. | Greeks and position must match contract and as-of time. | official open cannot be inferred from first tick; each contract source timestamp validated. | both leg quotes and multipliers must pass preflight. | exact weekly expiry and both quote identities must match. | CALL/PUT/overlay identities and quote/cost source must match. | actual fills for entry premium; current marks from matching contract quotes only. |
| F05 | Regime·진입 공식·임계값 | 현 코드: fence 7.5/12.5, vol ratio 1.15, approach 0.9, ROC direction. 최종 threshold/부호 미정. | 현 코드: BBW truthy, volume z>3, abs OBI>0.5, basis>0.3, POC distance>1.0, IV skew. 목표 기준 미정. | 현 코드: z entry 2, exit .2, stop 3.5 등 regime별 threshold. 산식·경계·우선순위 재검증 필요. | 현 코드: delta deadband, equity threshold, volatility regime. Greek units와 deadband 단위 미정. | 현 코드: regime z threshold, gap/intraday move and stop. official open 기준 재정의 필요. | 현 코드: active vol ≥ base vol×1.3. baseline window와 경계조건 미정. | 현 코드: new-week start. skew trigger와 expiry condition 정규화 필요. | 현 코드: DTE≥15, budget≥200,000, macro regimes. PUT 수량 truncation과 overlay 조건 재설계 필요. | 현 코드: time≥15:10, shock 1%, stabilization window. event feed와 session gate 미정. |
| F06 | 신호 중복·우선순위·재진입 | 같은 snapshot 중복평가, fence/hedge 동시신호, daily hedge count 기준 미정. | daily entry cap=2, loss cooldown=15분 관찰. loss source와 카운트 시점 미정. | 이전 exit z 차이 0.8 미만 재진입 차단 관찰. 재진입 시간/중복 규칙 미정. | rebalance throttling과 actual filled qty 기준 재조정 필요. | same-gap duplicate entry, reversal, terminal/non-terminal exit 우선순위 미정. | daily re-entry, cutoff 이후 재진입 정책 미정. | same-week duplicate entry와 weekly reset 미정. | base entry와 overlay/add-on/close 동시 발생 우선순위 미정. | entered-today 및 restart/retry 중복방지와 next-day re-entry 미정. |
| F07 | 전략 주기·시간 만료 | 월물 유지/일별 reset, DTE 및 exact last trading session 규칙 미정. | expiry handling이 부족; all-leg close와 overnight policy 필요. | 300 evaluate calls는 elapsed time이 아님; session timeout/rollover 미정. | option/Futures 만기 불일치와 hedge cutoff 미정. | 30 evaluate calls는 elapsed time이 아님; option/Futures expiry/rollover 미정. | daily cutoff 상수와 official calendar 일치 확인 필요. | expiry string format 정규화 및 주간 rollover 필요. | DTE≤4 HOLD_LONG_ATTACK은 NON_EXECUTION; 강제청산으로 바꾸지 않고 별도 결정. | exact expiry가 state에 부족; overnight 이후 contract tradability와 expiry 처리 미정. |

## B. 계약·수량·주문·헤지 판단 요소

| ID | 판단요소 | Strategy 1 Tail Defense | Strategy 2 Asymmetric Trap | Strategy 3 Statistical Arbitrage | Strategy 4 Gamma Scalping | Strategy 5 Gap Divergence | Strategy 6 Daily Tail Insurance | Strategy 7 Weekly Volatility Skew Insurance | Strategy 8 Macro Regime Monthly Strangle | Strategy 9 Event Overnight Insurance |
|---|---|---|---|---|---|---|---|---|---|---|
| F08 | 레그 구조·방향·역할 | 현 코드 3 option legs: CALL BUY, PUT SELL, PUT SELL. 각 역할과 최종 구조 미정. | 현 코드 4 legs: short CALL/PUT + long CALL/PUT. 역할별 max-loss 검증 필요. | adapter가 동일 Futures identity의 반대 side 같은 qty legs를 만들 수 있음. 실제 spread 구성 미정. | Basecamp는 NON_EXECUTION event; 실제 option position과 hedge role을 구분해야 함. | 현 코드 option BUY 1 + Futures qty 5. Futures 역할 재분석; 폐기된 BUY2안은 승인 기준 아님. | PUT BUY + CALL BUY pair; 두 leg를 동일 group으로 묶고 독립 상태 추적. | PUT BUY + CALL BUY pair; weekly expiry와 leg identity 연결. | CALL BUY + PUT BUY, 추가 PUT overlay 후보. base와 overlay leg/group 분리. | overnight PUT BUY + CALL BUY; leg별 fills와 next-day close 역할 분리. |
| F09 | 계약·행사가 선택 | 현 strike는 평가가격 +12.5, -12.5, -7.5 후 rounding. base price/tick/rounding 정책 미정. | 현 ATM offsets ±10/±5 또는 ±7.5/±2.5. ATM·tick·rounding 규칙 미정. | 각 Futures leg의 실제 instrument/contract month를 확정; Index는 거래 레그로 오인 금지. | Greeks가 가리키는 실제 option identity와 Basecamp strikes의 관계 미정. | CALL/PUT 선택은 gap 방향 관찰; exact expiry/strike/option identity와 Futures identity 별도 확정. | provider-selected PUT/CALL strikes, expiry, rounding, quote coverage 검증. | provider-selected weekly strikes와 STRIKE_OFFSET 실제 적용 경로 검증. | monthly Option Master로 strike/expiry resolve; CALL/PUT multiplier equality 검증. | ATM PUT/CALL strikes, exact expiry, next-session tradability 확인. |
| F10 | 만기·계약 identity | authoritative Option Master의 exact YYYYMMDD expiry; DTE float만으로 계약을 식별하지 않음. | 4개 leg 각각 exact expiry와 last trade session 필요. | Futures expiry/roll and actual spread legs identity 미정. | option inventory와 Futures hedge expiry 관계 명시. | option/Futures expiry를 각각 관리; 만기 전 exit scope 미정. | daily pair exact expiry와 cutoff 정의. | YYYYMMDD와 YYYY-MM-DD 비교 불일치 후보를 제거하고 exact expiry 사용. | monthly exact expiry; DTE≤4 NON_EXECUTION semantics 보존. | exact expiry를 state/provenance에 보존하고 next session policy 정의. |
| F11 | 수량·승수·반올림 | 현 Futures qty는 option net delta→delta_to_mini_futures_qty. 단위/부호/승수/option sizing 미정. | 현 각 leg qty=1. ratio, multiplier, max qty/payoff 산식 미정. | 현 qty 1 또는 조건부 2, expected profit에 multiplier 적용. spread qty/identity를 일관화. | 현 target Futures qty=min(delta conversion,100), fill 전 target 갱신 관찰. actual filled qty로 재설계. | 현 option qty=1, Futures qty=5. 신규 sizing/role 결정 필요. | 현 qty=1 관찰; marks에 qty/multiplier 누락 가능. quantity-aware valuation 필요. | 현 pair qty>1일 때 value 산식이 qty를 빠뜨릴 가능성. 수량 반영 검증. | 현 CALL qty=1, PUT high-vol qty=2, 기타 1.5 정수 절삭으로 1이 되는 경로. sizing 승인 필요. | 현 pair qty default=1. fill, mark, close 모두 actual qty/multiplier 사용. |
| F12 | 프리미엄·비용·증거금·최대손실 | option premium + Futures margin/stress loss + hedge cost를 함께 계산; editable config와 source-backed limits 필요. | 4-leg net premium, fees/slippage, margin, max loss와 naked short risk 계산. | Futures spread margin, expected net after costs, stress loss and account cap. | option inventory cost, Futures margin, delta/gamma stress loss, rebalance costs. | option/Futures structure별 premium, margin, fees, slippage and worst-case risk 계산. | pair premium, fees, slippage, daily and account caps. | weekly premium, fees, slippage, account exposure and expiry risk. | monthly pair plus overlay premium, margin, DTE and max loss. | overnight premium, fees, slippage and overnight gap stress loss. |
| F13 | 주문 유형·가격·재가격 | order type, tick, limit collar, repricing interval/timeout은 미정; quote freshness gate 필수. | group preflight 이후 4-leg별 price/reprice/cancel/replace 규칙 미정. | spread price relation, execution sequence, reprice/cancel policy 미정. | rebalance price, throttle/hysteresis, target-vs-filled quantity 규칙 필요. | option/Futures entry and exit order sequence, limit/reprice policy 미정. | pair order type, LIMIT cutoff/fallback semantics를 official session 기준으로 확정. | pair limit/reprice와 expiry close urgency 정의. | base/add-on orders and pending tranche cancellation semantics 정의. | 15:10 entry order의 official session 허용 여부와 overnight order policy 미정. |
| F14 | 전체 레그 사전검증 | all required legs의 identity, quote, size, cost, aggregate exposure 검사; 하나라도 실패하면 group 미전송. | 4-leg group preflight; one leg fail이면 나머지만 제출 금지. | actual spread legs and identities 검증; same identity로 상쇄되는 plan 차단. | option position/Greeks/Futures plan이 동일 snapshot과 coverage 관계인지 확인. | 승인된 역할/구조 전체 preflight; Strategy 5 구조 결정 전 신규 order plan 차단. | PUT+CALL quote, expiry, multiplier, liquidity, premium cap group preflight. | weekly pair coverage, cost, exact expiry group preflight. | CALL+PUT+승인 overlay legs 전체 budget/risk preflight. | PUT+CALL, event window, expiry, overnight risk group preflight. |
| F15 | 부분체결·거절·미체결·취소 race | grouped resolver, partial fills, Futures entry reject and cancel race; fill 전 state/count 갱신 금지. | 현 active state pre-fill. 4-leg actual fill/reject/partial states와 one-sided short exposure policy 필요. | 현 state pre-fill 및 same-identity offset risk. leg fills/true spread exposure 기준 active. | 현 active hedge qty는 target pre-fill. actual filled Futures qty와 target 분리. | rejected/no-route/partial은 실제 fills에 따라 state 유지; timeout은 reject로 단정 금지. | 현 is_active pre-fill; awaiting-fills and one-sided exposure recovery 필요. | 현 insurance_active pre-fill; group fill/partial/reject state 필요. | base/overlay state pre-fill 가능; add-on reject/partial reconciliation 필요. | awaiting-fills 존재하나 one-sided exposure timeout/hedge/close policy 부족. |
| F16 | 헤지·재조정·추가 레그 | delta hedge trigger, direction, ratio, cap, unwind 미정. 현 1.5-point reversal은 승인된 목표가 아님. | 현 4-leg 외 자동 protective leg 추가 금지; 추가 헤지 필요성은 payoff/risk 분석 후 결정. | Futures는 alpha/spread/hedge 중 역할을 먼저 분류; 옵션 대체는 그 뒤 결정. | delta-driven rebalance 핵심; source-backed Greeks, target-vs-filled, max exposure/hysteresis 필요. | Futures 5의 역할, conditional reverse/rehedge and option protection 신규 명세에서 결정. 폐기안 BUY2 재사용 금지. | 별도 hedge leg 임의 추가 금지; pair 자체의 insurance coverage를 정의. | extra hedge leg 미정; weekly pair의 exposure/coverage 측정 필요. | PUT overlay trigger, qty, repeat limit, budget and fill-driven state 정의. | overnight pair protection vs next-day shock/trailing, additional hedge policy 미정. |

## C. 보유·청산·회계·복구·위험 판단 요소

| ID | 판단요소 | Strategy 1 Tail Defense | Strategy 2 Asymmetric Trap | Strategy 3 Statistical Arbitrage | Strategy 4 Gamma Scalping | Strategy 5 Gap Divergence | Strategy 6 Daily Tail Insurance | Strategy 7 Weekly Volatility Skew Insurance | Strategy 8 Macro Regime Monthly Strangle | Strategy 9 Event Overnight Insurance |
|---|---|---|---|---|---|---|---|---|---|---|
| F17 | 보유 상태·노출 산출 | actual option/Futures lots, leg qty, fence/hedge relation, net Greeks 대사. | 4-leg MTM, net Greeks, uncovered short exposure and group state. | spread identities/qty, basis exposure, current P&L and holding time. | option inventory and actual Futures hedge; target-vs-filled net delta. | option premium/MTM and actual Futures position separately; gap movement is not fill evidence. | pair marks, qty, multiplier, premium spent and actual P&L. | quantity-aware pair value and peak/trailing state. | base pair, overlay qty, premium spent, exact expiry and actual P&L. | entry fill prices, pair marks, overnight gap and open exposure. |
| F18 | 손절·위험 종료 | 현 1.5pt reversal is Futures hedge unwind observation; option/strategy stop and max loss 미정. | 현 -30% underlying-return proxy is not option P&L. actual P&L/max-loss trigger 미정. | 현 z stop 3.5, cutoff/timeout; actual spread stress loss and trigger priority 미정. | equity threshold unwinds Futures hedge only; option inventory terminal stop 미정. | 현 stop based on underlying expected move, not option premium loss. New stop policy required. | cutoff/trailing exist; actual pair P&L stop and hard max-loss policy 미정. | 현 pair value 20% decline and expiry close; fees/actual P&L/max loss policy 미정. | intrinsic proxy and DTE≤4 non-execution; hard max-loss policy 미정. | next-day stabilization/shock/trailing; max overnight loss boundary 미정. |
| F19 | 익절·trailing | profit_target=500000, profit_buffer, coverage_ratio appear unused in evaluate. New target policy 미정. | 현 +30% activation and 85/88/90% retention tiers; actual P&L source and tier basis 미정. | convergence/profitability/trailing; P&L attribution and high-watermark source need verification. | 현 >30000 high-watermark and 85/88/90% retention closes Futures hedge only. | 현 underlying-based trailing; premium/mark-based trigger must be separately defined. | 현 intrinsic proxy and 1.5x/2x spend tiers; actual pair MTM required decision. | 현 combined mark peak with 20% decline; qty-aware MTM and expiry priority needed. | intrinsic proxy/85% retention and high-watermark update ordering need redesign. | current pair profit trail with 30% giveback after shock; no-shock exit semantics need validation. |
| F20 | 시간 종료·만기·롤오버 | every leg exact expiry/session cutoff and flat-confirmed reset; current DTE≤4 one-leg path insufficient. | all four leg expiry/last-trade/close policy missing. | elapsed-time and Futures expiry/roll policy; evaluate-call count is not wall time. | option expiry vs Futures expiry and session-end hedge policy. | 30 evaluate calls is not elapsed time; option/Futures expiry and rollover missing. | official daily cutoff, pair close and residual-lot policy. | exact weekly expiry normalization, close cutoff and week rollover. | preserve DTE≤4 HOLD_LONG_ATTACK as non-execution until new approval; monthly expiry details needed. | next session/overnight expiry, contract tradability and close policy. |
| F21 | 청산 범위·수량·방향 | authoritative open lots by contract/role determine close side and remaining qty. | all actual open 4-leg lots grouped; each leg's remaining qty independent. | actual spread legs close by identity/qty; Index is not a tradable leg. | hedge-only event closes Futures only; terminal scope includes option lots only if explicitly defined. | gap-fill non-terminal vs terminal stop/timeout/trailing close scope must be explicit; currently unresolved. | close both PUT/CALL open lots using actual qty. | close both weekly legs; group complete only after both flat. | close base CALL/PUT and overlay actual qty, not just proposal signal. | close both overnight legs from authoritative lots; partial close leaves exit pending. |
| F22 | 손익·수수료·슬리피지 | per-fill prices, multiplier, fees, slippage, option/futures P&L and hedge attribution. | all 4-leg MTM/payoff/fees and max loss; underlying return is not option P&L. | spread P&L, contract multiplier, costs; no assumed same-identity offset. | option and Futures hedge P&L separately plus combined attribution. | actual option premium and Futures P&L separately; index movement is not option P&L. | actual pair marks/fills, qty/multiplier/fees; intrinsic proxy not authoritative P&L. | pair value includes qty/multiplier, fees and realized close fills. | per-leg and overlay fills/marks; default zero premium spent not accepted as actual cost. | pair entry premium from actual fills; marks, qty, multiplier and overnight P&L. |
| F23 | 트리거 충돌·종료 우선순위 | expiry/stop/hedge/entry collision; no new entry during exit pending. | stop/trailing/cutoff/expiry simultaneous trigger precedence. | market cutoff, z stop, convergence, trailing, timeout priority. | risk-off vs rebalance vs trailing hedge close precedence. | gap-fill Futures close vs terminal close: keep economic scope and precedence distinct. | trailing vs cutoff/expiry precedence. | trailing vs expiry-day close precedence. | macro add-on vs rebuild vs DTE vs terminal close; NON_EXECUTION not order. | stabilization close vs shock/trailing vs expiry priority. |
| F24 | 공통 lifecycle·provenance | common state machine, run/group/leg/order/execution IDs, per-leg fills and group flat confirmation. | 4-leg per-leg state plus group exposure, exit batch and actual flat confirmation. | each spread leg distinct identity and role; pending-exit/reconciliation state. | option lifecycle and Futures hedge lifecycle explicitly linked but distinct. | option/Futures legs linked by logical group but distinct instrument and exit scope. | pair awaiting fills, active, exit pending, flat confirmed. | weekly pair fill, expiry management, flat confirmed. | base pair, overlay, pending cancellation and HOLD_LONG_ATTACK distinct states. | awaiting fills, overnight, next-session stabilization, close/expiry states. |
| F25 | 재시작·중복·timeout 복구 | restore orders/fills/open lots/fence/hedge relation; no memory-only reset. | restore all legs, cooldown/daily cap/trailing; no duplicate entry. | restore pending spread/exit and regime; resolve pending-path error before implementation. | restore actual hedge qty and option ownership/Greeks; recalc target after reconcile. | restore option/Futures state and terminal/non-terminal scope; no reset after partial fill. | restore pair fills, premium spent, marks and cutoff state. | restore expiry, quantity, marks and peak; normalize expiry representation. | restore base/overlay qty and pending cancel; do not recreate duplicate pair. | restore entry premium, expiry, next-session window and one-sided exposure. |
| F26 | 전략 간·계좌 전체 위험 | aggregate option short/long, Futures exposure, premium and margin; provenance prevents duplicate count. | short-option uncovered risk and correlated exposures across strategies. | shared Futures identity concentration and spread stress loss. | account delta/gamma and Futures hedge ownership/net exposure. | combined gap-shock risk across option/Futures and other strategies. | daily pair premium and overlapping account insurance positions. | weekly insurance overlap with other expiries/strategies. | monthly strangle and extra PUT overlay overlap by expiry bucket. | overnight gap stress and overlapping daily/weekly/monthly protection. |
| F27 | 오류·데이터 불가 시 처리 | BLOCKED/UNAVAILABLE; do not infer price/delta/expiry; reconcile existing lots separately. | block new 4-leg group; preserve actual short exposure and reconciliation state. | block new spread; pending execution stays reconciliation required. | no hedge from stale Greeks; preserve and reconcile actual Futures position. | block new entry/hedge on missing contract/quote; never infer close complete. | block new pair; preserve active state and reconcile existing lots. | block new weekly pair; expiry close needs authoritative identity and position. | block add-on/rebuild when risk/quote/expiry missing; don't promote NON_EXECUTION. | block entry when session/contract/quote unavailable; preserve overnight position. |
| F28 | 설정 한도·자본·재개 | editable total capital, strategy premium cap, strategy/account max loss, margin and hedge cap. Resume only after full reconcile. | editable premium/max-loss/qty and account limits; resume after all 4 legs reconciled. | editable margin/stress-loss/cost and account limits; expected profit is not risk cap. | editable hedge notional/margin/max loss; resume after Greeks/position/actual hedge match. | editable premium, max loss and account aggregate exposure; role unresolved blocks implementation. | editable daily premium/max loss/account cap; pair state reconciled before resume. | editable weekly premium/max loss/account cap; expiry and positions reconciled. | editable monthly/overlay premium and max loss; budget and quantities reconciled. | editable overnight premium/stress loss; session and pair state reconciled. |
| F29 | 필수 테스트 시나리오 | official open vs first tick, fence boundaries, stale/missing delta, partial/reject, DTE and all-leg flat. | 4-leg fill/partial/reject/cancel race, threshold boundaries, cooldown, actual P&L, expiry. | distinct spread identities, same-identity collision, pending regime error, z boundary, timeout/restart. | missing Greeks, target-vs-filled, deadband, partial rebalance, risk-off unwind, ownership. | gap up/down, official open, Futures role, nonterminal vs terminal exit, option partial, expiry/restart. | vol 1.3 boundary, missing quote, qty/multiplier MTM, cutoff, partial close/restart. | new-week duplicate, expiry normalization, qty>1 MTM, 20% trailing boundary, cancel race. | DTE 15/4, 1.5 qty rounding, add-on plan, pending cancellation, trailing update, max loss. | 15:10 session gate, one-sided fill, 1% shock, 30% giveback, no-shock close, next-session restart. |

## D. 모든 전략에 공통으로 적용할 기준과 완전성 게이트

| 공통 ID | 판단요소 | 통합 설계 기준 | 완료 증거 |
|---|---|---|---|
| C01 | 데이터 출처·시점 | source, instrument identity, event/received timestamp, unit, freshness, provenance 보존. 누락값을 추정·합성해 authoritative input으로 쓰지 않음. | source contract 및 missing/stale/mismatch tests |
| C02 | 계약 identity | 일반 KOSPI200 옵션, type, strike, exact YYYYMMDD expiry, instrument ID, multiplier를 authoritative Option Master로 resolve. Futures identity는 별도. | identity trace와 mismatch tests |
| C03 | 신호·주문·체결 분리 | signal, plan, risk approval, order ACK, partial fill, fill, position update, realized P&L을 서로 다른 상태로 관리. | run/group/leg provenance end-to-end evidence |
| C04 | Group preflight | 모든 필수 레그를 하나의 snapshot으로 검증. 하나라도 identity/quote/cost/risk 실패면 그룹 미전송. | group-wide preflight rejection tests |
| C05 | Partial/cancel/retry | cancel request ≠ cancel complete. timeout은 reject 증거가 아님. retry는 authoritative remaining quantity만 사용. | partial fill, cancel race, duplicate order tests |
| C06 | Group completion | actual fills와 position read model이 일치하고 모든 required close lots가 flat일 때만 COMPLETED/state reset. | no-early-reset and flat reconciliation tests |
| C07 | 손익·비용 | actual fills, authoritative mark, multiplier, qty, fee, slippage 사용. underlying/intrinsic proxy를 actual option P&L로 표시하지 않음. | contract-level P&L and fee-source tests |
| C08 | 계좌 위험 | total capital, strategy max premium, strategy/account max loss, margin, liquidity/spread, concurrency를 versioned editable config로 관리. | runtime enforcement evidence and boundary tests |
| C09 | 전략 간 노출 | ownership/provenance로 중복합산 방지. 서로 다른 전략 노출을 명시 규칙 없이 자동 netting하지 않음. | account aggregate risk test |
| C10 | 재시작·복구 | restart 시 memory state를 reset하지 않고 orders/fills/open lots/contracts/pending groups를 restore/reconcile. | restart with open/partial/unknown tests |
| C11 | 시간·만기 | KST official calendar, session, holiday, exact last trading date, expiry and overnight policy 분리. | open/close/expiry/week/month boundary tests |
| C12 | Fail closed | unknown state/source/contract/risk는 BLOCKED/UNAVAILABLE/RECONCILIATION_REQUIRED. 안전 재개 전 신규 주문 금지. | unavailable paths stop before routing |
| C13 | 추적성 | 각 Fxx/Cxx는 spec version, code path/symbol, test ID, evidence, result, approval version과 연결. | complete requirement-spec-code-test matrix |
| C14 | 환경 경계 | Virtual/VTS는 Live 결과가 아님. 별도 명시적 승인 없이는 KIS Live 주문 금지. | environment provenance and order-call audit |

| Gate ID | 전략별 완전성 질문 | PASS 조건 |
|---|---|---|
| G01 | 목적·보호 대상·경제적 역할이 정의되었나? | 각 레그의 목적과 payoff/risk가 정량적으로 설명됨 |
| G02 | 진입·대기·추가·반전 조건이 정의되었나? | 입력, 산식, 단위, threshold, 경계, 우선순위가 명시됨 |
| G03 | 계약·행사가·만기·승수·수량이 결정되나? | authoritative identity와 sizing/rounding/cap이 명시됨 |
| G04 | partial/no-fill/reject/cancel-race/timeout/retry가 정의되었나? | 모든 레그의 state transition과 복구가 명시됨 |
| G05 | hedge/rebalance/overlay가 정의되었나? | trigger, target qty, actual filled qty, residual exposure, unwind/rehedge 명시 |
| G06 | stop/take-profit/trailing/time exit가 정의되었나? | authoritative P&L basis, threshold, tie-break priority 명시 |
| G07 | 만기·롤오버·세션 경계가 정의되었나? | exact expiry/calendar와 각 레그의 close/flat rule 명시 |
| G08 | 비용·자본·최대손실·계좌 전체 위험이 계산되나? | premium, fees, slippage, margin, max/stress loss, cross-strategy risk 계산 |
| G09 | 장애·재시작·중복·복구가 정의되었나? | authoritative reconciliation과 safe resume criteria 존재 |
| G10 | 명세-코드-테스트 추적이 완전한가? | 모든 Fxx가 code path, test ID, evidence/result에 연결됨 |
| G11 | 가정·외부 의존성·미결정 사항이 드러나나? | 미정 항목마다 영향, 필요한 source/decision, 상태가 있음 |
| G12 | 검증과 승인이 분리되었나? | 검증 완료가 자동 승인이 아니며 approved version/scope가 기록됨 |

## E. 다음 검증 순서

1. F01~F29를 Strategy 1~9 각각에 대해 현재 코드·관련 source·유효 확정 Decision Log와 대조한다.
2. 각 칸을 현행 사실, 신규 설계 결정, 외부 데이터 의존성, 미결정, BLOCKED로 분류한다. 과거 값은 근거 없이 신규 설계 값으로 복사하지 않는다.
3. Strategy 1~9 상세 명세와 이 통합표를 상호 대조해 모순·누락을 찾는다.
4. C01~C14 공통 기준과 G01~G12 완전성 게이트를 전략별로 판정한다.
5. 검증 결과와 미결정 사항을 사용자에게 보고한다. 사용자 승인 전에는 전략 코드를 변경하지 않는다.

현재 판정: **DRAFT / COMPLETENESS VALIDATION NOT PASSED / IMPLEMENTATION BLOCKED**. 문서 작성 단계에서 테스트는 실행하지 않았고, KIS Live 주문도 실행하지 않았다.

---

## F. Strategy 1~9 상세 명세 대조 현황

| 전략 | 상세 명세 v0.2 | F01~F29 매핑 | 상태 머신/수용 게이트 | 현 판정 |
|---|---|---:|---|---|
| Strategy 1 Tail Defense | strategy_1_tail_defense_spec_v0.2.md | 29/29 | 작성됨; code/runtime lifecycle 미검증 | DRAFT / BLOCKED |
| Strategy 2 Asymmetric Trap | strategy_2_asymmetric_trap_spec_v0.2.md | 29/29 | 작성됨; duplicate entry/partial lifecycle 미검증 | DRAFT / BLOCKED |
| Strategy 3 Statistical Arbitrage | strategy_3_statistical_arbitrage_spec_v0.2.md | 29/29 | 작성됨; tradable spread identity unresolved | DRAFT / BLOCKED |
| Strategy 4 Gamma Scalping | strategy_4_gamma_scalping_spec_v0.2.md | 29/29 | 작성됨; option ownership/delta units unresolved | DRAFT / BLOCKED |
| Strategy 5 Gap Divergence | strategy_5_gap_divergence_spec_v0.2.md | 29/29 | 작성됨; Futures role and actual P&L unresolved | DRAFT / BLOCKED |
| Strategy 6 Daily Tail Insurance | strategy_6_daily_tail_insurance_spec_v0.2.md | 29/29 | 작성됨; pair MTM/partial fill/cutoff unresolved | DRAFT / BLOCKED |
| Strategy 7 Weekly Volatility Skew Insurance | strategy_7_weekly_volatility_skew_insurance_spec_v0.2.md | 29/29 | 작성됨; skew thesis/expiry/qty-aware MTM unresolved | DRAFT / BLOCKED |
| Strategy 8 Macro Regime Monthly Strangle | strategy_8_macro_regime_monthly_strangle_spec_v0.2.md | 29/29 | 작성됨; add-on resolver mismatch/expiry HOLD unresolved | DRAFT / BLOCKED |
| Strategy 9 Event Overnight Insurance | strategy_9_event_overnight_insurance_spec_v0.2.md | 29/29 | 작성됨; after-close gate/one-leg recovery/opening-window exit unresolved | DRAFT / BLOCKED |

판정 해석: 29/29는 판단요소 칸을 작성했다는 구조적 의미일 뿐, 정책 확정·소스 검증·테스트 PASS·사용자 승인 의미가 아니다.

## G. 전략 간 상호작용·충돌 검증표

| ID | 상호작용/충돌 영역 | 영향받는 전략 | 관찰된 충돌·위험 | 통합 목표 규칙 | 현재 상태 |
|---|---|---|---|---|---|
| I01 | 계좌 총자본·프리미엄·최대손실 | S1~S9 전체 | 전략별 고정 상수와 계좌 전체 예산이 일관되게 강제된다는 증거가 부족하다. 여러 전략이 같은 계좌 자본을 동시에 예약할 수 있다. | 중앙의 versioned editable config: account total capital, per-strategy max premium, per-strategy max loss, account max loss, margin, fee/slippage, effective time/hash. 주문 직전 atomic budget reserve. | **BLOCKED** — 수치·runtime enforcement 별도 검증/승인 |
| I02 | 동일 Futures identity 상쇄/중복 헤지 | S3, S4, S5, S1 | S3 adapter가 동일 Futures identity의 반대 방향 동일 수량 leg를 만들 수 있다. S4/S1도 계좌 delta와 strategy-owned lots의 관계가 불명확하면 중복 hedge 가능. S5 Futures 5는 역할이 미확정. | Futures legs must have distinct intended economic roles; reject same-identity opposite legs unless formally proven as valid spread. Aggregate target delta from authoritative option lots and actual Futures fills. | **BLOCKED** — S3 identity/role 결정 필요; S5 No.1151 분류 필요 |
| I03 | 옵션 보유 포지션과 delta attribution | S1, S4, S5 | 전략별 lots, aggregate options.delta, Futures hedge ownership의 출처가 다를 수 있어 이미 헤지된 노출을 다시 헤지할 수 있다. | Every option lot has owner/group/contract/qty/multiplier/Greeks provenance; delta aggregation excludes duplicate observations and maps actual Futures fills to hedged exposure. | **BLOCKED** — source/ownership contract incomplete |
| I04 | 보험 pair 중복·상관 tail risk | S6, S7, S8, S9 and S1 | Daily, weekly, monthly, overnight pairs may overlap by strike/expiry and cover same tail exposure, increasing premium and giving false impression of independent protection. | Account-level expiry-bucket and scenario-based stress aggregation; protection credit only for verified payoff correlation/ownership; premium counted once per actual fill. | **BLOCKED** — correlation/payoff model missing |
| I05 | multi-leg partial fill and cancel race | S1, S2, S3, S5, S6, S7, S8, S9 | Multi-leg plans are not atomic; several strategies update state before fills or lack entry partial-recovery. Cancel request may race with fills. | Each leg has independent order/fill/cancel state; group exposure recomputed on each report; recovery uses actual open lots; no state reset until all required lots flat and reconciled. | Common contract defined; per-strategy runtime coverage incomplete |
| I06 | strategy/account P&L attribution | S2, S3, S4, S5, S6, S7, S8, S9 | Some stop/trailing decisions use underlying/intrinsic proxy; others use portfolio-wide P&L; quantity/multiplier/fees may be omitted. | Separate underlying trigger metrics from actual option/Futures MTM; per-fill multiplier/qty/fees/slippage and strategy ownership feed realized/unrealized P&L. | **BLOCKED** — source-backed P&L and fee ledger proof required |
| I07 | expiry/session/overnight boundaries | S1~S9 | Exact expiry string/date, first tick vs official open, evaluate-call count vs elapsed time, 15:00/15:15 windows and overnight reset vary. | Shared KRX calendar/session contract; exact YYYYMMDD identity; explicit strategy-specific terminal policy; no reset until flat; timer conditions use >= where deadline semantics require it. | **BLOCKED** — strategy-specific decisions needed |
| I08 | risk exits vs profit/hedge exits | S1~S9 | Simultaneous max-loss, expiry, trailing, hedge unwind and entry/rebuild can generate conflicting actions or unclear close scope. | One deterministic per-strategy trigger priority plus account-level emergency risk override; terminal exit plan must specify all required legs and prohibit new entry while pending. | **BLOCKED** — priority tables require policy approval |
| I09 | data freshness and unavailable handling | S1~S9 | Some providers have timestamp checks, but some features collapse unavailable into false/zero or missing quote simply suppresses action. | UNAVAILABLE/BLOCKED distinct from valid false/zero; entry blocked on stale/mismatched data; existing exposure enters explicit reconciliation/emergency management state. | Common rule defined; runtime enforcement unverified |
| I10 | restart, duplicate signal and state restore | S1~S9 | Memory reset can erase strategy state while actual lots/orders remain; daily/weekly flags and timers may remain stale or fail to reset. | Durable state linked to authoritative orders/fills/positions/config hash; restart always reconcile before evaluation; idempotent group IDs; no blind retries. | **BLOCKED** — persistent restore evidence absent |
| I11 | Strategy 5 Futures role vs option alternative | S5; shared with S1/S4 risk model | Current Futures qty=5 and option qty=1 are observed code. No.1151 says classify Futures legs as PRIMARY_ALPHA/SPREAD vs HEDGE before conversion. No.1168 Option BUY 2 proposal is 폐기됨. | Reclassify each Futures leg with evidence; convert only verified hedge-purpose exposure after option contract/Greeks/premium/max-loss analysis; no blanket Futures replacement. | **미결정 / 사용자 승인 필요** |
| I12 | Strategy 3 spread identity and role | S3; shared Futures execution | Same-identity opposite-side plan may cancel economically while presenting as a two-leg spread. | Define actual tradable spread legs first; no plan if leg identities, signs, units or economic payoff are undefined. | **BLOCKED** |
| I13 | Strategy 4 basecamp and hedge ownership | S4; S1/S3 shared Greeks | Basecamp is NON_EXECUTION; hedge can be emitted without confirmed option inventory. Portfolio delta may include positions not owned by Strategy 4. | Hedge only against authoritative eligible option lots; state target qty separately from actual filled Futures qty; define if basecamp is state-only or executable. | **BLOCKED** |
| I14 | Strategy 8 macro add-on intent | S8 | MACRO_HEDGE_SCALE_UP PUT-only proposal may resolve to full CALL+PUT pair; state flag changes before fill. | Distinct add-on resolver and parent group; only incremental PUT quantity routed after group-wide risk preflight. | **BLOCKED** |
| I15 | daily/weekly/overnight re-entry | S6, S7, S9 | Date/week flags, expiry and restart can permit duplicate entry or suppress future entry while old position remains. | New daily/weekly/overnight cycle begins only after prior group has authoritative flat confirmation and calendar boundary is validated. | **BLOCKED** |
| I16 | Editable config consistency | S1~S9 | Strategy constants may be configurable but common account total capital/premium/max-loss enforcement not proven in actual Virtual routing path. | One schema/version/hash; per-strategy overrides bounded by account cap; validate at startup and each preflight; reject missing/invalid config. | **BLOCKED** — no implementation approval yet |

## H. 공통 상태 머신 계약 — 전략별 상태에 적용

| 공통 상태 | 진입 조건 | 허용 행동 | 금지 행동 / 실패 전이 |
|---|---|---|---|
| DISABLED | Strategy OFF or permission absent | monitor/reconcile existing positions only | no new entry; do not forget open lots |
| WAITING_FOR_SESSION | Official session/calendar valid | validate sources and entry window | no entry on inferred session/open |
| DATA_WARMUP | history/quote/Greeks window incomplete | gather authoritative data | do not treat missing as false/zero |
| PRE_ENTRY_CHECK | signal exists and all sources valid | contract/quote/risk/capital preflight | no order if any required leg fails |
| ENTRY_PLANNED | group/legs/limits/idempotency key persisted | submit approved per-leg orders | no claim of fill/position before reports |
| ENTRY_WORKING | one or more orders acknowledged | reconcile every leg state | no duplicate group; cancellation not complete until confirmed |
| PARTIALLY_EXPOSED | some legs filled and others not | compute actual and worst-case exposure; apply approved recovery | no assumption of atomic fill; no blind reset |
| ACTIVE | actual fills and open lots reconciled | evaluate strategy signals and risk | no new group while policy forbids; no proxy labeled actual P&L |
| REBALANCE_PENDING | approved hedge adjustment needed | submit adjustment based on actual filled qty | target qty is not actual qty |
| EXIT_PENDING | terminal trigger accepted and exit batch persisted | close actual open lots; track partial/cancel race | no entry/rebuild; no flat claim from request/ACK |
| EXPIRY_MANAGEMENT | contract nearing/at exact expiry or terminal session | approved close/hold policy and reconcile | no DTE-only contract identity or implicit HOLD-to-close conversion |
| RECONCILIATION_REQUIRED | restart, timeout, data mismatch, unknown order/fill/position | query authoritative orders/fills/positions; repair ledger under policy | no new entry, no blind retry, no silent reset |
| FLAT_CONFIRMED | all required open lots zero and executions reconciled | final fees/P&L/accounting | no close completion based solely on group_complete flag |
| CLOSED | flat + P&L finalized + provenance stored | start next lifecycle when calendar permits | do not reopen until policy allows |

## I. 미결정·승인 필요 항목 통합 등록부

| ID | 결정 항목 | 근거/검증 필요 | 영향을 받는 전략 | 현재 상태 |
|---|---|---|---|---|
| U01 | Strategy 1 target payoff and 3-leg structure | option chain/payoff/stress/cost analysis | S1 | 미결정 |
| U02 | Strategy 2 4-leg payoff, stop/trailing P&L basis | exact contract marks, payoff and stress scenarios | S2 | 미결정 |
| U03 | Strategy 3 tradable spread instruments and leg identities | source/identity/multiplier and spread unit validation | S3 | BLOCKED |
| U04 | Strategy 4 eligible option lots, delta units and basecamp role | option positions, Greeks, multipliers and account delta ownership | S4 | BLOCKED |
| U05 | Strategy 5 Futures PRIMARY_ALPHA/SPREAD vs HEDGE, quantities and terminal sequence | No.1151 role analysis, payoff/margin/fees; exclude retired No.1168 | S5 | 사용자 결정/승인 필요 |
| U06 | Strategy 6 actual pair MTM, partial pair recovery and daily cutoff | fills/marks/fees/calendar and partial-fill scenarios | S6 | 미결정 |
| U07 | Strategy 7 whether IV skew is actually a trigger; expiry normalization | same-expiry IV surface, calendar and contract identity | S7 | 미결정 |
| U08 | Strategy 8 add-on plan, normal PUT rounding and DTE<=4 HOLD policy | macro stress, exact add-on quantities, expiry risk | S8 | 미결정 |
| U09 | Strategy 9 latest entry time, official open, skipped-window exit | official KRX session/open, next-day calendar and fallback close | S9 | BLOCKED |
| U10 | Account total capital and strategy/account risk numbers | current capital, quotes, fees, margin, stress loss and editable schema | S1~S9 | 숫자 미확정; 별도 승인 |
| U11 | Common order/partial/cancel/restart state persistence | actual Virtual runtime evidence and position read models | S1~S9 | 미검증 |
| U12 | Account-wide aggregate exposure/correlation/netting policy | all strategy positions, shared contracts, correlated stress scenarios | S1~S9 | 미결정 |
| U13 | Authoritative P&L/fee/multiplier source | fill ledger, quote/mark source and contract-level attribution | S1~S9 | 미검증 |
| U14 | Exact expiry/session/rollover common service | KRX calendar, YYYYMMDD identities, last trading day | S1~S9 | 미검증 |
| U15 | Shrimp Resume Context update/access | currently no accessible Shrimp task-manager action exposed to this session; cannot claim updated | project workflow | UNAVAILABLE — needs accessible action |

## J. 완전성 게이트 최종 예비 판정

| Gate | 검증 항목 | 현재 증거 | 판정 |
|---|---|---|---|
| G01 | 목적/경제적 역할 | F01 rows exist, but several payoff/hedge roles unresolved | BLOCKED |
| G02 | entry/scale/exit signals | per-strategy F05/F06 and trigger tables exist; several priorities unresolved | BLOCKED |
| G03 | contract/expiry/qty/multiplier | per-strategy contract notes exist; expiry/product/rounding gaps remain | BLOCKED |
| G04 | partial/reject/cancel/timeout | common state machine defined; runtime evidence incomplete | BLOCKED |
| G05 | hedge/rebalance/overlay | S3/S4/S5/S8 role/identity conflicts unresolved | BLOCKED |
| G06 | stop/target/trailing/time exits | proxy P&L and trigger priorities unresolved | BLOCKED |
| G07 | session/expiry/rollover | exact expiry/session edge cases unresolved in multiple strategies | BLOCKED |
| G08 | capital/premium/max-loss/account risk | editable config target identified; numbers and runtime enforcement not approved | BLOCKED |
| G09 | failure/restart/recovery | reconciliation target defined; persistence and scenario evidence absent | BLOCKED |
| G10 | requirement-spec-code-test traceability | factor-level code-path groups identified; complete test IDs/evidence map not built | BLOCKED |
| G11 | assumptions/external dependencies | 15 unresolved items registered, more may emerge during testing | DRAFT |
| G12 | validation separated from approval | all v0.2 specs marked draft/unapproved; no implementation permission | PASS (process rule only) |

## K. 상태 및 다음 순서

1. Strategy 1~9 v0.2 상세 명세: **구조 작성 완료(각 F01~F29)**. 각 문서는 초안이며 완전성 검증을 통과하지 않았다.
2. 통합설계표 v0.3: **초안 작성 완료**. 상호작용/충돌 I01~I16, 공통 상태 머신, 미결정 등록부 U01~U15, G01~G12 예비 판정을 추가했다.
3. 전체 명세-코드-테스트 추적: **미완료**. 모든 Fxx에 실제 test ID/log/E2E 증거를 연결해야 한다.
4. 시나리오 검증: **미실행**. 이번 작업에서는 문서 구조만 확인했으며 전략 테스트나 Virtual E2E를 PASS로 주장하지 않는다.
5. 사용자 승인: **없음**. 전략 로직/아키텍처/데이터 기준 코드 변경, commit/push는 승인 전 금지.
6. KIS Live: 별도 명시적 승인 없이는 주문 금지.
7. Shrimp Resume Context: 현재 세션에서 접근 가능한 task-manager action이 없어 업데이트 여부를 확인할 수 없다. 갱신했다고 주장하지 않는다.

최종 예비 판정: **DRAFT / COMPLETENESS VALIDATION NOT PASSED / IMPLEMENTATION BLOCKED**.

## L. 요구사항-명세-코드-테스트 추적표 v0.1

- 로컬 파일: docs/strategy_specifications/03_requirements_spec_code_test_traceability_v0.1.md
- 포함 행: Strategy 1~9의 F01~F29 = 261개, 공통 C01~C14 = 14개, 완전성 게이트 G01~G12 = 12개.
- 각 전략 factor 행에는 명세 경로, 주요 코드/런타임 경로, 테스트 파일 후보를 연결했다.
- 정확한 Test ID, 실행 명령, 로그/증거, 실제 결과는 아직 매핑하지 않았으며 모두 TBD/NOT_RUN/NOT_MAPPED로 유지한다.
- 따라서 추적표 산출물은 생성됐지만 G10은 계속 BLOCKED다. 이 표는 테스트 PASS나 명세 완전성 PASS의 증거가 아니다.

## M. 정상·경계·예외·복구 시나리오 테스트 계획 v0.1

- 로컬 파일: docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_v0.1.md
- Strategy 1~9: 정상/경계/예외/복구 각 1개 계획 row씩, 총 36개 전략별 scenario group.
- Cross-strategy interaction scenarios: 16개.
- 모든 케이스는 NOT_RUN이며, 승인된 명세와 exact Test ID/fixture/log mapping 전까지 실행 결과로 취급하지 않는다.
- Test plan exists; actual scenario execution is not performed. G04/G06/G09/G10 remain BLOCKED.

# S1 direct-user-intent amendment — v0.4 draft
- Status: draft / unverified / unapproved. Additive amendment; v0.3 preserved.
- S1 direct user intent dated 2026-10-12 controls where old S1 cells conflict. Other strategy cells remain unchanged.

## S1 factor classification
| Class | Count | Meaning |
|---|---:|---|
| User-intent confirmed | 15 | Explicit intent, not validation or approval |
| Configurable/provisional | 12 | Editable settings; null/PROVISIONAL blocks new orders |
| User confirmation required | 2 | Only unresolved F-level policy items; new U entries preserve other unknowns |
| Total | 29 | F01–F29 classified |

S1 target: base long CALL/PUT one contract each at ATM ±12.5; option shorts under combined cap 10, hedge buys excluded from that count; option-only hedge at configurable distance to nearest short strike, 1:1 against actual linked short residual; candidate match to sale-time premium, liquidity tie-break; LIMIT reservation, 30-minute wait, cancel-confirm and late-fill reconciliation before candidate descent; hedge release at ±5.0pt; DTE≤4 full close of all S1 short/hedge/base strangle legs. No Mini Futures hedge. Every factor is classified in strategy_1_tail_defense_spec_v0.3.md §2.

## Existing unresolved register disposition
| Existing U | S1 disposition | Basis |
|---|---|---|
| U01 target payoff/3-leg structure | Resolved for core structure; short direction, month gap, and premium-match semantics are resolved below | User §1.2–7 |
| U10 capital/premium/max-loss values | Moved to editable settings; values provisional | User §1.13 |
| U11 partial/cancel/restart persistence | Still needs evidence/confirmation | Draft policy is not runtime proof |
| U12 account aggregate risk/correlation/netting | Editable limits; aggregation method unresolved | §1.13 |
| U13 authoritative P&L/fee/multiplier | Still needs evidence/confirmation | Source-backed ledger not verified |
| U14 expiry/session/rollover | DTE4 and 3–4 day pause resolved; DTE semantics/cutoff remain U22 | §1.10, question 2 |
| U15 Shrimp Resume Context | Unchanged UNAVAILABLE; this task does not access/update Shrimp | Workflow boundary |

U02–U09 are other-strategy items and unchanged.

## New unresolved register
| U | Item | State |
|---|---|---|
| U16 | Call/put short direction and terminology | Resolved (basis: user confirmed 2026-10-12) |
| U17 | 3–4 day idle gap after DTE4 close | Resolved (basis: user confirmed 2026-10-12) |
| U18 | new_short_stop_dte=7 vs DTE4 close | Resolved; setting deleted and retired (basis: user confirmed 2026-10-12) |
| U19 | hedge_trigger_distance_pt candidates | Configurable/tuning: compare 2.5pt and 5.0pt in REAL_VTS; no final value |
| U20 | Sale-time premium matching semantics | Resolved: compare option premium prices themselves (basis: user confirmed 2026-10-12) |
| U21 | Liquidity metric, spread/depth/quote-age gates and tie-break | 사용자 확인 필요 |
| U22 | Calendar vs trading DTE; expiry/last-trading-day source and cutoff | 사용자 확인 필요 |
| U23 | Monthly-start ATM reference and opening gap rule | 사용자 확인 필요 |
| U24 | Short-entry limit price/reprice interval/max attempts | 사용자 확인 필요 |
| U25 | DTE4 close recovery if a leg is rejected/illiquid | 사용자 확인 필요; market fallback 추론 금지 |
| U26 | REAL_VTS tuning/validation dataset IDs, split and acceptance criteria | 설정값으로 이관; 검증 미완료 |
| U27 | Unit/economic meaning of capital_per_contract=25,000,000 | 사용자 확인 필요 |
| U28 | Short accumulation step anchor refresh policy (last short vs every step) | 사용자 확인 필요; target logic absent in current code |
| U29 | Whether separate take-profit/trailing policy exists | 사용자 확인 필요; do not infer |

## S1 interaction register I01–I16 delta
| I | S1 update | Status |
|---|---|---|
| I01 | Editable capital/premium/max-loss/margin; null/PROVISIONAL blocks new orders | BLOCKED pending values/runtime enforcement |
| I02 | S1 Futures hedge removed from target; S3/S4/S5 Futures role issue remains separate | S1 resolved; global issue BLOCKED |
| I03 | S1 hedge uses linked actual short lots 1:1, not unowned account-wide delta | BLOCKED pending lot ownership evidence |
| I04 | Aggregate S1/S2/S6/S7/S8/S9 quantity, premium, margin and stress exposure by contract/expiry; no duplicate protection credit, no strategy-intent changes | BLOCKED |
| I05 | Cancel-confirm and late-fill rules added | Specified, unverified |
| I06 | Actual fill/qty/multiplier/fees/slippage; no underlying proxy as option P&L | BLOCKED pending ledger proof |
| I07 | DTE4 full-close and 3–4 day monthly pause specified; DTE semantics/cutoff unresolved | BLOCKED |
| I08 | DTE4 suppresses new S1 short/hedge; other simultaneous priority unresolved | PARTIAL |
| I09 | Fail-closed for null/provisional/stale/mismatch | Specified, enforcement unverified |
| I10 | Reconcile before resume; no reset until flat | Specified, persistence unverified |
| I11 | S1 does not convert Futures quantity; S5 No.1151 unchanged | S5 unresolved |
| I12 | S3 spread identity unchanged | BLOCKED |
| I13 | S1 hedge limited to S1-owned linked short lots; S4 ownership issue remains | BLOCKED |
| I14 | S8 add-on unchanged | BLOCKED |
| I15 | S1 next monthly cycle requires prior group flat; other cycles unchanged | Account interaction BLOCKED |
| I16 | S1 schema/version/hash defined; null/provisional fails closed | Runtime enforcement unverified |

## S1 completeness gates
| Gate | Draft status | Remaining issue |
|---|---|---|
| G01 payoff/role | PARTIAL | short direction resolved; payoff/stress model still requires validation |
| G02 entry/scale/exit | BLOCKED | short direction resolved; trigger distance is tunable, DTE7 gate retired |
| G03 contract/expiry/qty/multiplier | PARTIAL | DTE semantics/master/rounding evidence |
| G04 partial/reject/cancel race | SPECIFIED / UNVERIFIED | no scenario execution |
| G05 hedge/rebalance | PARTIAL | premium-price match resolved; trigger tuning and cost gates remain |
| G06 exits | PARTIAL | DTE4/±5 specified; other exits undefined |
| G07 session/rollover | BLOCKED | monthly gap resolved; DTE definition/cutoff remain U22 |
| G08 capital/risk | BLOCKED | provisional/null limits and unvalidated cost model |
| G09 recovery | SPECIFIED / UNVERIFIED | no runtime recovery evidence |
| G10 traceability | BLOCKED | exact tests/logs not run/mapped |
| G11 assumptions/dependencies | DRAFT | U21–U29 open; U16–U20 resolved or settings |
| G12 validation vs approval | PASS (process only) | v0.4 remains draft/unverified/unapproved |

## Historical Decision Log retirement proposals — not executed
No Decision Log item is deleted or changed. If an old S1 rule mandates Mini Futures hedge, short cap 5, 1.5pt release, new_short_stop_dte=7, DTE7 hedge close, or high-volatility-day deferral of base strangle close, propose status “폐기됨” with reason/date 2026-10-12 and the conflicting user clause. Proposal only. Do not reuse retired No.1168 BUY 2. No.1151 role classification and cost/margin gates remain in force; no same-quantity Futures-to-option substitution is implied.

## 9-A. Strict three-way classification of every v0.2 U, S1-relevant G and I
The following classification uses only the three categories requested in the user instruction. “Resolved” means the intent/policy question is settled by the user's direct instruction; it does not mean code or runtime verification passed.

### All existing U01–U15
| Item | Required classification | Reason / scope |
|---|---|---|
| U01 | 확정으로 해결 | S1 core structure specified by user; short direction/month gap/premium match separately resolved below |
| U02 | 사용자 확인 필요 | S2-only payoff/stop basis; outside S1 intent |
| U03 | 사용자 확인 필요 | S3 tradable spread identity; outside S1 intent |
| U04 | 사용자 확인 필요 | S4 eligible option lots/basecamp role; outside S1 intent |
| U05 | 사용자 확인 필요 | S5 Futures PRIMARY_ALPHA/SPREAD vs HEDGE, quantities and exit order; No.1151 remains |
| U06 | 사용자 확인 필요 | S6 pair MTM/partial pair/cutoff; outside S1 intent |
| U07 | 사용자 확인 필요 | S7 IV skew trigger/expiry normalization; outside S1 intent |
| U08 | 사용자 확인 필요 | S8 add-on/rounding/DTE policy; outside S1 intent |
| U09 | 사용자 확인 필요 | S9 latest entry/open/stabilization close; outside S1 intent |
| U10 | 설정값으로 이관 | capital/premium/max-loss values editable, but provisional/null until verified and approved |
| U11 | 사용자 확인 필요 | common partial/cancel/restart persistence has no current runtime evidence |
| U12 | 설정값으로 이관 | account aggregate limits editable; correlation/netting model remains an explicit blocker |
| U13 | 사용자 확인 필요 | authoritative P&L/fee/multiplier source and ledger evidence |
| U14 | 사용자 확인 필요 | DTE4 and monthly pause specified; calendar/trading DTE and authoritative cutoff remain U22 |
| U15 | 사용자 확인 필요 | Shrimp Resume Context currently UNAVAILABLE; this task did not update it |

### All completeness gates G01–G12
| Gate | Required classification | Reason |
|---|---|---|
| G01 payoff/role | 사용자 확인 필요 | short direction resolved; payoff/stress validation remains incomplete |
| G02 entry/scale/exit | 사용자 확인 필요 | short direction resolved; trigger distance is a tunable setting; DTE7 gate retired |
| G03 contract/expiry/qty/multiplier | 사용자 확인 필요 | DTE semantics/master/rounding evidence remains open |
| G04 partial/reject/cancel race | 사용자 확인 필요 | transition is specified, but tests/runtime evidence are NOT_RUN |
| G05 hedge/rebalance | 사용자 확인 필요 | premium-price matching resolved; trigger tuning and cost gates remain |
| G06 stop/target/trailing/time exit | 사용자 확인 필요 | DTE4/±5 specified; no other exit policy was authorized |
| G07 session/expiry/rollover | 사용자 확인 필요 | monthly gap resolved; DTE definition/cutoff remain U22 |
| G08 capital/premium/max-loss/account risk | 설정값으로 이관 | editable settings exist in draft; all critical numbers are null/provisional |
| G09 failure/restart/recovery | 사용자 확인 필요 | policy draft exists, persistence/reconciliation evidence absent |
| G10 requirements-spec-code-test | 사용자 확인 필요 | exact test IDs/logs not run or mapped |
| G11 assumptions/external dependencies | 사용자 확인 필요 | U21–U29 and source/acceptance dependencies remain; U16–U20 resolved or settings |
| G12 validation vs approval | 확정으로 해결 | process boundary is explicit: draft/verification never implies user approval; this document remains unapproved |

### All interaction register items I01–I16, S1 classification
| I | Required classification | S1 reason; other-strategy issue remains where noted |
|---|---|---|
| I01 capital/premium/margin | 설정값으로 이관 | account/strategy caps are configurable; runtime enforcement and values not verified |
| I02 shared Futures identity | 확정으로 해결 | S1 has no Futures hedge in target intent; S3/S4/S5 global role issues remain |
| I03 option lots/Greeks ownership | 사용자 확인 필요 | S1 1:1 linked-short rule set, but authoritative lot ownership/duplicate aggregation evidence absent |
| I04 insurance overlap/tail risk | 설정값으로 이관 | account limits/stress exposure must aggregate; stress/correlation model still requires validation |
| I05 multi-leg partial/cancel race | 사용자 확인 필요 | state policy written; runtime test evidence absent |
| I06 P&L/fees attribution | 사용자 확인 필요 | authoritative ledger/multiplier/fee evidence absent |
| I07 expiry/session/rollover | 사용자 확인 필요 | DTE4 and monthly pause specified; calendar semantics/cutoff remain U22 |
| I08 risk/profit/hedge trigger priority | 사용자 확인 필요 | DTE4 suppresses new entry; other simultaneous priorities remain open |
| I09 data freshness/unavailable | 확정으로 해결 | user mandates fail-closed; actual enforcement still unverified |
| I10 restart/idempotency | 확정으로 해결 | user mandates reconcile before resume and no reset until flat; durable implementation still unverified |
| I11 Strategy 5 Futures role | 확정으로 해결 | S1 will not convert Futures quantities; S5 itself still requires No.1151 classification |
| I12 Strategy 3 spread identity | 사용자 확인 필요 | S3 issue is outside S1 and remains BLOCKED |
| I13 Strategy 4 hedge ownership | 확정으로 해결 | S1 uses only S1-owned linked short lots; S4 ownership issue remains separate |
| I14 Strategy 8 add-on intent | 확정으로 해결 | S1 does not modify S8 intent; S8 remains independently blocked |
| I15 daily/weekly/overnight re-entry | 사용자 확인 필요 | S1 monthly flat gate defined, account-wide cross-strategy cycle interaction remains unverified; S1 monthly pause is specified |
| I16 editable config consistency | 설정값으로 이관 | S1 version/hash schema specified; config values and runtime enforcement unverified |

These classifications do not change the status of any Decision Log entry. Any historical conflict is only a proposed “폐기됨” annotation; no Decision Log item was changed or deleted.

## Product boundary — No.1070
S1 base CALL/PUT, short options and hedge options use standard KOSPI200 options only. Mini Options are not used. This restriction is independent from replacing Mini Futures hedge with option hedge. All contract identity, exact YYYYMMDD expiry, strike and multiplier must be resolved from authoritative master data; otherwise new orders are blocked.

## Follow-up user-confirmed amendment — 2026-10-12 (authoritative over earlier draft rows)
- S1 short accumulation: ATM rises by short_step_pt → sell PUT at ATM minus short_offset_pt; ATM falls by short_step_pt → sell CALL at ATM plus short_offset_pt. Do not use the user's-unintended short-strategy label.
- DTE4: close every remaining S1 short, hedge, and base CALL/PUT; after confirmed flat, S1 remains idle about 3–4 days until next monthly cycle.
- new_short_stop_dte is removed; new_short_stop_dte=7 is retired (user confirmed 2026-10-12). No DTE7 entry stop is implied.
- Hedge trigger tuning candidates include 2.5pt and 5.0pt; neither is final. Sale-time premium means option premium price itself, not strike distance. Quote-gap fallback remains LIMIT reservation, 30 minutes, cancel-terminal/late-fill/position reconciliation before candidate descent.
- F01–F29 latest classification count: confirmed 15 / configurable 12 / user confirmation required 2. U16–U20 are resolved or settings as classified below; U21–U29 remain in the new unresolved register.
- U28: short step anchor refresh policy not specified and absent from current code; U29: separate take-profit/trailing policy not specified. Do not infer either.

- No.1046 evidence boundary: observed code facts and actual verification evidence remain separate; this document update is not runtime/test PASS.

- No.1131: no silent logic changes; target intent and code differences stay separate until explicit user approval. No.1132/1134: grouped plans are not atomic fills, leg-level execution is authoritative, and no reset/new cycle before all lots are confirmed flat.

## Integrated decision amendment — approved user intent, validation pending (2026-10-12)
- U-ID: preserve S1 U16–U29; namespace S5 delta items as S5-U16–S5-U20; preserve S9 U30–U37. Update cross-document references accordingly.
- S9 lifecycle: S1 exposure reaching zero does not itself close S9 insurance lots; S9 is independently held until per-lot stop/trailing or DTE7 rollover.
- S9 per-lot stop: current premium <= 0.50 x actual entry fill price closes that lot's remaining quantity.
- S9 per-lot trailing: arm when premium >= 2.00 x that lot's actual entry fill; track high-water and close on >=10% drawdown from peak.
- The 2.00x level arms trailing and is not an immediate fixed-target exit. DTE7 semantics/timing, fresh price source, lot-level state persistence, and execution ordering require validation. Draft/unapproved for implementation; no tests executed.

## Cross-strategy approved policy update — S9 DTE7 (2026-10-12)
- S9 DTE is trading-day based; rollover reference time is 11:00 KST.
- If next monthly expiry is not yet listed, monitor until listing; no substitute contract or order before listing and full preflight.
- Restore lot entry fills, residual qty, exact contract/expiry, trailing state and high-water mark after restart; reconcile against broker fills/positions and fail closed on mismatch/stale quotes.
- Same-lot simultaneous trigger order: trailing exit > stop-loss > DTE7 rollover. Reconcile fills/positions before subsequent action.
- This S9 policy does not alter other strategies' DTE rules; test evidence remains NOT_RUN.


## Integrated S9 verification blockers (2026-10-12; BLOCKED/NOT_RUN)
- Trading-day DTE7 must use the KRX official derivatives schedule and exact contract expiry/listing metadata; off-by-one/holiday vectors remain untested.
- Quote freshness threshold is deliberately UNSET until KIS option timestamp semantics and VTS evidence are reviewed; do not invent a numeric value.
- Restart restoration and broker execution/position reconciliation are acceptance gates, not assumed capabilities. Any missing state, stale quote, duplicate/late/partial fill or mismatch blocks new actions.
- Detailed evidence matrix: `05_strategy_9_dte7_quote_restart_validation_addendum_v0.1.md`.



---

## Strategy 6 v0.3 amendment — draft / unverified / unapproved (2026-10-13)

Version rule: this is a new v0.5 copied from v0.4. Earlier S6 rows remain historical context; this amendment is the current S6 draft where the two conflict. No Decision Log entries are deleted or rewritten and this does not authorize implementation.

### S6 F01–F29 intent update
The full S6 F01–F29 reclassification, state transitions, code-intent comparison and config schema are in strategy_6_daily_tail_insurance_spec_v0.3.md §§2–6. Main changes:
- Entry: session open through 11:00; max one entry/day; active/base IV ratio >= 1.3 using No.966's ATM CALL/PUT IV mean.
- Not an atomic pair order: rank-5/rank-6 candidates are considered sequentially, one live order at a time. Cancellation completion and late-fill reconciliation precede another candidate.
- If the first submitted order has no fill for 10 minutes, S6 entry ends for the day; no automatic retry of the other rank.
- CALL and PUT are one contract each. If the opposite leg times out, retain only the actual filled single leg; never label it a complete pair.
- Each leg's actual entry fill ×2 arms its own high-water tracking; a 10% drawdown from that leg's peak closes that leg. No S6 price stop before 2×.
- At 15:10 all actual residual S6 legs become close targets. The old 15:00 limit / 15:15 fallback is a code-intent mismatch.
- Exact expiry YYYYMMDD from authoritative Option Master; mini options prohibited. No reset before orders/fills/positions reconcile and all lots are flat.
- Null/unverified config/data fail closed. Record config version/hash per run and separate REAL_VTS tuning and validation windows.

### Interaction register I01–I16 (S6 scope)
| ID | S6 update for v0.5 | Status |
|---|---|---|
| I01 | CALL/PUT qty fixed at one each; common account premium, margin and max-loss reserve remains aggregate | intent fixed; enforcement BLOCKED |
| I02 | S6 has no futures hedge; keep futures-role questions for S1/S3/S4/S5 separate | S6 resolved |
| I03 | Link each S6 lot to owner/group/contract/fill/qty/mark and account attribution | integration evidence pending |
| I04 | Aggregate S6 daily with S7 weekly, S8 monthly/overlay and S9 insurance by premium, expiry and correlated stress | BLOCKED: correlation/payoff evidence |
| I05 | Sequential order, cancel completion before next, cancel-race reconciliation and single-leg state | intent fixed; runtime unverified |
| I06 | Per-leg actual option mark/fill replaces intrinsic/premium-spent proxy | intent fixed; marks/fees unverified |
| I07 | Same-day expiry, 11:00 entry window, 15:10 forced close, exact YYYYMMDD | policy specified; calendar/broker validation pending |
| I08 | 15:10 force-close precedes S6 trailing; account emergency override follows separately approved common risk policy | S6 policy specified; override evidence pending |
| I09 | Stale/mismatched IV/quote blocks entry; existing exposure remains in reconciliation/exit management | policy specified; age threshold unset |
| I10 | Restore pending orders, fills, positions, per-leg high-water and config hash before evaluation | required; persistence unverified |
| I11 | No S6 futures conversion; S5 role question unchanged | S6 N/A |
| I12 | S6 is not a futures spread | S6 N/A |
| I13 | S6 insurance lots are separate from S4 basecamp/delta inventory | ownership integration pending |
| I14 | S6 does not implement S8 PUT-only add-on behavior | S6 N/A |
| I15 | Max one entry/day; reconcile prior orders/fills/positions before next daily cycle/reset | policy specified; runtime unverified |
| I16 | Config version/hash covers 1.3, 11:00, rank order, timeout split, qty, 2×, 10%, 15:10, freshness/pricing | schema intent fixed; values/enforcement partly provisional |

### U01–U15 register update
| ID | Existing item | S6-specific classification |
|---|---|---|
| U01–U05 | S1–S5 items | unchanged |
| U06 | S6 pair MTM, partial pair recovery, daily cutoff | policy specified; validation BLOCKED pending marks/fills/cancel/calendar/runtime evidence |
| U07–U09 | S7–S9 items | unchanged |
| U10 | account capital and risk values | settings/verification pending; S6 fixed qty does not remove account gate |
| U11 | common order/partial/cancel/restart persistence | policy specified; runtime proof BLOCKED |
| U12 | account-wide aggregate exposure/correlation | validation pending for S6/S7/S8 margin/qty and S6/S7/S8/S9 correlated insurance |
| U13 | authoritative P&L/fee/multiplier | validation pending; actual per-leg marks/fills/fees required |
| U14 | exact expiry/session service | partly specified; YYYYMMDD, same-day expiry, 11:00/15:10 set; calendar/broker semantics pending |
| U15 | Shrimp Resume Context access/update | UNAVAILABLE unless an actual tool result proves inspection/update |

### G01–G12 S6 gate status
| Gate | Draft status | Evidence still required |
|---|---|---|
| G01 | intent defined | quantitative payoff/stress/cost validation |
| G02 | formulas/times defined; rank/time split/pricing remain settings | boundary and priority scenarios |
| G03 | qty and rank offsets defined | listed exact YYYYMMDD contracts and multiplier |
| G04 | partial/cancel lifecycle specified | actual order/fill/cancel evidence |
| G05 | no futures/additional hedge leg | prove resolver cannot add unintended legs |
| G06 | per-leg 2×/10%, 15:10 specified | actual marks/fills/close evidence |
| G07 | same-day expiry, 11:00 and 15:10 specified | official calendar/broker cutoff |
| G08 | fixed S6 qty; common account risk remains | settings/runtime enforcement |
| G09 | reconcile-before-reset specified | durable restart evidence |
| G10 | F01–F29 mapping drafted in traceability v0.3 | exact tests/evidence after approval |
| G11 | first_rank, timeout_split and quote/freshness explicit | REAL_VTS validation; no silent defaults |
| G12 | validation and approval separated | process rule only; draft remains unapproved |

State: document-only draft. No tests, code changes, stage/commit/push or Live orders.


### Explicit classification register for S6-related I/U/G (v0.5)

Classification semantics: “확정 해결” means the user-intent/policy definition is resolved, not that code or live trading is validated. “설정 이관” means keep the item as a versioned setting or evidence gate, without asking the user to decide it again in this task. “사용자 확인 필요” preserves another strategy's unresolved policy rather than letting S6 decide it.

#### I01–I16
| ID | Classification | S6 basis | Residual status |
|---|---|---|---|
| I01 | 설정 이관 | §1.5–1.6 | common account risk values/enforcement |
| I02 | 확정 해결 | §1.1, §1.6 | S6 has no futures hedge |
| I03 | 설정 이관 | §1.6 | lot ownership/account read-model evidence |
| I04 | 설정 이관 | §1.6 | S6/S7/S8/S9 correlation/stress model |
| I05 | 확정 해결 | §1.3–1.4, §1.6 | sequential per-leg lifecycle; runtime unverified |
| I06 | 확정 해결 | §1.5–1.6 | actual per-leg mark/fill required |
| I07 | 확정 해결 | §1.2, §1.5 | same-day, 11:00, 15:10; calendar proof pending |
| I08 | 확정 해결 | §1.5–1.6 | S6 force-close before S6 trailing |
| I09 | 확정 해결 | §1.2, §1.6 | fail-closed policy; age threshold settings remain |
| I10 | 확정 해결 | §1.6 | reconcile/restore before evaluation |
| I11 | 확정 해결 | §1.1 | S6 no futures conversion; S5 stays separate |
| I12 | 확정 해결 | §1.1 | S6 is not a futures spread |
| I13 | 설정 이관 | §1.6 | separate S6 lot ownership from S4 inventory |
| I14 | 확정 해결 | §1.1, §1.3 | no S6 PUT-only add-on |
| I15 | 확정 해결 | §1.2, §1.4, §1.6 | daily cap and reconcile-before-reset |
| I16 | 설정 이관 | §1.2–1.6 | config version/hash and provisional values |

#### U01–U15
| ID | Classification | Treatment |
|---|---|---|
| U01 | 사용자 확인 필요 | S1-only; unchanged |
| U02 | 사용자 확인 필요 | S2-only; unchanged |
| U03 | 사용자 확인 필요 | S3-only; unchanged |
| U04 | 사용자 확인 필요 | S4-only; unchanged |
| U05 | 사용자 확인 필요 | S5-only; No.1151 and retired No.1168 preserved |
| U06 | 확정 해결 | S6 policy defined; runtime/data validation still BLOCKED |
| U07 | 사용자 확인 필요 | S7-only; unchanged |
| U08 | 사용자 확인 필요 | S8-only; unchanged |
| U09 | 사용자 확인 필요 | S9-only; unchanged |
| U10 | 설정 이관 | common account risk values/enforcement |
| U11 | 확정 해결 | common lifecycle policy defined; runtime evidence pending |
| U12 | 설정 이관 | aggregate exposure/correlation/netting |
| U13 | 설정 이관 | authoritative marks/fills/fees/multiplier |
| U14 | 설정 이관 | expiry/session policy defined; common calendar/broker evidence |
| U15 | 사용자 확인 필요 | Shrimp access is unavailable; no update claim |

#### G01–G12
| Gate | Classification | S6 basis | Residual status |
|---|---|---|---|
| G01 | 설정 이관 | §1.1 | payoff/stress/cost validation |
| G02 | 설정 이관 | §1.2–1.5 | rank/time split/pricing boundaries |
| G03 | 설정 이관 | §1.3, §1.5 | exact listed contracts/multiplier |
| G04 | 확정 해결 | §1.4, §1.6 | policy defined; runtime test pending |
| G05 | 확정 해결 | §1.1 | no futures/additional leg |
| G06 | 확정 해결 | §1.5 | exit policy defined; mark/close evidence pending |
| G07 | 설정 이관 | §1.2, §1.5 | official calendar/broker boundary |
| G08 | 설정 이관 | §1.6 | account risk config/runtime enforcement |
| G09 | 확정 해결 | §1.6 | recovery policy defined; persistence evidence pending |
| G10 | 설정 이관 | §1.6 | exact test/evidence IDs not run |
| G11 | 설정 이관 | §1.2–1.6 | provisional config/data gates |
| G12 | 확정 해결 | §1.6 | approval remains separate; v0.3 unapproved |


## Strategy 7 v0.3 amendment — 2026-10-13
This appendix updates only S7-related classifications; prior IDs and versions remain intact. “Resolved” means intent is defined, not code/test PASS.

### I01–I16
| ID | Classification | S7 impact |
|---|---|---|
| I01 | 설정 이관 | Account capital/premium/max-loss/margin and atomic reserve across two S7 expiry groups plus S6/S8/S9 |
| I02 | 확정 해결 | No S7 futures hedge |
| I03 | 설정 이관 | Per-group/leg ownership and actual fill/position provenance |
| I04 | 설정 이관 | Monday/Thursday group and correlated insurance payoff aggregation |
| I05 | 확정 해결 | Sequential per-leg/cancel-race policy defined; runtime evidence pending |
| I06 | 확정 해결 | Actual fill/mark per leg defined; ledger evidence pending |
| I07 | 확정 해결 | Own expiry/15:10 intent defined; calendar/broker proof pending |
| I08 | 확정 해결 | Expiry > stop > trailing |
| I09 | 확정 해결 | Stale/unavailable fail-closed; thresholds remain config |
| I10 | 확정 해결 | No reset until flat; two-group restore unverified |
| I11 | 확정 해결 | No S7 futures conversion |
| I12 | 확정 해결 | S7 is not a futures spread |
| I13 | 설정 이관 | Separate S7 lots from S4/S1 holdings |
| I14 | 확정 해결 | No S7 PUT-only add-on |
| I15 | 확정 해결 | Independent Monday/Thursday lifecycle |
| I16 | 설정 이관 | Config hash, first_rank, timeout_split, volatility source, pricing/risk caps |

### U01–U15 carry-forward
| ID | Classification | S7 treatment |
|---|---|---|
| U01 | 사용자 확인 필요 | S1-only, unchanged |
| U02 | 사용자 확인 필요 | S2-only, unchanged |
| U03 | 사용자 확인 필요 | S3-only, unchanged |
| U04 | 사용자 확인 필요 | S4-only, unchanged |
| U05 | 사용자 확인 필요 | S5-only; No.1151/retired No.1168 untouched |
| U06 | 확정 해결 | S6 intent defined; runtime evidence pending |
| U07 | 사용자 확인 필요 | Historical ID retained; new S7 ambiguity uses S7-U16+ |
| U08 | 사용자 확인 필요 | S8-only, unchanged |
| U09 | 사용자 확인 필요 | S9-only, unchanged |
| U10 | 설정 이관 | Shared account risk enforcement |
| U11 | 확정 해결 | Common partial/cancel/restart/flat policy defined |
| U12 | 설정 이관 | Aggregate exposure/correlation/netting |
| U13 | 설정 이관 | Authoritative marks/fills/multiplier/fees |
| U14 | 설정 이관 | Expiry/session intent; source proof pending |
| U15 | 사용자 확인 필요 | Shrimp status not verified |

### New S7-U16–U20
| ID | Classification | Treatment |
|---|---|---|
| S7-U16 | 사용자 확인 필요 | Opposite leg timeout after first fill: retry to 15:00 vs retain one-sided lot |
| S7-U17 | 사용자 확인 필요 | An order's 10-minute timeout crosses 15:00: cutoff cancel vs natural timeout |
| S7-U18 | 설정 이관 | Base/active volatility formula, source, window and freshness |
| S7-U19 | 설정 이관 | Account risk aggregation across both S7 groups and S1/S6/S8/S9 |
| S7-U20 | 사용자 확인 필요 | Rename impact/alias; no change without separate approval |

### G01–G12
| Gate | Classification | Evidence needed |
|---|---|---|
| G01 | 설정 이관 | Payoff/stress/cost validation |
| G02 | 설정 이관 | Ratio/timeout/rank/cutoff boundaries, U16/U17 |
| G03 | 설정 이관 | Option Master expiry/strike/product/multiplier |
| G04 | 확정 해결 | Policy defined; tests not run |
| G05 | 확정 해결 | No S7 futures/extra leg |
| G06 | 확정 해결 | Stop/trailing/expiry intent defined; marks/fills unverified |
| G07 | 설정 이관 | Holiday calendar/broker cutoff |
| G08 | 설정 이관 | Account risk config/runtime enforcement |
| G09 | 확정 해결 | Reconcile-before-resume; recovery untested |
| G10 | 설정 이관 | Traceability added; tests NOT_RUN |
| G11 | 확정 해결 | S7-U16–U20 and assumptions listed |
| G12 | 확정 해결 | Draft status separate from approval |

## Strategy 8 v0.3 delta (2026-10-13; draft/unverified/unapproved)
- S8 monthly CALL+PUT, 1 contract per leg; S1 broad strangle remains separate and may coexist.
- Sequential single-leg limit orders only; rank 5/6, 10-minute timeout, confirmed cancellation and cancel-race reconciliation.
- Entry volatility ratio >=1.3; entry window 3 days after monthly start. Daily 15:00 cutoff is an assumption requiring confirmation.
- Per leg: stop at 50% actual entry fill; after mark reaches 2x entry, close on 10% drawdown from high-water. Monthly expiry day 15:10 force close.
- Remove macro PUT scaling/add-on and 1.5 multiplier truncation. Old DTE>=15 and budget>=200,000 gates unresolved.
- Open items: first rank, timeout_split/one-leg policy, volatility base source/window/freshness, budget/capital/premium/margin, aggregate account risk.
- Interactions: S1/S8 distinct lots; S6/S7/S8 aggregate quantities/premium/margin/stress; order/fill/cancel/restart reconciliation; exact YYYYMMDD expiry; config version/hash.

## S8 interaction/unresolved crosswalk v0.3 (draft; no strategy approval implied)

The I/U IDs below are inherited shared register identifiers from the latest integrated matrix. They are cross-referenced, not globally redefined. Older strategy-specific rows with repeated I/U IDs remain historical; this section records only the S8-v0.3 impact.

| ID | S8-v0.3 impact | Disposition |
|---|---|---|
| I01 | S8 fixed 1+1 qty does not waive account capital/premium/max-loss/margin reserve; null gate blocks | BLOCKED pending numeric settings/enforcement |
| I04 | S1/S8 pairs may coexist; S6/S7/S8/S9 exposure aggregated by expiry, premium, margin, correlated stress; no assumed netting | BLOCKED pending risk model |
| I05 | S8 sequential single-leg orders, cancel-confirm and cancel-race/partial-fill reconciliation | Policy specified; runtime proof pending |
| I06 | Per-leg actual fill/mark/multiplier/fees; no intrinsic/moneyness proxy for option P&L | Runtime ledger/mark proof pending |
| I07 | Exact YYYYMMDD expiry and monthly expiry-day 15:10 close; daily 15:00 entry cutoff remains assumption | Calendar/broker semantics pending |
| I08 | Expiry/stop/trailing exit suppresses new entry; deterministic account emergency override requires common policy | Specified in draft; runtime proof pending |
| I09 | Missing/stale/mismatched mark, expiry or volatility base blocks entry/action | Policy specified; freshness thresholds/enforcement pending |
| I10 | Restart must reconcile orders/fills/positions/config/watermark before evaluation or reset | Runtime persistence proof pending |
| I14 | Remove old S8 macro PUT-only add-on; resolver must not turn a single-leg intent into full pair | Intent resolved; code mismatch remains |
| I15 | New monthly cycle cannot duplicate existing S8/S1 lots; previous order/position state must reconcile | Runtime proof pending |
| I16 | Versioned config/hash; fixed qty and new exit rules; null/unverified risk/volatility settings block | Config schema provisional; enforcement pending |
| U08 | S8 add-on/PUT rounding/DTE behavior superseded by v0.3 intent: remove macro add-on, fixed qty, expiry 15:10; DTE gate remains open | Partially resolved; DTE question open |
| U10 | Account capital/premium/max-loss/margin values and gate semantics | OPEN; user confirmation required |
| U11 | Common partial/cancel/restart persistence | Policy specified; runtime proof pending |
| U12 | Account-wide aggregate exposure/correlation/netting | OPEN; risk config/model pending |
| U13 | Authoritative P&L/fee/multiplier source; per-leg actual fill/mark | Runtime evidence pending |
| U14 | Exact expiry/session service; monthly expiry-day 15:10; 3-day counting and 15:00 assumption remain open | Partially resolved; calendar proof pending |
| U15 | Shrimp Resume Context access/update | This task did not inspect/update Shrimp; no completion claim |


## Strategy 2 v0.3 user-intent amendment — 2026-10-13 (draft; NOT_RUN)

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

## Strategy 3 v0.3 amendment — draft only (2026-10-13)

Status: draft / unverified / unapproved; no code, tests, commit/push or Live orders. Source v0.8 preserved. S3 target spread is provisionally `near-month KOSPI200 Futures − far-month KOSPI200 Futures`, with two distinct authoritative contract identities. `spread_history` must be constructed from synchronized near/far futures observations; analytics only consumes the supplied history and does not establish its instruments.

| Decision area | v0.3 proposal | Classification / gate |
|---|---|---|
| F01 thesis | Near/far calendar-spread mean reversion | Proposed; REAL_VTS validation required |
| F02/F08 identity | Distinct expiries/identities, same underlying/product family; authoritative multiplier | Same-identity opposite legs blocked |
| F03/F20 schedule | Intraday only, proposed force close 15:10, no overnight; max-hold and DTE null | Config null blocks; verify official calendar |
| F04/F09 spread history | synchronized `near - far`; validated units, timestamp freshness, no stale/duplicate data | BLOCKED without both quotes/history |
| F05/F10/F11 signal | z-entry 2.0, exit 0.2, stop 3.5; regime-specific rules provisional | unapproved/config-only |
| F06/F07/F15 lifecycle | persist group; per-leg ACK/partial/fill/cancel/reject/late-fill and restart reconciliation | BLOCKED until evidence |
| F12/F18/F26/F28 risk | capital gate null, size-up false, cost/multiplier/stress/account exposure mandatory | entry disabled |
| F13/F14 pricing/preflight | per-leg tick/quote freshness/spread width/limit and group economic integrity | BLOCKED if any unknown |
| F16 roles | near/far are alpha spread legs, not an equal-quantity same-identity hedge | adapter mismatch to resolve |
| F17/F21/F24/F25 positions | actual lots and per-leg identities/fills determine close quantity and recovery | authoritative read model required |
| F19/F22 P&L | Futures spread P&L from actual fills, marks, multiplier, fees/slippage; no option premium proxy | mismatch with legacy trailing |
| F23 trigger priority | cutoff/risk-stop/stop/convergence/timeout priority explicit; pending branch must not use uninitialized regime | code issue documented, not fixed |
| F27 data | missing quote/cost/multiplier/P&L = UNAVAILABLE/BLOCKED | fail-closed |
| F29 acceptance | map every requirement to executable test + evidence | NOT_RUN |

### No.956 conflict proposal (do not mutate Decision Log)
No.956 defines Futures−Index basis. This v0.3 proposal is Futures near−far calendar spread and must not silently overwrite the old definition. Preserve No.956; only propose a later status change to `폐기됨` or scope-narrowing after explicit user approval. No.956 was not deleted or edited.

### Existing cross-strategy interaction register — S3 disposition

This table maps only IDs actually present in the prior integrated matrix; IDs are not renumbered or redefined here.

| Existing ID | Existing interaction scope | Strategy 3 v0.3 disposition | Status |
|---|---|---|---|
| I02 | Shared Futures identity / duplicate or cancelling Futures legs across S3/S4/S5/S1 | Calendar spread must use distinct near/far contract identities; same-identity opposite-side legs are not a spread. S4/S5 role questions remain separate. | BLOCKED pending adapter/master evidence |
| I05 | Multi-leg partial fill and cancel race | Track each calendar leg independently; cancel request is not terminal; reconcile late fills and actual residual positions. | BLOCKED / NOT_RUN |
| I06 | Strategy/account P&L attribution | S3 P&L must be Futures spread-specific, with actual fills, multiplier, fees/slippage and verified marks; no option premium proxy. | BLOCKED |
| I12 | Strategy 3 spread identity and role | v0.3 proposes near-month Futures minus far-month Futures; preserve No.956 unchanged and propose only a later status change after separate approval. | USER APPROVAL NEEDED for No.956 disposition |

### Existing open-register items and v0.2 S3 unresolved register

| Existing ID | Existing meaning | v0.3 classification |
|---|---|---|
| U03 | Strategy 3 tradable spread instruments and leg identities | Proposed near/far calendar spread; actual identity, expiry, multiplier, quote coverage and spread units still require validation. BLOCKED. |
| U12 | Account-wide aggregate exposure/correlation/netting policy | Applies to S3/S4/S5 and all strategies; account risk config/model remains open. BLOCKED. |
| D01 | v0.2 spread instruments/legs | Proposed calendar spread; validate master/quotes/roll mapping. |
| D02 | v0.2 hedge leg role/ratio | Near/far are spread legs; multiplier-adjusted ratio unresolved. |
| D03 | v0.2 z/std windows and units | Config/REAL_VTS validation required. |
| D04 | v0.2 regime/size-up/min-profit | Provisional; size-up remains false. |
| D05 | v0.2 trailing/max-loss P&L basis | Futures-only strategy P&L and account risk source required. |
| D06 | v0.2 timeout/cutoff/expiry | 15:10 proposed; max hold/DTE remain null. |
| D07 | v0.2 partial fills/group recovery | Per-leg reconciliation/restart evidence required. |
| D08 | v0.2 capital/strategy risk values | capital_gate_min null; explicit user confirmation required. |
| D09 | v0.2 missing-value semantics | Missing authoritative quote/cost/multiplier/P&L is BLOCKED/UNAVAILABLE, never assumed zero. |
| D10 | v0.2 cooldown/group identity persistence | Persist exit z, cooldown, group/order/execution IDs and config hash. |
All U items are open unless this table says the classification is a governance rule; no U item is claimed technically resolved. S3 remains disabled.

## Strategy 4 v0.3 disposition — draft / not approved

- S4 is disabled (`enabled=false`) pending capital/margin proof and explicit user approval. It must not reserve deployable capital for new S4 entry while disabled; any actual pre-existing S4 position/order still belongs in account-wide exposure and reconciliation.
- Proposed market-standard role: long-gamma options with Futures delta rehedging. Hedge only confirmed S4-owned option lots; account risk aggregation remains cross-strategy.
- S4 F01–F29 classification and I01–I16 disposition are detailed in `strategy_4_gamma_scalping_spec_v0.3.md` §4–6. This is a draft proposal, not a Decision Log approval.
- I01: budget allocator must distinguish disabled strategy budget from actual account exposure; no S4 budget reservation for new entries while disabled; activation requires approved capital gate and atomic reserve.
- I02/I03: actual/pending Futures lots and option lot ownership must be preserved to prevent offset/double hedge.
- I05/I06/I07/I08/I09/I10: grouped leg-level execution, S4-attributed P&L, no-overnight/15:10 candidate, deterministic trigger priority, fail-closed data and restart reconciliation are required but runtime coverage is not verified.
- I13: basecamp NON_EXECUTION is not an option fill; no hedge until option position is authoritatively confirmed.
- I16: versioned config/hash; null mandatory settings and disabled/capital gate block entry.
