# Strategy 5 — Gap Divergence 신규 상세 명세 v0.1
- 상태: **초안 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
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