# Strategy 7 — Weekly Volatility Skew Insurance 신규 상세 명세 v0.1
- 상태: **초안 / 미승인 / 구현 기준 사용 금지**
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98
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