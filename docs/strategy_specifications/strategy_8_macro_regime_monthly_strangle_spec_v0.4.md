# Strategy 8 — Macro Regime Monthly Strangle 명세 v0.3
- 작성일: 2026-10-13
- 상태: 초안 / 미검증 / 미승인. 구현 기준으로 사용할 수 없음.
- 기준: Project200 / HEAD 7eb9945e29774fb61fd2d07801762871b2506b98
- 범위: 문서 전용. v0.2 보존. 코드·테스트·commit/push·KIS Live 금지.
- 우선순위: 현재 사용자 지시 > 최신 유효 확정 Decision Log > AGENTS.md. 과거 문서/코드/테스트는 역사적 증거일 뿐 승인 근거가 아니다.
- 참고: No.1151, No.1131, No.1132/1134, No.1119, No.1070, No.1046.

## 1. 사용자 확정 의도

S8은 월물 CALL+PUT 양매수 보험 포지션이다. 매크로 국면에 따른 PUT 수량 확대 및 별도 add-on은 제거한다. S1의 넓은 양매수와 S8은 별도 포지션이며 둘 다 보유 가능하다. 같은 계약이어도 strategy/group/leg/lot, 실제 체결원가와 청산 책임을 분리한다.

### 1.1 S6/S7/S8 공통 규칙
1. 두 레그 동시 제출의 all-or-none 주문이 아니다. 콜·풋 각각 ATM 대비 5번째 또는 6번째 넓은 행사가를 선택한다. 2.5pt 간격이 Option Master로 확인될 때만 rank 5=±12.5pt, rank 6=±15pt로 해석한다. 확인 실패 시 진입 차단.
2. 한 번에 단일 옵션 주문 하나만 제출한다. 후보 rank 5/6 중 첫 주문 미체결 10분 후 취소 요청하고, 취소 완료 및 취소 중 체결 여부를 authoritative order/execution 상태로 확인한 뒤에만 다음 후보 제출. 첫 후보 체결 또는 취소 중 체결이면 대체 후보 금지.
3. 첫 leg 체결 후 반대 leg를 별도 주문한다. 반대 leg 주문은 10분 관리한다. 반대 leg 실제 체결 확인 전에는 양매수 완성으로 간주하지 않는다.
4. CALL=1계약, PUT=1계약 고정. macro regime에 따른 수량 확대, 1.5배 및 int 절사 폐기.
5. 각 leg의 손절은 실제 체결 매수가 대비 50% 하락이다. 실제 옵션 mark가 해당 leg의 실제 진입가 2배에 도달한 후 high-water를 추적하고, high-water 대비 10% 하락 시 그 leg를 청산한다.
6. 월물 만기 당일 15:10에 S8의 잔여 포지션 강제 청산. 15:00/15:15 pending cancel event와 15:10 종료의 충돌은 취소/체결 대사로 처리한다. 15:10 이후 잔여 포지션이 있으면 성공이 아니라 RECONCILIATION_REQUIRED/BLOCKED.
7. 진입은 active volatility / base volatility ≥1.3일 때만. volatility source/base window/freshness 미확인 시 fail-closed.
8. 모든 수치/시간/rank/수량은 versioned config. REAL_VTS 튜닝·검증 기간 분리, 실행별 config version/hash 기록. 미검증 설정은 승인된 운영 기준이 아니다.

### 1.2 S8 월물 규칙
- 월물 시작/정확한 만기는 authoritative Option Master/calendar로 조회. 하드코딩·추정 금지. 만기 identity는 YYYYMMDD로 보존(No.1119).
- entry_attempt_days=3. 가정(확인 필요): 거래 가능 영업일 3일이며 각 날짜 15:00까지 진입 시도. 휴장/단축장 처리도 확인 필요.
- 기존 DTE≥15 게이트는 코드 관찰 사실일 뿐 현재 확정 의도가 아니다. 유지/폐기는 사용자 확인 필요.
- 기존 예산 200,000 게이트도 미확정. 계좌자본/프리미엄/증거금 중 무엇인지 정의 없이 임의 유지·삭제 금지. 게이트가 필요한데 값이 미확정이면 진입 BLOCKED.
- S1과 S8은 서로 대체·상계하지 않는다. 같은 계약도 별도 lot/entry fill/remaining qty/config provenance/exit owner로 보존한다.

## 2. F01–F29 분류표
분류: 확정=사용자 의도; 설정/검증=REAL_VTS 후 승인 필요; 사용자 확인=임의 결정 금지.
| ID | 항목 | 목표/판정 | 분류 |
|---|---|---|---|
| F01 | 목적 | 월물 CALL+PUT 보험, macro PUT add-on 제거 | 확정 §1 |
| F02 | 상품 | 일반 KOSPI200 옵션, exact expiry/strike/type/multiplier/symbol, 미니옵션 금지 | 확정, No.1070/1119 |
| F03 | 생명주기 | Option Master/calendar 월물 시작·만기, 시작 후 3일, 만기 15:10 청산 | 3일 계산 확인 필요 |
| F04 | 데이터 | underlying, active/base vol, quote/mark, master, freshness, risk snapshot | 검증값 |
| F05 | 진입 | active/base volatility ≥1.3 | 설정/검증 |
| F06 | 진입 창 | 시작 후 3일; 일별 15:00은 가정; 중복 진입 금지 | cutoff 확인 필요 |
| F07 | 주문 | 단일 leg limit, rank 5/6 순차, timeout 10분, 취소 확인 | 의도 확정; 검증 필요 |
| F08 | identity | exact YYYYMMDD/type/strike/multiplier/symbol | 원칙 확정 |
| F09 | rank/tick | rank 5/6, 2.5pt 간격은 master 확인 시만 | first_rank 미정 |
| F10 | regime/qty | PUT scale과 1.5배 절사 제거, CALL=PUT=1 | 확정 |
| F11 | mark | actual option mark for trailing; actual fill for cost; moneyness proxy 금지 | 원칙 확정 |
| F12 | capital | 각 leg 1계약; budget/capital/premium/margin gate 미정 | 확인 필요 |
| F13 | limit | single-leg limit; price/tick/reprice/max premium 정책 검증 필요 | 설정/검증 |
| F14 | resolver | BUY를 무조건 full pair로 변환 금지; leg intent 보존 | 코드 불일치 |
| F15 | partial/cancel | leg별 상태 기록; fill 확인 후 active | 공통 안전 원칙 |
| F16 | overlay | macro PUT add-on 제거 | 확정 |
| F17 | lot | fill price, remaining qty, watermark, expiry, config hash 및 provenance 저장 | 공통 원칙 |
| F18 | stop | 각 leg actual fill 대비 50% 손절 | 규칙 확정; 검증 필요 |
| F19 | trailing | 각 leg 2× entry activate, high-water 대비 10% 하락 청산 | 규칙 확정; 검증 필요 |
| F20 | expiry | 만기일 15:10 청산; DTE≤4 HOLD와 코드 충돌 | 의도 확정 |
| F21 | close | S8 잔여 qty만 청산; S1 lots 독립; flat 전 reset 금지 | 공통 원칙 |
| F22 | P&L | actual fills/marks/multiplier/fees; premium_spent=0을 실제 원가로 취급 금지 | 원칙 확정 |
| F23 | priority | expiry/stop/trailing exit 우선, exit/reconcile 중 진입 금지 | 세부 검증 필요 |
| F24 | provenance | strategy/group/leg/order/execution/lot 및 config version/hash | 원칙 확정 |
| F25 | recovery | restart 후 주문/체결/포지션/expiry/cost/watermark 대사, flat 전 reset 금지 | 원칙 확정 |
| F26 | 계좌위험 | S1/S8 별도 공존; S6/S7/S8 quantity/premium/margin/stress 합산 | enforcement 미입증 |
| F27 | 데이터 오류 | stale/missing/unknown/mismatched/base vol/risk -> BLOCKED | 확정 fail-closed |
| F28 | 설정 | versioned config/hash; null/unverified blocks | 원칙 확정 |
| F29 | 승인검증 | REAL_VTS tuning/validation 분리; 문서 갱신은 테스트 PASS 아님 | 절차 확정 |

## 3. PROVISIONAL 설정 스키마
    strategy8:
      status: PROVISIONAL
      vol_ratio_min: 1.3
      entry_attempt_days: 3
      entry_daily_end_time: "15:00" # 가정, 사용자 확인 필요
      strike_ranks: [5, 6]
      order_timeout_minutes: 10
      qty_call: 1
      qty_put: 1
      stop_loss_ratio: 0.5
      trailing_activate_multiple: 2.0
      trailing_drawdown: 0.10
      force_close_time: "15:10"
      first_rank: null
      timeout_split: null
      dte_entry_min: null
      budget_min: null
      volatility_base_source: null
      volatility_base_window: null
      max_quote_age_seconds: null
      limit_price_policy: null
      max_premium_per_leg: null
      account_risk_gate: null
null/PROVISIONAL/missing source, contract, or risk settings block new orders. Values remain unverified pending REAL_VTS and explicit approval.

## 4. 상태 전이
| 현재 상태 | 조건 | 처리 | 다음 상태/실패 |
|---|---|---|---|
| CONFIG_BLOCKED | null/unverified config/hash | 주문 금지 | BLOCKED |
| WAIT_MONTHLY_START | master/calendar로 월물 계약 미확인 | 선택/주문 금지 | UNAVAILABLE |
| ENTRY_WINDOW | 월물 시작 확인, 승인된 3일 창 내 | vol/risk/quote 검사 | VOL_CHECK |
| VOL_CHECK | ratio missing/stale/base undefined/<1.3 | 주문 금지 | WAIT/BLOCKED |
| VOL_CHECK | ratio≥1.3 및 모든 gate 통과 | rank 후보 선택 | ENTRY_ORDER_READY |
| ENTRY_ORDER_READY | 유효 단일-leg limit, qty 1 | 주문 하나 제출 | ENTRY_WORKING; ACK는 ACTIVE 아님 |
| ENTRY_WORKING | 10분 미체결 | 취소 요청 | CANCEL_PENDING |
| CANCEL_PENDING | 취소 확인, fill 없음 | 창 내 대체 rank 허용 | ENTRY_ORDER_READY |
| CANCEL_PENDING | fill/partial/cancel race | 대체 주문 금지, actual qty 대사 | LEG_PARTIAL/LEG_FILLED |
| LEG_FILLED | 첫 leg fill 확정 | 반대쪽 qty 1 별도 주문 | OPPOSITE_WORKING |
| OPPOSITE_WORKING | 10분 미체결 | 취소 요청 및 확인 | OPPOSITE_CANCEL_PENDING |
| OPPOSITE_CANCEL_PENDING | fill/partial/cancel race | 대사; 중복 대체 주문 금지 | LEG_PARTIAL/PAIR_COMPLETE if both fills |
| OPPOSITE_CANCEL_PENDING | 취소 확인, fill 없음 | timeout_split 정책 적용 | null이면 BLOCKED |
| both legs filled | 두 leg 체결/identity 대사 완료 | 독립 lot 및 cost basis 기록 | PAIR_COMPLETE |
| one leg filled | 반대 leg 미체결, 정책 미확정 | one-leg exposure 추적, pair-complete 금지 | ONE_LEG_EXPOSURE/BLOCKED |
| open leg | mark ≤ entry fill×0.5 | 해당 leg 잔여 qty 청산 | EXIT_WORKING |
| open leg | mark ≥ entry fill×2 | high-water 추적 시작 | TRAILING_ACTIVE |
| TRAILING_ACTIVE | mark > prior high-water | 비교 후 high-water 갱신 | TRAILING_ACTIVE |
| TRAILING_ACTIVE | mark ≤ high-water×0.9 | 해당 leg 잔여 qty 청산 | EXIT_WORKING |
| expiry day 15:10 | 주문/포지션 잔존 | pending entry 취소/대사 후 실제 잔여 qty 청산 | EXPIRY_EXIT_WORKING |
| exit partial/reject/pending | flat 아님 | 대사/승인된 복구; reset 금지 | EXIT_WORKING/RECONCILIATION_REQUIRED |
| all orders terminal + authoritative flat | broker position/execution 일치 | terminal state 기록 후 reset | FLAT |
| restart/reconnect | 내부/브로커 상태 불일치 | 신규 주문 금지, 대사 | RECONCILIATION_REQUIRED |

취소 요청은 취소 확인이 아니다. 취소 중 fill/partial fill이면 체결을 먼저 반영하고 남은 주문/포지션 수량을 다시 계산한다. Watermark는 이전 값을 먼저 비교한 뒤 갱신해야 하며, 갱신 순서 때문에 UPDATE_TRAILING 신호가 억제되지 않는 시나리오가 필요하다. exit/reconciliation 중 신규 진입 금지.

## 5. 코드-의도 차이표 (read-only)
| ID | 관찰된 코드 차이 | v0.3 의도/분류 |
|---|---|---|
| D01 | DTE_ENTRY=15, MIN_BUDGET=200000 gate | 유지/폐기 사용자 확인 필요 |
| D02 | HIGH_VOL PUT=2, normal PUT=1.5 및 int 절사 | PUT=1 고정, scale 폐기 |
| D03 | evaluate_entry가 fill 전에 is_active 설정 | 실제 fill/reconcile 후 active |
| D04 | CALL BUY proposal이 full CALL+PUT pair plan으로 변환될 수 있음 | 단일 leg intent 보존 |
| D05 | Track8OptionContractSource가 symmetric ±15 pair 기대 | rank 5/6 sequential |
| D06 | build_pair_plan이 CALL+PUT logical plan 생성 | broker 주문은 독립·순차 |
| D07 | premium_spent 초기값 0, 실제 fill 원가 미갱신 경로 | execution fill cost 기록 |
| D08 | state에 exact YYYYMMDD expiry 미보존 | expiry identity 저장 |
| D09 | moneyness/intrinsic proxy와 85% retain ratio | actual mark, 50% stop, 2×/10% trailing |
| D10 | watermark 갱신 후 비교해 UPDATE_TRAILING 억제 가능성 | 이전 watermark 비교 후 갱신; defect candidate |
| D11 | macro PUT add-on 계산 및 fill 전 macro_hedge_scaled 설정 | add-on 제거, state는 fill 기반 |
| D12 | DYNAMIC_PROFIT_TAKE / DYNAMIC_REBUILD_FENCE 의미가 미승인 | v0.3에서 제외 |
| D13 | 15:00–15:15 pending cancel 및 DTE≤4 HOLD_LONG_ATTACK | 만기일 15:10 force close |
| D14 | close resolver는 open lots 사용, reset은 group_complete+flat 조건 | S1/S8 lot 분리, 대사 후 reset |
| D15 | analytics에 active vol은 있으나 base_vol authoritative source 미입증 | ratio source/freshness 검증 |
| D16 | tests/strategy/test_strategy8.py의 주된 범위는 entry proposal/macro repeat | full lifecycle coverage 미입증; 테스트 미실행 |

Code paths reviewed: core/strategy/track8_macro_regime_monthly_strangle.py; application/composition/track8_option_contract_source.py; application/composition/automated_virtual_runtime_factory.py (resolve_track8); core/strategy/multi_leg_plan.py; core/analytics/track8.py; tests/strategy/test_strategy8.py. This is not an exhaustive runtime proof.

## 6. v0.2 U/G/I carry-forward disposition
- Confirmed principle: exact monthly expiry/calendar from Option Master and YYYYMMDD; remove PUT scaling; actual option mark for per-leg trailing; 50% stop; 2×/10% trailing; expiry-day 15:10 close; no reset before flat; S1/S8 separate lots.
- User confirmation required: DTE≥15 gate, budget 200,000 gate/meaning, first_rank, timeout_split and one-leg policy, 3-day definition/daily 15:00 cutoff, volatility base source/window/freshness, max premium/account max-loss/margin caps.
- Configuration/validation transfer: quote freshness, limit price/tick/reprice, multiplier/rank spacing, account risk aggregation, actual fill cost and watermark correctness, restart and cancel-race behavior.
- Retire from new S8 intent: macro PUT overlay/add-on, 1.5 multiplier and truncation, DYNAMIC_PROFIT_TAKE / DYNAMIC_REBUILD_FENCE unless separately approved, DTE≤4 HOLD_LONG_ATTACK.
- Gate register: Option Master/exact expiry; contract identity/strike/multiplier; quote/mark freshness; vol ratio source; sequential order/cancel/fill reconciliation; budget/DTE decision; per-leg mark/cost; 15:10 expiry exit; S1/S8 lot separation; S6/S7/S8 aggregate risk; restart/idempotency; REAL_VTS split and config provenance. Any required null/unverified gate blocks new orders.
- Interaction register: S1+S8 can coexist, same contract must be separate lots; S6/S7/S8 account risk aggregated; no full pair recreation from macro PUT signal; single-leg sequential execution; shared quotes require exact identity/time; expiry YYYYMMDD; config reload cannot silently alter open-lot exit policy; exit priority suppresses entry; REAL_VTS is not Live evidence.

### S8 unresolved questions (additional)
| ID | Question | Status |
|---|---|---|
| S8-U16 | Does 3 days mean 3 trading days, each with 15:00 cutoff? How handle holidays/short sessions? | OPEN |
| S8-U17 | Retain or remove DTE≥15 gate? | OPEN |
| S8-U18 | Retain/remove/replace budget 200,000; what does it measure? | OPEN |
| S8-U19 | Rank 5 or 6 first? | OPEN |
| S8-U20 | Opposite leg timeout: retry until window closes or retain one-leg exposure under separately approved rule? | OPEN |
| S8-U21 | Authoritative active/base volatility source/window/cadence/freshness? | OPEN |
| S8-U22 | Max premium per leg and strategy/account max-loss/margin gate? | OPEN |

## 7. REAL_VTS validation plan (not run)
Freeze candidate config/hash and tuning interval; select separate untouched validation interval. Verify source/receive timestamp semantics, freshness, exact expiry, multiplier, strike spacing/rank. Replay sequential order ACK, partial fill, timeout, cancel pending, fill during cancel, cancel confirmed, opposite fill/timeout, restart. Verify actual fill cost, 50% stop, 2× activation, high-water update, 10% drawdown and 15:10 close. Verify S1/S8 same-contract lots remain separate. Verify S1/S6/S7/S8/S9 aggregate premium/margin/correlated stress. Missing caps => BLOCKED. REAL_VTS is not Live evidence.

## 8. Scenario additions (planned only, not executed)
| Scenario ID | Type | Expected result | Status |
|---|---|---|---|
| TP-S8-V03-N01 | Normal | Valid master/window/vol=1.3/risk pass; one single-leg order | NOT_RUN |
| TP-S8-V03-B01 | Boundary | Vol ratio below/equal/above 1.3 | NOT_RUN |
| TP-S8-V03-B02 | Boundary | Rank 5 unavailable; rank 6 only after cancel confirmation | NOT_RUN |
| TP-S8-V03-B03 | Boundary | 10-minute timeout; cancel request alone cannot replace | NOT_RUN |
| TP-S8-V03-E01 | Exception | Fill during cancel blocks alternate rank and reconciles quantity | NOT_RUN |
| TP-S8-V03-E02 | Exception | Partial fill/cancel race records filled and remaining qty | NOT_RUN |
| TP-S8-V03-N02 | Normal | Opposite leg submitted separately; pair complete only after both fills | NOT_RUN |
| TP-S8-V03-E03 | Exception | Opposite leg timeout with timeout_split null | BLOCKED: user decision |
| TP-S8-V03-B04 | Boundary | Mark around 50% entry fill triggers per-leg stop | NOT_RUN |
| TP-S8-V03-B05 | Boundary | Mark reaches 2× fill and activates high-water tracking | NOT_RUN |
| TP-S8-V03-B06 | Boundary | Mark reaches 90% high-water and closes that leg remaining qty | NOT_RUN |
| TP-S8-V03-E04 | Exception | New high compared to prior watermark before update | NOT_RUN |
| TP-S8-V03-E05 | Exception | Missing/stale/wrong-contract mark blocks action | NOT_RUN |
| TP-S8-V03-B07 | Boundary | Expiry day 15:09:59/15:10:00/15:10:01 | NOT_RUN |
| TP-S8-V03-E06 | Exception | Pending cancel overlaps 15:10 close; reconcile race | NOT_RUN |
| TP-S8-V03-E07 | Recovery | Restart with working order/partial fill/open leg reconciles first | NOT_RUN |
| TP-S8-V03-X01 | Cross-strategy | Same contract S1/S8 retains separate lots/exit owners | NOT_RUN |
| TP-S8-V03-X02 | Cross-strategy | S6/S7/S8 risk aggregated; unset cap blocks | BLOCKED: risk config |
| TP-S8-V03-B08 | Boundary | DTE 15/14 and budget 200000/below while gates unresolved | BLOCKED: user decision |
| TP-S8-V03-R01 | Recovery | Config changes do not alter existing lot provenance | NOT_RUN |
| TP-S8-V03-E08 | Exception | Macro regime changes never scale PUT qty | NOT_RUN |

## 9. 사용자 확인 질문
1. entry_attempt_days=3은 거래일 3일이며 매일 15:00 마감인가? 휴장/단축장 처리는?
2. DTE≥15 gate 유지 또는 폐기?
3. budget 200,000 gate 유지/폐기/대체? 유지 시 계좌자본·프리미엄·증거금 중 무엇인가?
4. rank 5와 rank 6 중 무엇을 먼저 시도하는가?
5. 반대 leg timeout 후 재시도 또는 편매수 보유 중 어느 정책인가?
6. authoritative active/base volatility source/window/freshness는?
7. leg별 max premium 및 strategy/account max-loss/margin gate는?

### Appendix B. v0.2 D01-D10 source rows (historical; v0.2 has no U/G/I ID rows)

The v0.2 file contains the D01-D10 unresolved/discrepancy registry, but no rows with Uxx/Gxx/Ixx identifiers. Therefore no U/G/I rows can be copied verbatim; all S8-relevant open items and interactions are reclassified in Sections 6.1–6.3. The source D01-D10 items are summarized below (not a verbatim extraction; the source remains preserved in v0.2):




| D01 | Monthly expiry/contract selection | Option Master/calendar; lifecycle incomplete |
| D02 | Budget definition/200,000 threshold | Capital, premium, margin evidence; unapproved |
| D03 | Normal PUT 1.5 multiplier rounding | Existing int truncation not target |
| D04 | Macro add-on role/qty/resolver | Incremental plan mismatch; blocked |
| D05 | Actual pair MTM/trailing | Mark/fill/fees/multiplier not authoritative |
| D06 | DTE≤4 HOLD vs close | Old HOLD behavior conflicts with new 15:10 intent |
| D07 | Rebuild signal semantics | DYNAMIC_PROFIT_TAKE / REBUILD_FENCE unclear |
| D08 | Capital/premium/max-loss values | Separate user approval needed |
| D09 | Aggregate account risk | Cross-strategy enforcement unproven |
| D10 | Restart/partial fills/expiry state | Order/fill/position provenance incomplete |

---
## v0.4 사용자 규칙 갱신 — 진입 만기 게이트·재시도 창·예산 조건
상태: DRAFT / VERIFYING / UNAPPROVED. 이 절은 기존 DTE 15 및 KRW 200,000 예산 조건을 대체한다.
1. 진입은 계약의 정확한 만기까지 남은 거래일 수가 10 이상인 경우에만 허용한다. 달력일 수로 계산하지 않는다. 공식 KRX 거래일 달력과 해당 계약의 authoritative expiry를 사용해 검증한다. 달력/만기/상품 identity가 불명확하면 BLOCKED.
2. 기존 budget=200,000 KRW 진입 게이트는 폐기한다. 이 금액을 다른 변수로 재해석하거나 숨은 기본값으로 유지하지 않는다. 실제 주문은 별도 승인된 공통 계좌/전략 프리미엄·최대손실·증거금 한도와 authoritative quote/risk preflight를 통과해야 한다. 그 한도나 런타임 enforcement가 확인되지 않으면 BLOCKED; 예산 게이트 제거가 무제한 주문 허가를 뜻하지 않는다.
3. 재시도 기간은 달력 3일이 아니라 3개의 유효 KRX 거래일이다. 첫 유효 진입 시도일을 1일차로 세며, 3일차 15:00 KST를 최종 신규 시도 cutoff로 한다. 휴장일·주말은 세지 않는다.
4. 각 주문의 미체결 타이머는 10분이다. 타임아웃 후 즉시 잔여 수량을 중복 제출하지 말고 취소 확인, 취소 중 late/partial fill 대사, 실제 잔여 목표 수량 계산을 먼저 완료한다. 그 뒤 유효 quote와 위험 게이트가 통과되면 다음 허용 재시도를 수행한다.
5. 3거래일 창 종료 또는 3일차 15:00 KST 중 먼저 도달한 시점 이후에는 신규 진입 재시도를 중단한다. 열린 주문/부분체결/포지션은 별도의 청산·위험관리 상태로 관리하며, 재시도 기간 종료만으로 포지션이 flat이라고 간주하지 않는다.
6. 호가 freshness, 재호가 간격, 허용 슬리피지, 최대 재시도 횟수는 실제 KIS VTS 기록 및 공식 호가단위 규칙으로 검증할 때까지 미확정이다. 필요한 설정이 없으면 임의 가격 주문을 하지 않는다.
