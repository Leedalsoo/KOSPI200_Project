# Strategy 2 — Asymmetric Trap 상세 명세 v0.3

- 작성일: 2026-10-13
- 상태: **draft / unverified / unapproved** — 구현 기준 사용 금지
- 기준 브랜치/HEAD 조사값: `Project200` / `7eb9945e29774fb61fd2d07801762871b2506b98`
- v0.1/v0.2 보존. 문서만 작성하며 코드 수정·테스트·commit/push·KIS Live 주문 금지.
- 사용자 확정 의도 §1은 과거 코드/명세보다 우선한다. 코드는 관찰 사실이며 불일치는 수정 대상일 뿐 구현 승인으로 해석하지 않는다.

## 1. 사용자 확정 의도

### 1.1 구조·상품

Asymmetric Trap은 **안쪽 콜·풋 매수 + 바깥쪽 콜·풋 매도**의 네 레그다. 즉 매수 콜스프레드와 매수 풋스프레드를 합친 구조다.

- 안쪽 PUT BUY 1계약, CALL BUY 1계약
- 바깥쪽 PUT SELL 1계약, CALL SELL 1계약
- 일반 KOSPI200 옵션만 사용하고 Mini 옵션은 사용하지 않는다(No.1070).
- 추가 Futures hedge/overlay는 임의로 넣지 않는다.
- `ZERO_COST`라는 이름은 경제적 사실을 보장하지 않는다. 실제 bid/ask, fill, multiplier, fees, slippage로 순비용·payoff·max/stress loss를 계산한다.

### 1.2 변동성별 행사가

| 조건 | 구조 | 안쪽 매수 | 바깥쪽 매도 |
|---|---|---|---|
| `active_vol / base_vol <= low_vol_ratio` | 넓은 | PUT ATM−5.0pt / CALL ATM+5.0pt | PUT ATM−10.0pt / CALL ATM+10.0pt |
| 그 외 | 좁은 | PUT ATM−2.5pt / CALL ATM+2.5pt | PUT ATM−7.5pt / CALL ATM+7.5pt |

`low_vol_ratio=0.85`는 PROVISIONAL이다. `base_vol<=0`, 비율 산출 불가, stale/mismatched volatility 또는 authoritative listed strike/ATM identity 불가면 신규 진입을 차단한다. Listed-strike rounding, ATM 동률 및 미존재 strike 처리 규칙은 임의 추정하지 않는다(S2-U17).

### 1.3 진입 feature — 전부 유지

사용자는 기존 코드에서 확인된 조건 묶음을 모두 의도했다고 확정했다. 삭제·완화하지 않는다. 임계값은 설정 파일의 PROVISIONAL 값이며 검증 후 확정한다.

1. Bollinger Band Width (`bbw`) 조건
2. 거래량 Z-score `> 3.0`
3. `abs(OBI) > 0.5`
4. Futures basis `> 0.3` — 단위/부호를 source contract에서 확인
5. `abs(price - POC) > 1.0pt` 및 POC 위/아래 위치
6. IV 비교: POC 위면 `put_iv < call_iv`; POC 아래 또는 같으면 `call_iv < put_iv` (현재 코드 규칙을 문서화하고 검증)
7. active/base volatility ratio에 따른 wide/narrow 선택

각 feature는 산식, 단위, source, source/received timestamp, freshness, instrument/expiry identity, sample sufficiency와 missing/stale 처리를 기록한다. `bbw_condition: null` 또는 필요한 source/정의/설정이 null·PROVISIONAL·검증 불가이면 신규 거래를 차단한다. 경계값 포함 여부는 코드 관찰만으로 승인하지 않는다.

### 1.4 월물 lifecycle

- 현재 `target_expiry_series: [monthly]`만 활성. 일물·주물은 향후 확장·현재 미활성.
- 월물 시작 후 첫 3일 동안 진입 조건이 충족될 때만 진입한다. 일별 진입 마감은 15:00.
- 월물당 사실상 1사이클. 청산 후 같은 월물에서 재진입하지 않고 만기까지 대기한다. 다음 월물 시작 후 새 사이클을 평가한다.
- 월물 만기 당일 15:10에 무조건 청산 절차를 시작한다. 15:10은 제출/청산 시작 시각이지 모든 주문이 체결되었다는 보증이 아니다. 실제 모든 S2 lot가 flat으로 대사될 때까지 종료 상태/다음 진입을 허용하지 않는다.
- KRX official calendar, 월물 시작일 정의 및 broker cutoff 의미는 검증 의존성이다. 일물·주물 확대 시 S6/S7 시간 규칙을 참조할 수 있게 `target_expiry_series`로 일반화한다.
- 기존 `MAX_DAILY_ENTRIES=2`, 손실 후 15분 cooldown은 폐기 대상이며 월물당 1사이클 규칙으로 대체한다.

### 1.5 순차 주문·체결 상태

4레그를 한꺼번에 제출하지 않는다. 각 레그는 지정가 주문 한 건씩 순차 제출한다. 사용자 확정 순서:

1. `inner_put_buy`
2. `inner_call_buy`
3. `outer_put_sell`
4. `outer_call_sell`

각 주문은 최대 10분 대기한다. 미체결이면 취소 요청 후 **취소 확인과 취소 중 체결 여부 대사**가 끝나야 다음 상태를 판단할 수 있다. 취소 요청은 취소 완료가 아니다. 사용자가 “취소 확인 후 다음 주문”이라고 지시한 부분과 “앞 레그가 체결되지 않았을 때 뒤 레그를 내지 않는다”는 지시의 경계가 모호하다. 따라서 zero-fill cancel 후 다음 레그로 자동 진행하지 않고 S2-U20 해결 전 `BLOCKED` 처리한다. 선행 레그가 완전히 체결된 사실이 확인되지 않으면 후속 레그를 제출하지 않는다. 두 안쪽 매수의 실제 체결 확인 전 바깥쪽 매도는 제출하지 않는다.

앞 레그가 부분체결·거절·미체결이면 뒤 레그를 제출하지 않는다. 부분체결 lot와 leaves quantity를 분리해 기록하고 실제 노출/최악 추가체결 위험을 다시 계산한다. 맹목적 재주문이나 다음 레그 진행은 금지한다. 안전 복구/청산 우선순위가 정의되지 않았거나 주문·fill·position 상태가 불일치하면 `RECONCILIATION_REQUIRED`/`BLOCKED`로 정지한다. 구체적인 repair vs flatten 정책은 S2-U16으로 남긴다.

### 1.6 손절·trailing·시간 종료

- 손절/이익 청산은 기초자산 가격 변화율이 아니라 **네 레그 옵션의 실제 가격 기반 그룹 손익**을 사용한다.
- 실제 fills, authoritative option mark/quote, multiplier, 잔여 수량, fees 및 slippage를 반영한다. underlying return/intrinsic proxy를 옵션 P&L로 사용하지 않는다.
- `stop_loss_ratio=-0.30`, trailing activation `0.30`, tiers `0.50/1.00`, retention `0.85/0.88/0.90`은 PROVISIONAL 시작값이다. 옵션 그룹 P&L 기준으로 재정의하고 REAL_VTS 검증으로 확정한다.
- mark side(bid/ask/mid 또는 liquidation-side), entry net-cost가 0 이하인 경우, high-watermark/tier/retention의 정확한 공식은 미정(S2-U18). 정의가 없으면 P&L 지표를 추정하지 않고 해당 판단을 BLOCKED로 한다. 월물 만기일 15:10 terminal close intent는 유지한다.
- `SHORT_SWITCH_TIMEOUT_EXIT`와 trailing 이후 15분 short-switch timer는 사용자 폐기 확정(2026-10-13). 관련 상태·타이머·종료 경로는 목표 설계에서 제거 대상이다. 코드에 남아 있는 것은 차이로 기록한다.
- exit pending 중 신규 진입 금지. 15:10 terminal close intent를 충족하되, ACK/cancel request만으로 flat으로 보지 않는다. 모든 lot가 flat으로 확인될 때만 종료 완료다.

### 1.7 설정·실행 provenance

모든 threshold, offsets, timeout, risk budget, session rule은 versioned config에 둔다. 실행마다 config version/hash, monthly expiry, input provenance, structure selection, signal reasons, per-leg order/fill/cancel states, mark/fill P&L, close reason을 기록한다. REAL_VTS tuning/validation 기간은 분리한다. null/PROVISIONAL critical settings, invalid hash, missing/stale/mismatched data, risk limit unavailable이면 신규 주문을 차단한다.

## 2. 설정 스키마 초안 — PROVISIONAL

```yaml
strategy2:
  status: PROVISIONAL
  target_expiry_series: [monthly] # daily/weekly future expansion only
  low_vol_ratio: 0.85
  wide: {long_offset_pt: 5.0, short_offset_pt: 10.0}
  narrow: {long_offset_pt: 2.5, short_offset_pt: 7.5}
  qty_per_leg: 1
  entry:
    bbw_condition: null
    volume_z_min: 3.0
    obi_abs_min: 0.5
    basis_min: 0.3
    poc_distance_min_pt: 1.0
    iv_skew_rule: from_code
  entry_attempt_days: 3
  entry_daily_end_time: "15:00"
  reentry_same_expiry: false
  order_style: sequential_limit
  leg_order: [inner_put_buy, inner_call_buy, outer_put_sell, outer_call_sell]
  order_timeout_minutes: 10
  stop_loss_ratio: -0.30 # provisional; option-group P&L basis
  trailing_activate_ratio: 0.30
  trailing_tiers: {mid: 0.50, high: 1.00}
  trailing_retention: {low: 0.85, mid: 0.88, high: 0.90}
  force_close_time: "15:10"
  max_daily_entries: null # retired; never use as live rule
  cooldown_after_loss_minutes: null # retired
  short_switch_timeout_minutes: null # retired
  risk:
    account_total_capital: null
    strategy_max_premium: null
    strategy_max_loss: null
    account_max_loss: null
    max_margin_utilization_ratio: null
    fees_slippage_model: null
  data:
    freshness_seconds: null
    bbw_window: null
    volatility_source: null
    iv_source: null
    limit_price_basis: null
    tick_rounding_rule: null
    quote_max_age_seconds: null
    max_spread_ticks: null
  config_version: null
```

## 3. F01–F29 재분류표

분류는 의도/설정/추가 확인 상태이며 구현 완료를 뜻하지 않는다.

| ID | 판단요소 | 분류 | v0.3 기준 |
|---|---|---|---|
| F01 | 구조/경제적 역할 | 확정 해결 | 안쪽 CALL/PUT BUY + 바깥쪽 CALL/PUT SELL, §1.1 |
| F02 | 시장·상품 | 확정 해결 | 일반 KOSPI200 옵션, Mini 미사용, §1.1/No.1070 |
| F03 | 주기·활성화 | 확정 해결 | 월물 시작 후 첫 3일, 일별 15:00, 만기일 15:10, 월물당 1사이클 |
| F04 | 가격·시점·provenance | 설정 이관 | source/time/freshness/unit/identity 설정 및 검증 필요 |
| F05 | 진입 feature 집합 | 확정 해결 | BBW, volume z, OBI, basis, POC/방향, IV 비교 전부 유지 |
| F06 | 중복·재진입 | 확정 해결 | active/pending 중 중복 금지, 같은 월물 청산 후 재진입 금지 |
| F07 | 대기·취소·순차 주문 | 확정 해결 | sequential limit, 10분 대기, cancel-confirm/fill reconciliation; zero-fill cancel 후 진행 여부는 S2-U20 |
| F08 | 계약·만기 선택 | 사용자 확인 필요 | exact YYYYMMDD/standard product; ATM tie-break/listed strike/expiry source semantics open (S2-U17) |
| F09 | 행사가 offset | 확정 해결 | wide ±5/±10, narrow ±2.5/±7.5; listed strike validation separate |
| F10 | volatility regime | 설정 이관 | ratio 0.85 provisional; active/base definitions, window, equality |
| F11 | microstructure/IV skew | 설정 이관 | 3.0/0.5/0.3/1.0 and IV rule remain provisional pending units/source/boundaries |
| F12 | quantity/capital/cost | 확정 해결 | 1 contract per leg; risk budgets separately configured and null-blocked |
| F13 | order type/pricing | 확정 해결 | sequential limit; legacy MID_PRICE_OFFSET 1 tick not approved |
| F14 | group preflight | 설정 이관 | four-contract/quote/cost/margin/max-loss/fee/stress/account gate; runtime proof absent |
| F15 | partial/reject/cancel race | 사용자 확인 필요 | next-leg rule set; repair/flatten priority S2-U16 |
| F16 | hedge/overlay | 확정 해결 | no unapproved Futures/extra options leg |
| F17 | inventory/exposure | 사용자 확인 필요 | authoritative per-leg lots/marks/exposure and source lifecycle not verified (S2-U19) |
| F18 | stop loss | 설정 이관 | option group P&L basis confirmed; −30% provisional and formula/mark side open |
| F19 | take-profit/trailing | 설정 이관 | option group P&L basis confirmed; 30/50/100 and 85/88/90 provisional |
| F20 | time/expiry exit | 확정 해결 | monthly expiry day 15:10 close start; actual flat required |
| F21 | close scope/qty | 사용자 확인 필요 | use actual lot remaining quantity; partial close/race verification open (S2-U16/U19) |
| F22 | P&L/fees/slippage | 사용자 확인 필요 | authoritative mark/fill/multiplier/fees and denominator unresolved (S2-U18) |
| F23 | trigger priority/short switch | 확정 해결 | retire short-switch timer/path; preserve 15:10 terminal close |
| F24 | lifecycle/provenance | 사용자 확인 필요 | config hash and run/group/leg/order/execution/position linkage; restore unverified (S2-U19) |
| F25 | restart/timer cleanup | 확정 해결 | retire short-switch path; reconcile before resume/reset; flat before terminal reset |
| F26 | cross-strategy/account risk | 설정 이관 | aggregate S1/S6/S7/S8/S9 exposures; null/unverified caps block |
| F27 | data error/fail-closed | 설정 이관 | fail-closed policy set; source freshness/enforcement configured and verified separately |
| F28 | config/resume | 설정 이관 | version/hash/effective time and risk limits; null/provisional blocks |
| F29 | test/acceptance | 사용자 확인 필요 | exact test IDs, REAL_VTS split, acceptance/evidence mapping not run (NOT_RUN) |

**집계: 확정 해결 13 / 설정 이관 9 / 사용자 확인 필요 7 = 29.** “확정 해결”은 정책/의도가 문서상 확정됐다는 뜻이지 runtime PASS가 아니다.

## 4. 목표 상태 전이표

| 현재 상태 | 조건/이벤트 | 다음 상태 | 필수 동작 | 실패/예외 |
|---|---|---|---|---|
| DISABLED | config null/PROVISIONAL, risk limit unavailable | BLOCKED | no new order; record missing keys | verified config required |
| DISABLED | config/schema and exact monthly expiry source available | DATA_WARMUP | load config version/hash and expiry YYYYMMDD | identity/calendar unknown → BLOCKED |
| DATA_WARMUP | all features fresh, valid, same-session/identity and sample sufficient | PRE_ENTRY_CHECK | preserve source/as-of/received timestamps | missing/stale/mismatch → UNAVAILABLE; reconcile existing lots |
| PRE_ENTRY_CHECK | first 3 monthly-start days, before 15:00, all entry conditions pass, cycle unused and flat | STRUCTURE_SELECTED | record every condition result | else wait; no duplicate entry |
| STRUCTURE_SELECTED | ratio/ATM/listed contracts and all quotes valid | GROUP_PREFLIGHT | choose wide/narrow and calculate premium/margin/max-loss/stress | missing/invalid contract or risk input → BLOCKED |
| GROUP_PREFLIGHT | all four legs and account risk pass | ENTRY_LEG_1_WORKING | submit inner PUT BUY limit; save order ID | no active state before fill |
| ENTRY_LEG_1_WORKING | inner PUT fully filled and reconciled | ENTRY_LEG_2_WORKING | submit inner CALL BUY | partial/reject/timeout/race → RECONCILIATION_REQUIRED; no next leg |
| ENTRY_LEG_2_WORKING | inner CALL fully filled and reconciled | ENTRY_LEG_3_WORKING | confirm both inner buys then submit outer PUT SELL | any mismatch → BLOCKED; no short leg |
| ENTRY_LEG_3_WORKING | outer PUT fully filled and reconciled | ENTRY_LEG_4_WORKING | re-check protection/risk then submit outer CALL SELL | partial/reject/race → RECONCILIATION_REQUIRED; no next leg |
| ENTRY_LEG_4_WORKING | outer CALL fully filled and all 4 lots reconcile | ACTIVE | record net cost, fills, fees, marks, hash, cycle consumption | mismatch → BLOCKED, do not infer ACTIVE/FLAT |
| any ENTRY_WORKING | 10 min timeout | CANCEL_PENDING | request cancel; track order state | cancel request alone is not terminal |
| CANCEL_PENDING | cancel confirmed and cumulative fills/leaves reconciled | RECONCILIATION_REQUIRED | rebuild actual exposure including late fills | unknown state → BLOCKED |
| RECONCILIATION_REQUIRED | all orders terminal and positions reconciled | RECOVERY_DECISION | block entry; calculate residual/worst-case exposure | unresolved policy → BLOCKED |
| RECOVERY_DECISION | approved recovery/close path exists | EXIT_PENDING | close actual filled lots by actual remaining qty | no approved path → BLOCKED; no blind retry |
| ACTIVE | valid option-group P&L stop/trailing | EXIT_PENDING | record marks, formula, trigger and close plan | invalid/stale mark blocks metric action; expiry rule still applies |
| ACTIVE / open exposure | monthly expiry date and time >=15:10 | EXIT_PENDING | terminal close all S2 lots; suppress entry | 15:10 does not imply fill/flat |
| EXIT_PENDING | partial/reject/cancel race | RECONCILIATION_REQUIRED | reconcile order leaves/late fills/actual lots | no false flat |
| EXIT_PENDING | all orders terminal and authoritative S2 position flat | FLAT_CONFIRMED | reconcile account positions and S2 lots | mismatch → BLOCKED |
| FLAT_CONFIRMED | P&L/fees/config and cycle reconciled | CLOSED | mark monthly cycle consumed; no same-expiry reentry | mismatch → BLOCKED, no reset |
| restart/reconnect | any pending order or open exposure possible | RECONCILIATION_REQUIRED | restore orders/fills/positions/timers/config before evaluate | no reconcile PASS → no resume |

**State rule:** signal/submit/ACK is not fill. Update active exposure, cycle consumed, entry cost, watermark and P&L only from authoritative execution/position evidence. Each leg has independent state; group state is derived from reconciled leg states.

## 5. v0.2 D01–D10 disposition

| v0.2 item | v0.3 disposition | Basis |
|---|---|---|
| D01 thesis/4-leg payoff | structure intent resolved; payoff/stress validation BLOCKED | §1.1, S2-U18 |
| D02 offsets/rounding | offsets resolved; listed-strike rounding open | §1.2, S2-U17 |
| D03 feature/skew | feature set/direction resolved; formula/units/source/boundaries provisional | §1.3, S2-U17 |
| D04 stop/trailing basis | option group P&L basis resolved; exact formula/mark semantics provisional | §1.6, S2-U18 |
| D05 entry cap/cooldown | daily cap/cooldown retired; monthly one-cycle rule resolved | §1.4 |
| D06 expiry/overnight/cutoff | monthly expiry 15:10 and entry window intent resolved; official calendar/broker proof pending | §1.4, S2-U17 |
| D07 partial-fill recovery | order sequence resolved; repair/flatten priority open | §1.5, S2-U16 |
| D08 capital/premium/max-loss | editable settings; null/provisional blocks | §1.7/§2 |
| D09 freshness/product filter | standard product/no Mini resolved; source/freshness enforcement pending | §1.1/§1.3 |
| D10 restart/timer/duplicate entry | policy resolved; durable restore/position evidence pending | §1.5–1.7, S2-U19 |

## 6. New S2 unresolved items

| ID | Unresolved item | Needed evidence / impact | Status |
|---|---|---|---|
| S2-U16 | Partial/reject/timeout/cancel-race recovery: flatten all filled legs or approved repair sequence; exact close order/retry guard | Per-leg events, worst-case exposure, REAL_VTS/Virtual scenarios; no next leg until previous full fill and reconciliation | 사용자 확인 필요 / BLOCKED |
| S2-U17 | ATM tie-break/listed strike rounding, exact expiry source, active/base ratio and feature freshness/boundaries | Authoritative Option Master, KRX calendar, timestamped source observations; unknown source/identity blocks entry | 사용자 확인 필요 / BLOCKED |
| S2-U18 | Mark/liquidation-side, net entry cost denominator, fees/slippage, stop/trailing formulas/tier semantics | Actual bid/ask/mark/fill/multiplier/fee ledger and separate tuning/validation data; no silent normalization for non-positive denominator | 사용자 확인 필요 / BLOCKED |
| S2-U19 | Durable per-leg order/fill/position/P&L/config restore and authoritative flat source | Restart/cancel-race/late-fill scenarios and account position reconciliation | 사용자 확인 필요 / BLOCKED |
| S2-U20 | Zero-fill timeout/cancel-confirm 이후 다음 레그로 진행할지, 월물 cycle을 중단할지; partial fill은 recovery 상태로 갈지 | 사용자 문구의 “취소 확인 후 다음 주문”과 “앞 레그 미체결이면 뒤 레그 금지” 경계가 충돌함. 정확한 상태전이 승인 전 zero-fill 후 자동 진행 금지 | 사용자 확인 필요 / BLOCKED |
| S2-U21 | 지정가 산정 기준, tick rounding, quote max age, max spread limit | S6 v0.3은 해당 값이 null이면 진입 차단으로 정의. S2에도 option limit basis/source/freshness/spread config 및 REAL_VTS evidence 필요 | 사용자 확인 필요 / BLOCKED |

## 7. U01–U15 global register classification (IDs preserved)

| ID | Topic | S2 disposition | Boundary |
|---|---|---|---|
| U01 | S1 payoff/structure | 사용자 확인 필요 — unchanged | S1 only |
| U02 | S2 4-leg payoff/stop/trailing basis | 확정 해결 — intent only | 4-leg structure and option-P&L basis set; payoff/mark validation remains S2-U18 |
| U03 | S3 tradable spread identity | 사용자 확인 필요 — unchanged | S3 only |
| U04 | S4 option lots/Greeks/basecamp | 사용자 확인 필요 — unchanged | S4 only |
| U05 | S5 Futures role | 사용자 확인 필요 — unchanged | No.1151 applies to S5; retired No.1168 not revived |
| U06 | S6 pair MTM/partial/cutoff | 사용자 확인 필요 — unchanged | S6 only |
| U07 | S7 IV skew/expiry | 사용자 확인 필요 — unchanged | S7 only |
| U08 | S8 add-on/rounding/DTE | 사용자 확인 필요 — unchanged | S8 only |
| U09 | S9 entry/open/close timing | 사용자 확인 필요 — unchanged | S9 only |
| U10 | Account capital/risk values | 설정 이관 | versioned config; null/provisional blocks entry |
| U11 | Common partial/cancel/restart | 확정 해결 — policy only | reconcile before resume/reset; runtime proof pending S2-U19 |
| U12 | Account aggregate exposure/correlation/netting | 설정 이관 | S2 joins account aggregation; model/limits not validated |
| U13 | Authoritative P&L/fee/multiplier | 사용자 확인 필요 | mark/fee source semantics under S2-U18 |
| U14 | Exact expiry/session service | 확정 해결 — S2 intent only | monthly expiry 15:10 intent; calendar/master proof pending |
| U15 | Shrimp Resume Context | 사용자 확인 필요 / UNAVAILABLE | not inspected or updated in this task |

## 8. I01–I16 S2 interaction classification

| ID | S2-related interaction | Classification | S2-specific target / blocker |
|---|---|---|---|
| I01 | capital/premium/max-loss/margin | 설정 이관 | one group budget reserved before first leg; null blocks |
| I02 | shared Futures hedge | 확정 해결 | S2 has no Futures hedge; other strategy issues remain separate |
| I03 | option inventory/Greeks ownership | 사용자 확인 필요 | strategy/group/leg provenance and actual fills required |
| I04 | overlapping insurance/tail risk | 설정 이관 | aggregate S2 with S1/S6/S7/S8/S9 by expiry/strike/premium/margin/stress |
| I05 | multi-leg partial/cancel race | 확정 해결 — policy only | fixed sequence and cancel-confirm; runtime proof pending; recovery S2-U16 |
| I06 | P&L attribution | 설정 이관 | option-group P&L replaces underlying proxy; marks/fees source pending |
| I07 | expiry/session | 확정 해결 — policy only | monthly/first 3 days/15:00/15:10; calendar proof pending |
| I08 | exit priority | 확정 해결 — policy only | 15:10 close; exit-pending suppresses entry; no flat without evidence |
| I09 | freshness/unavailable | 설정 이관 | fail-closed policy; source thresholds/enforcement pending |
| I10 | restart/idempotency | 확정 해결 — policy only | reconcile before resume/reset; durable proof S2-U19 |
| I11 | S5 Futures role | 확정 해결 for S2 | S2 does not convert/use Futures; S5 unchanged |
| I12 | S3 spread identity | 확정 해결 for S2 | S2 is not a Futures spread; S3 unchanged |
| I13 | S4 hedge ownership | 사용자 확인 필요 | keep S2 inventory separate from S4 hedge inventory |
| I14 | S8 add-on/resolver | 확정 해결 for S2 intent | never rewrite S2 4-leg intent as single PUT SELL; code mismatch remains |
| I15 | cycle re-entry | 확정 해결 — policy only | one cycle/month, no same-expiry reentry; account aggregation pending |
| I16 | config consistency | 설정 이관 | version/hash/effective settings; null/provisional blocks |

## 9. G01–G12 completeness gate disposition

| Gate | S2 disposition | Remaining evidence |
|---|---|---|
| G01 payoff/role | 설정 이관 | signed net premium, payoff/stress validation |
| G02 entry/scale/exit | 설정 이관 | feature definitions, threshold boundaries, trigger formulas |
| G03 contract/expiry/qty/multiplier | 설정 이관 | exact contract identity, strike rounding, calendar |
| G04 partial/reject/cancel/timeout | 확정 해결 — policy only | per-leg state/recovery tests NOT_RUN |
| G05 hedge/rebalance/overlay | 확정 해결 | no unapproved overlay |
| G06 stop/trailing/time exit | 설정 이관 | group P&L formula, marks/fills/fees |
| G07 session/expiry/rollover | 확정 해결 — policy only | official calendar and broker semantics |
| G08 account risk | 설정 이관 | risk values null/provisional; enforcement unverified |
| G09 failure/restart/recovery | 사용자 확인 필요 | S2-U16/U19 and durable evidence |
| G10 traceability | 사용자 확인 필요 | exact test IDs/evidence not run/mapped |
| G11 assumptions/dependencies | 확정 해결 — register created | S2-U16–U21 explicitly listed; registration is not resolution |
| G12 validation vs approval | 확정 해결 | v0.3 remains draft/unverified/unapproved |

## 10. Validation plan — not executed

- Entry boundaries: ratio 0.8499/0.8500/0.8501; z 2.99/3.00/3.01; abs OBI 0.499/0.500/0.501; basis/POC boundaries; BBW missing/stale; IV expiry/strike mismatch.
- Contracts: exact YYYYMMDD, standard-vs-Mini, multiplier, listed strikes, ATM tie and rounding.
- Orders: each leg full/partial/reject; 9:59/10:00/10:01; fill during cancel; late fill; no next leg before full fill/reconciliation; no outer short before both inner buys.
- P&L: option group marks/fills/fees, non-positive entry cost, stop -30%, trailing 30/50/100% boundaries after formulas are approved.
- Expiry: 15:09:59/15:10:00/15:10:01; close partial/reject; no false flat; no same-month reentry; next month only after calendar and flat checks.
- Restart: working/cancel-pending order, late fill, partial lots, config version change; reconcile before resume.
- Cross-strategy: overlapping strikes/expiry, aggregate premium/margin/max-loss/stress, no assumed netting.
- Separate REAL_VTS tuning and validation windows; record dataset IDs and config hash.

**No tests or REAL_VTS validation were run.** All cases remain NOT_RUN. Document structure is not strategy validation.

## 11. Final status

- Specification: **draft / unverified / unapproved**.
- Runtime/strategy correctness: **BLOCKED** pending S2-U16–U21, authoritative source evidence, risk settings and test validation.
- No code edits, test runs, commit/push, KIS Live orders, Decision Log deletion/edits, or Shrimp update are included in this document task.

---
## v0.4 사용자 규칙 갱신 — S2 취소·잔여 레그 재주문
상태: DRAFT / VERIFYING / UNAPPROVED. 이 절은 과거 초안의 상충 규칙보다 우선하며, 런타임 구현 완료를 뜻하지 않는다.
1. 주문 취소는 CANCEL_REQUESTED와 CANCEL_CONFIRMED를 구분한다. 취소 요청만으로 미체결이라고 판단하거나 같은 수량을 재주문하지 않는다.
2. 취소 확인 후 해당 주문의 execution/fill 조회와 broker position/order 대사를 수행한다. 취소 처리 중 체결·부분체결·late fill이 있으면 실제 체결 수량을 반영한다.
3. remaining_target_qty = target_qty - reconciled_filled_qty를 레그별로 계산한다. 잔여 목표가 0 이하이면 재주문하지 않는다. 양수일 때만 잔여 목표 수량을 재주문한다. 실제 체결 원장·미체결 주문·포지션이 서로 불일치하면 RECONCILIATION_REQUIRED로 fail-closed한다.
4. 전략 의도(target intent)는 실제 목표 체결 수량이 확인될 때까지 유지한다. 취소된 거래소 주문 자체를 살아 있는 주문처럼 취급하지 않는다. 각 재시도는 이전 주문의 종료 상태와 체결 수량 대사 완료 후에만 허용한다.
5. 재시도는 새롭고 유효한 quote snapshot에서만 평가한다. 매수는 ask 기준, 매도는 bid 기준의 marketable-limit 후보를 만들 수 있으나, KRX 호가단위 정규화·허용 슬리피지·가격 상한/하한·quote freshness·재호가 간격은 검증된 설정으로 제한한다. 해당 설정이 없으면 신규 주문은 BLOCKED다.
6. retry_interval, max_retry_attempts 및 max_adverse_slippage_ticks는 설정 항목으로 둔다. REAL_VTS 기록으로 검증되기 전에는 수치를 임의 확정하지 않는다. 설정 누락, 세션/위험 한도 초과, stale quote, 중복 client_order_id 가능성은 재시도를 차단한다.
7. 검증 시 cancel/fill race, partial fill, late fill, duplicate signal, restart, broker position mismatch를 포함한다. 주문 ACK는 체결 증거가 아니며 실제 fill/position 대사 전 전략 레그를 완료 처리하지 않는다.
