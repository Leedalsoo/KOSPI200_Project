# Strategy 9 — Event Overnight Insurance 신규 상세 명세 v0.1
- 상태: **초안 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
- 현 코드: core/strategy/track9_event_overnight_insurance.py v3.0
- 연결: Track9 ATM IV/Option Master sources, AnalyticsSnapshot, resolve_track9, build_pair_plan, MultiLegBridge.

## 1. 목적 — 미확정
현 코드는 장 마감 전 PUT+CALL 보험을 매수해 다음 거래일 시초 급변을 보호하는 overnight strangle을 의도한다. 코드는 외부 macro/event/IV indicators를 entry trigger로 쓰지 않는다고 명시한다. Overnight risk budget, opening reference and payout acceptance criteria remain unresolved.

## 2. 현재 코드 사실 — 신규 요구사항이 아님
- Entry time=15:10; opening window end=MarketSessionPolicy.STABILIZATION_END; opening shock threshold=1%; trailing profit giveback=30%; pair qty default=1.
- Entry requires time>=15:10, entered_today false, valid positive underlying price, ATM PUT/CALL strikes and multiplier. It does not visibly reject times after official close.
- State becomes OVERNIGHT_INSURANCE_AWAITING_FILLS before actual pair fills. Entry proposal PUT BUY; resolver builds PUT+CALL pair.
- Filled leg prices are synced from same-day VSSF fill metrics. Entry premium=(put fill+call fill)*qty*multiplier. If either fill metric missing, state remains awaiting fills; no explicit one-sided-exposure timeout manager exists here.
- Next session: if abs(opening move)<1%, close pair; if shock>=1% and pair current profit>0, activate trailing. Peak profit trails with 30% giveback. If no shock/no trailing, close. At window end without trailing, close.
- Marks calculate pair value; close plan uses authoritative open lots. Callback resets only after group_complete and position_flat.
- State lacks exact option expiry identity.

## 3. 목표 lifecycle
WAITING_ENTRY → ENTRY_WINDOW_OPEN → CONTRACT/QUOTE/RISK_PREFLIGHT → PAIR_ENTRY_PLANNED → ENTRY_WORKING → PARTIAL/ENTRY_FILLED_AND_RECONCILED → OVERNIGHT_HOLD → NEXT_SESSION_OPENING_WINDOW → NO_SHOCK_EXIT or SHOCK_PROFIT_TRAILING or WINDOW_TIMEOUT_EXIT → EXIT_PENDING → FLAT_CONFIRMED → CLOSED.

No shock is not proof both legs filled. Partial/unknown entry requires an approved recovery policy and blocks duplicate entries. Unknown overnight exposure must not be silently carried or reset.

## 4. 필수 데이터
Official session close and next trading calendar; exact ATM strikes/expiry/contract IDs/multiplier; actual per-leg fill price/qty/fees; next-session opening price and pair marks with timestamps; authoritative open lots; order/fill/cancel state across restart.

## 5. 미결정 항목
1. latest allowed entry time and after-close data behavior.
2. ATM definition, strike selection and expiry.
3. max premium/max overnight loss/account risk.
4. pair fill deadline and one-leg fill response.
5. opening reference and shock denominator.
6. opening stabilization window and holiday/timezone.
7. trailing mark source and fees.
8. shock but nonpositive pair profit; stale marks; no opening data.
9. terminal exit if quote unavailable.
10. expiry/restart/missed session/residual lots.
11. whether IV/event history sources remain informational only.

## 6. 검증 시나리오
15:09:59/15:10/official close/after close; missing strike/multiplier/quote; one-leg/partial fills; weekend/holiday; opening move below/equal/above 1%; pair profit negative/zero/positive; 30% giveback; exact window end; exit partial/reject/cancel-race; restart during overnight hold; no next-session data; account premium budget.

## 7. 추적/판정
관련 코드: track9_event_overnight_insurance.py, Track9 ATM IV/Option Master sources, resolve_track9, build_pair_plan, MultiLegBridge/PositionLotStore.
**BLOCKED** — after-close entry gate, partial entry recovery and max overnight risk unresolved.