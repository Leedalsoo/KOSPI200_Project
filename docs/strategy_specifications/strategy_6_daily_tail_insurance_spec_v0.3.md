# Strategy 6 — Daily Tail Insurance 상세 명세 v0.3

- 작성일: 2026-10-13
- 상태: **초안 / 미검증 / 미승인 / 구현 기준 사용 금지**
- v0.2를 보존하고 본 파일을 신규 작성한다.
- 기준 HEAD: 7eb9945e29774fb61fd2d07801762871b2506b98, branch Project200.
- 범위: 문서 갱신만. 코드 수정·테스트 실행·Git stage/commit/push·KIS Live 주문 없음.
- 우선순위: 현재 사용자 확정 의도 > 최신 유효 확정 Decision Log > AGENTS.md. 코드 관찰은 의도나 승인으로 간주하지 않는다.
- 관련 기준: No.966(active/base IV), No.1046, No.1070(미니옵션 미사용), No.1119(정확한 YYYYMMDD 만기), No.1131/1132/1134(레그별 체결·취소 레이스·flat 전 reset 금지), No.1151(선물 역할 분류).
- 이전 S6의 15:00/15:15, intrinsic proxy, pair 동시주문, 테스트 PASS는 현재 명세의 승인 근거가 아니다.

## 1. 사용자 확정 의도

### 1.1 목적과 주기
S6는 당일 만기 KOSPI200 일반 옵션을 이용하는 일물 tail-insurance 양매수다. 거래일 장 시작부터 장 종료까지 운용하며, CALL 1계약과 PUT 1계약을 보험 목적으로 매수한다. 미니옵션과 선물 hedge는 사용하지 않는다. 2배 trailing이 활성화되기 전에는 가격 손절 없이 프리미엄 손실을 감수한다.

양매수는 원자적 멀티레그 주문이 아니다. 각 옵션은 독립 주문·체결·잔여 수량을 가진다. 양쪽 실제 체결 및 포지션 대사 후에만 pair complete로 표시한다. 한쪽만 체결되면 편매수 상태를 유지한다.

### 1.2 변동성 진입 조건
- 공식 장 시작 이후 11:00까지 진입 조건을 감시한다. 11:00 경계의 포함 여부는 설정/시나리오 검증 대상으로 기록한다.
- 진입 조건은 active_vol >= base_vol × 1.3 이다.
- 확정 Decision Log No.966의 의미:
  - active_vol: 현재 KOSPI200 ATM CALL과 PUT의 KIS HTS_INTS_VLTL 평균을 canonical decimal로 변환.
  - base_vol: 같은 거래 세션에서 동일 ATM/만기 선택 규칙으로 처음 확보한 유효 ATM CALL/PUT IV 평균.
  - CALL/PUT 양쪽의 authoritative IV가 없으면 UNAVAILABLE/fail-closed.
  - 세션 변경 시 baseline reset.
- 1.3은 의도상 확정값이지만, REAL_VTS 데이터 신선도·coverage 및 독립 검증 기간은 검증 게이트다. synthetic/scenario 값으로 authoritative IV를 대체하지 않는다.

### 1.3 행사가 및 순차 주문
- 후보는 ATM 기준 5번째 또는 6번째 바깥 행사가다. 행사가 간격이 2.5pt인 사다리에서 5번째는 ±12.5pt, 6번째는 ±15.0pt다. 실제 listed strike, expiry, option type, symbol은 Option Master에서 확인하며 계약을 계산으로 만들어내지 않는다.
- 한 번에 한 주문만 낸다. 5번째와 6번째를 동시에 제출하지 않는다.
- 후보가 상장 계약/유효 호가를 제공하지 못해 preflight에서 주문을 만들 수 없는 경우, 미전송 또는 취소 완료를 확인한 뒤 다른 rank 후보를 검토할 수 있다. 첫 순위와 정확한 fallback trigger는 설정·REAL_VTS 검증 후보이며 임의 확정하지 않는다.
- S6에서 최초 주문이 10분 동안 아무것도 체결되지 않으면 그날 진입을 종료하고 재시도하지 않는다. 따라서 제출 후 미체결 timeout을 이유로 다른 rank를 자동 재주문하지 않는다.
- 각 주문은 해당 옵션 가격 기준의 지정가 예약주문이다. limit 기준(bid/ask/승인된 mark), tick 반올림, quote freshness 및 spread 제한은 설정/검증 대상이며, 값이 null이면 진입 차단.

### 1.4 편매수·양매수 완성
- 첫 CALL 또는 PUT이 실제 체결되면 그 레그의 fill price와 quantity를 저장하고 반대편 주문을 시작한다.
- 반대 옵션 주문은 첫 레그 체결 후 최대 10분 대기한다. 이 기간 내 반대편이 체결되고 두 레그의 position reconciliation이 완료된 경우에만 pair complete.
- 반대편이 10분 내 체결되지 않으면 취소 요청 후 취소 완료와 취소 중 추가 체결을 대사한다. 그 뒤 실제 체결된 레그만 편매수로 유지하며, 미체결 레그를 보유 중으로 기록하지 않는다.
- 취소 요청/ACK는 취소 완료가 아니다. 취소 중 체결이 확인되면 해당 fill을 반영하고 신규 주문 전 포지션을 다시 대사한다.
- 부분체결은 filled quantity와 leaves quantity를 분리한다. 미체결 수량을 체결된 것으로 간주하거나 목표 1계약을 넘겨 임의 증액하지 않는다.
- timeout_split은 per_order(각 주문별 10분)와 shared_elapsed(공유 경과시간) 후보로 두고 검증한다. null이면 신규 주문을 차단한다.

### 1.5 수량·청산
- CALL 1계약, PUT 1계약 고정. 전략 내부 수량 확대/배수 로직 금지.
- 각 옵션은 그 레그의 실제 매수 평균 체결가를 기준으로 독립 청산한다.
- 해당 레그 옵션 가격이 실제 매수 체결가의 2.0배 이상에 도달하면 해당 레그의 high-water tracking을 활성화한다. 2배 도달은 즉시 익절이 아니다.
- 활성화 후 해당 레그의 가격이 그 레그 고점 대비 10% 이상 하락하면 그 레그의 실제 잔여 수량을 청산한다.
- 2배 전 손절은 없다. stop_loss_enabled=false로 명시한다. stop_loss:null은 비활성화 플래그와 별도로 보존하며 null을 0 또는 임의 한도로 바꾸지 않는다.
- 15:10에 모든 S6 잔여 포지션을 무조건 청산 대상으로 만든다. 기존 15:00 limit/15:15 fallback은 불일치다. 15:10의 주문 유형·tick·broker cutoff 처리는 설정/실행 검증 대상이나 청산 대상 시각 자체를 변경하지 않는다.
- 15:10 강제청산은 trailing보다 우선한다. 실제 모든 잔여 수량이 flat으로 대사되기 전 전략 상태를 reset하지 않는다.

### 1.6 공통 주문·체결 안전 규칙
- 주문 계획/ACK만으로 ACTIVE가 되지 않는다. 한 레그 체결은 PARTIALLY_EXPOSED, 양 레그의 실제 체결과 대사 완료는 PAIR_ACTIVE.
- 각 레그에 order/client_order/execution ID, filled/leaves quantity, average fill price, actual position, fee, mark, config version/hash를 보존한다.
- restart, 날짜 변경, timeout, stale quote, contract mismatch, unknown order/fill 상태에서는 authoritative orders/fills/positions를 대사한다. 확인 전 신규 주문과 daily reset 금지.
- actual residual position이 있는 동안 FLAT_CONFIRMED/CLOSED로 이동하지 않는다.
- REAL_VTS 튜닝 기간과 독립 검증 기간을 분리하고 실행마다 config version/hash/effective time을 기록한다. PROVISIONAL 설정의 null/미검증 값은 신규 주문을 차단한다.

## 2. 확정 규칙 / 설정 이관 / 검증 필요

| 항목 | 분류 | 규칙 |
|---|---|---|
| 일물·세션 | 확정 | 당일 만기, 공식 장 시작~종료 |
| 변동성 | 확정 규칙 | active_vol >= base_vol × 1.3, No.966의 ATM CALL/PUT IV 평균 정의 |
| 진입창·일일 횟수 | 확정 | 장 시작 후 11:00까지, 하루 최대 1회 |
| 첫 주문 무체결 | 확정 | 10분 timeout, 그날 종료·재시도 없음 |
| 주문 방식 | 확정 | 독립 단일 레그 지정가; 동시 pair 제출 금지 |
| rank 5/6 | 확정 후보군 | ±12.5/±15.0pt, listed contract 확인 |
| first_rank | 설정 이관 | 5 또는 6, REAL_VTS 검증 전 null |
| timeout_split | 설정 이관 | per_order/shared_elapsed 후보, null이면 차단 |
| CALL/PUT 수량 | 확정 | 각 1계약, 증량 금지 |
| trailing | 확정 | 개별 entry fill ×2에서 arm, 개별 high-water 대비 10% 하락 |
| 손절 | 확정 | 2배 전 손절 없음, stop_loss_enabled=false |
| 시간 종료 | 확정 | 15:10 모든 잔여 레그 청산 대상 |
| limit 가격/freshness/spread/tick | 설정·검증 이관 | quote source/age, limit basis, spread/tick 검증 |
| expiry/상품 | 확정 원칙 | exact YYYYMMDD, authoritative Option Master, 미니옵션 금지 |
| partial/cancel/restart/flat | 확정 공통 원칙 | 레그별 대사, 취소 확인 및 flat 전 reset 금지 |
| 계좌 위험 한도 | 설정·검증 이관 | S6 qty 고정과 별도로 계좌 premium/margin/max-loss 합산 |
| 실행/검증 evidence | 검증 대기 | REAL_VTS 구간 분리, config version/hash 기록 |

## 3. PROVISIONAL 설정 스키마
아래는 설정 스키마 초안이다. null, 누락, 미검증 또는 잘못된 값은 신규 주문 차단 조건이다.

~~~yaml
strategy6:
  status: PROVISIONAL
  vol_ratio_min: 1.3
  entry_end_time: "11:00"
  entry_end_inclusive: null
  max_entries_per_day: 1
  strike_ranks: [5, 6]
  first_rank: null
  fallback_on_preflight_unavailable: true
  fallback_on_submitted_order_timeout: false
  order_timeout_minutes: 10
  timeout_split: null
  qty_call: 1
  qty_put: 1
  trailing_activate_multiple: 2.0
  trailing_drawdown: 0.10
  stop_loss_enabled: false
  stop_loss: null
  force_close_time: "15:10"
  quote_mark_source: null
  quote_max_age_seconds: null
  max_spread_ticks: null
  config_version: null
  tuning_window_id: null
  validation_window_id: null
~~~

first_rank, timeout_split, quote_mark_source, quote_max_age_seconds, max_spread_ticks 및 11:00 경계 포함 여부는 사용자에게 다시 질문하지 않고 설정/검증 후보로 유지한다. 유효 값과 검증 증거가 없으면 fail-closed한다.

## 4. 상태 전이표

| 현재 상태 | 이벤트/조건 | 다음 상태 | 행동 및 실패 처리 |
|---|---|---|---|
| DISABLED | ON + config valid | WAITING_FOR_SESSION | config version/hash 기록; PROVISIONAL 미검증이면 BLOCKED |
| WAITING_FOR_SESSION | official calendar/session/source valid | VOL_TRIGGER_CHECK | 공식 장 시작 확인; 추정 open이면 차단 |
| VOL_TRIGGER_CHECK | 시각 허용 + active/base >= 1.3 | CONTRACT_PREFLIGHT | 같은 snapshot의 IV, expiry, Option Master, quote 확인 |
| VOL_TRIGGER_CHECK | ratio 미충족 또는 창 종료 | WAITING/ENTRY_WINDOW_CLOSED | 주문 없음; unavailable과 valid false 구분 |
| CONTRACT_PREFLIGHT | candidate identity/quote/risk valid | ENTRY_PLANNED | rank 하나만 선택; 다른 rank 동시 제출 금지 |
| ENTRY_PLANNED | order persisted and submitted | FIRST_ORDER_WORKING | deadline 및 idempotency 저장 |
| FIRST_ORDER_WORKING | 첫 레그 전량 fill + 대사 | SINGLE_LEG_FILLED | 실제 fill price/qty 기록; 반대편 timer 시작 |
| FIRST_ORDER_WORKING | partial fill | PARTIALLY_EXPOSED | filled/leaves 구분; 임의 증량 금지 |
| FIRST_ORDER_WORKING | 10분 동안 no fill | CANCEL_PENDING | cancel request 후 late fills 대사; 취소 완료 시 당일 종료 |
| FIRST_ORDER_WORKING | 사전검증에서 미전송으로 확정된 rank unavailable | CONTRACT_PREFLIGHT | 설정에 따라 다음 rank를 순차 검토 |
| CANCEL_PENDING | cancel complete + zero fill confirmed | ENTRY_WINDOW_CLOSED | 당일 재진입 금지 |
| CANCEL_PENDING | cancel 중 fill/상태 미상 | RECONCILIATION_REQUIRED | 새 주문 금지, authoritative 대사 |
| SINGLE_LEG_FILLED | opposite order submitted | OPPOSITE_ORDER_WORKING | 반대 레그 1계약; timeout_split 설정 적용 |
| OPPOSITE_ORDER_WORKING | opposite fill + both positions reconciled | PAIR_ACTIVE | 두 레그의 fill/position 연결 |
| OPPOSITE_ORDER_WORKING | timeout | CANCEL_PENDING | 반대 주문 취소/late fill 대사; 실제 편매수 유지 |
| CANCEL_PENDING | opposite cancel complete, first leg remains | SINGLE_LEG_HELD | 체결된 레그만 trailing/15:10 관리 |
| SINGLE_LEG_HELD/PAIR_ACTIVE | per-leg mark >= that leg fill × 2 | TRAILING_ACTIVE_PER_LEG | 해당 레그만 high-water 추적 |
| TRAILING_ACTIVE_PER_LEG | per-leg mark <= high-water × 0.90 | EXIT_PENDING | 해당 레그 actual remaining qty close |
| any open state | official time >= 15:10 | EXIT_PENDING | 모든 actual S6 residual legs close; trailing보다 우선 |
| EXIT_PENDING | 모든 잔여 qty 0 + orders/fills reconciled | FLAT_CONFIRMED | fees/P&L/config provenance finalize |
| FLAT_CONFIRMED | accounting/log complete | CLOSED | 다음 거래일 정책에 따라 새 lifecycle |
| any | restart, stale quote, unknown order/fill, mismatch | RECONCILIATION_REQUIRED | authoritative reconciliation 전 주문/reset 금지 |
| any | required config/data unavailable | BLOCKED/UNAVAILABLE | reason code 기록, 추정값 사용 금지 |

### 취소 레이스 처리
1. Timeout이면 cancel request를 기록하고 terminal cancel 상태를 기다린다.
2. Cancel-pending 중 들어온 execution report를 반영한다.
3. filled/leaves, open lots 및 broker position을 대사한다.
4. 취소 확인 후에만 다른 candidate를 고려할 수 있다. 단, S6 첫 주문이 10분 무체결이면 당일 종료이므로 순위 재시도하지 않는다.
5. 취소 완료 또는 포지션을 확인할 수 없으면 RECONCILIATION_REQUIRED; 추정 재주문 금지.

## 5. F01–F29 재분류표

분류는 의도/설정/검증 상태이며 코드 구현 완료를 의미하지 않는다.

| ID | 판단 요소 | v0.3 규칙 | 분류 | 구현·검증 게이트 |
|---|---|---|---|---|
| F01 | 목적/payoff | 당일 만기 tail-insurance 양매수 | 확정 | payoff/stress 성능은 미검증 |
| F02 | 상품 범위 | KOSPI200 일반 옵션, mini 금지 | 확정 | Option Master 확인 |
| F03 | 세션/lifecycle | 장 시작~종료, 11:00 진입 종료, 하루 1회, 15:10 close | 확정 | official calendar 검증 |
| F04 | 데이터/provenance | IV, contract, quote, fill, mark, position source/time | 설정·검증 이관 | freshness/coverage 증거 |
| F05 | 진입 공식 | active >= base × 1.3 | 확정 | REAL_VTS source validation |
| F06 | 중복/re-entry | 하루 1회; 첫 주문 no-fill 10분이면 당일 종료 | 확정 | fill-driven state 확인 |
| F07 | pending/cancel | 단일 순차 주문, 10분 timeout, cancel 확인 전 다음 주문 금지 | 확정 의도 + 설정 후보 | timeout_split/fallback validation |
| F08 | contract/expiry | 당일 만기 exact YYYYMMDD | 확정 | master identity |
| F09 | strike/price | rank 5/6, ±12.5/±15.0, limit order | 설정·검증 이관 | first_rank, tick, quote, spread |
| F10 | volatility source | No.966 ATM CALL/PUT IV 평균, session baseline | 확정 규칙 + data gate | REAL_VTS freshness |
| F11 | additional features | 임의 추가 신호 금지 | 확정 | required input missing => block |
| F12 | quantity/cost | CALL 1, PUT 1; no scaling | 확정 | account risk separate |
| F13 | order pricing | per-option limit; price basis not finalized | 설정·검증 이관 | quote source/limit basis |
| F14 | preflight | identity, quote, expiry, qty, budget/risk before order | 확정 공통 원칙 | source gate evidence |
| F15 | partial/cancel race | per-leg state and reconciliation | 확정 공통 원칙 | runtime tests after approval |
| F16 | hedge/additional leg | no futures hedge/additional leg | 확정 | reject unapproved legs |
| F17 | holdings/exposure | actual per-leg open lots/fill/qty/mark | 확정 공통 원칙 | authoritative position proof |
| F18 | stop/max loss | no S6 price stop before 2× | 확정 | account emergency policy distinct |
| F19 | trailing | each leg: 2× fill arms; 10% drawdown from its own peak closes | 확정 | actual option mark + restart watermark |
| F20 | time/expiry | same-day expiry, 15:10 all residual close | 확정 | official calendar/broker behavior |
| F21 | close qty | actual residual quantity of each filled leg | 확정 | flat confirmation |
| F22 | P&L/fees | actual fills/marks/multiplier/fees | 설정·검증 이관 | ledger source proof |
| F23 | priority | 15:10 force-close overrides trailing; exit pending blocks entry | 확정 규칙 | simultaneous trigger tests |
| F24 | provenance | run/group/leg/order/execution/config hash and per-leg watermark | 설정·검증 이관 | durable schema verification |
| F25 | restart/recovery | reconcile before reset/re-entry; no blind retry | 확정 공통 원칙 | persistence not verified |
| F26 | cross-strategy risk | S6/S7/S8/S9 premium, margin, qty, correlated stress aggregated | 설정·검증 이관 | account risk evidence |
| F27 | data failure | stale/missing/mismatched IV/quote/position blocks entry | 확정 공통 원칙 | numeric freshness unset |
| F28 | editable settings | version/hash per run; null/PROVISIONAL blocks | 설정·검증 이관 | runtime enforcement |
| F29 | acceptance | scenarios in §8 are NOT_RUN plans | 검증 대기 | exact test IDs/evidence |

분류 집계(주 분류 기준): **확정 19 / 설정·검증 이관 9 / 사용자 확인 필요 0 / 검증 대기 1**. 일부 행은 확정 의도와 미검증 구현 게이트를 함께 표시한다. 이번 작업에서 새 사용자 확인 질문은 만들지 않는다.

## 6. 코드-의도 차이표 (정적 조사만)

| 경로 | 관찰된 현재 동작 | §1과의 차이 | 판정 |
|---|---|---|---|
| core/strategy/track6_daily_tail_insurance.py | evaluate_buy에서 BUY proposal 반환 전에 is_active/bought_date/strikes 기록(약 117행) | fill 전 active 가능 | 불일치 |
| same | representative PUT BUY proposal 후 build_execution_plan이 build_pair_plan으로 PUT+CALL pair plan 생성(143–149행) | sequential single-leg order와 다름 | 불일치 |
| same | premium_spent/qty를 multiplier처럼 사용해 strike-distance intrinsic proxy 계산(153–176행) | per-leg actual mark/fill price가 아님 | 불일치 |
| same | trailing activation 1.5×/2×, 85/88/90% retention tiers(168–190행) | 2× arm + 10% drawdown 단일 규칙과 다름 | 불일치 |
| same | 15:00 CLOSE_LIMIT 및 15:15 CLOSE_FALLBACK(201–215행) | 15:10 forced close와 다름 | 불일치 |
| same | pair-level high_watermark_intrinsic 하나만 보존 | per-leg entry/mark/high-water가 없음 | 미구현 |
| core/strategy/engine/s6_engine.py | _buy가 fill 전 is_active 설정(72–75행), build_execution_plan이 pair plan 생성(169–175행) | sequential workflow와 다름 | 불일치 |
| same | _take_profit도 premium_spent-derived intrinsic proxy와 tiered threshold(92–132행) | actual per-leg mark required | 불일치 |
| same | _expiry_cutoff가 15:00/15:15 사용(137–147행) | 15:10와 다름 | 불일치 |
| core/strategy/engine/s6_plugin.py | candidate decision/pair plan을 노출; sequential rank/cancel/fill state evidence 미확인 | ordered candidate state machine 미입증 | 미구현/증거 부족 |
| application/composition/track6_option_contract_source.py | exact symmetric ±12.5 center first; otherwise nearest listed OTM strikes around ±12.5(24–72행) | rank 5/6 ordered fallback not represented | 불일치 |
| resolve_track6/resolver registry | existing path uses representative PUT signal to form PUT+CALL pair; exact invocation/ordering requires runtime trace | pair resolver alone cannot express ordered reservation workflow | 불일치/실행경로 추가 확인 |
| core/analytics/track6.py | active/base vol and portfolio.premium_spent are passthrough mappings(42–44행) | source freshness not enforced here; premium_spent not per-leg option mark | 부분 일치/미구현 |
| tests/strategy/test_strategy6.py | inspected tests cover trailing close proposal and watermark update; no mapped 5/6 sequential, 10m timer, 11:00/15:10, actual mark or cancel-race suite | v0.3 acceptance coverage not shown | 미구현/추적성 부족 |

### 공통 차이
- Pair multi-leg plan → sequential single-leg limit orders.
- pre-fill active state → fill/position-driven state.
- premium_spent/intrinsic proxy → actual per-leg option mark and entry fill.
- 1.5×/2× and 85/88/90% tiers → 2× activation and 10% high-water drawdown.
- 15:00/15:15 → 15:10.
- exact expiry YYYYMMDD (No.1119); no mini options (No.1070).
- previous-day residual/restart must block reset until flat confirmed.
- partial fills, cancel race, stale quote and position mismatch must be explicit.
- S6/S7/S8 aggregate margin/quantity/premium and S6/S7/S8/S9 correlated insurance risk are recorded; S6's fixed quantity must not be scaled.

## 7. 통합 매트릭스의 S6 관련 I01–I16 / U01–U15 / G01–G12 갱신 초안

기존 integrated matrix의 등록부/ID는 삭제하지 않는다. 다음은 v0.5에서 기존 v0.4의 S6 관련 해석을 갱신하는 amendment다.

### I01–I16
| ID | S6 갱신 사항 | 상태 |
|---|---|---|
| I01 | S6 CALL/PUT qty fixed at 1; account premium/margin/max-loss is separately aggregated | 의도 확정, enforcement BLOCKED |
| I02 | S6 uses no futures hedge; keep S5/S4/S3 futures role decisions separate | S6 범위 확정 |
| I03 | actual per-leg lots/fill/qty/mark linked to owner/group; count each account lot once | 구현 검증 필요 |
| I04 | S6 daily + S7 weekly + S8 monthly/overlay + S9 insurance overlap aggregated by expiry/stress/cost | BLOCKED: correlation/payoff model |
| I05 | sequential orders, cancel complete before next; late fill and single-leg exposure preserved | 의도 확정, runtime 미검증 |
| I06 | per-leg actual option mark and entry fill, no intrinsic/premium-spent proxy | 의도 확정, mark/fee evidence needed |
| I07 | same-day expiry, entry cutoff 11:00, force close 15:10, exact YYYYMMDD | policy specified, calendar/broker validation |
| I08 | 15:10 force-close precedes S6 trailing; account emergency override must follow common risk spec | S6 priority specified, account override validation |
| I09 | stale/mismatched IV/quote blocks entry; existing risk stays in reconciliation/exit management | policy specified, age threshold unset |
| I10 | restart restores orders/fills/positions/high-water/config hash before evaluation | required, persistence unverified |
| I11 | S6 has no futures conversion; S5 role question remains S5-only | S6 N/A |
| I12 | S6 is not a futures spread | S6 N/A |
| I13 | S6 insurance lots remain separately owned; not S4 basecamp/delta inventory | ownership integration validation |
| I14 | no S6 PUT-only add-on; separate from S8 add-on resolver | S6 N/A |
| I15 | one entry per day; prior orders/fills/positions reconciled before new daily lifecycle/reset | policy specified, runtime unverified |
| I16 | config version/hash covers 1.3, 11:00, ranks, timeout split, qty, 2×, 10%, 15:10, freshness/pricing | schema intent confirmed; values/enforcement partly provisional |

### U01–U15
| ID | Existing register item | S6 update classification |
|---|---|---|
| U01 | S1 payoff/3-leg | unchanged, S1 only |
| U02 | S2 payoff/stop/trailing | unchanged, S2 only |
| U03 | S3 tradable spread identity | unchanged, S3 only |
| U04 | S4 lots/delta/basecamp | unchanged, S4 only |
| U05 | S5 Futures role/qty/sequence | unchanged, S5 only; No.1151/retired No.1168 retained |
| U06 | S6 pair MTM, partial pair recovery, daily cutoff | **policy specified; validation BLOCKED** — 11:00, one entry, timeout, per-leg trail and 15:10 specified; actual marks/fills/cancel/calendar evidence missing |
| U07 | S7 IV skew/expiry | unchanged, S7 only |
| U08 | S8 add-on/rounding/DTE<=4 | unchanged, S8 only |
| U09 | S9 entry/open/skip window | unchanged, S9 only |
| U10 | account capital/risk values | settings/validation pending; S6 qty fixed, common account values still unverified |
| U11 | common order/partial/cancel/restart persistence | policy specified; runtime/read-model proof BLOCKED |
| U12 | account aggregate exposure/correlation/netting | validation pending; S6/S7/S8 aggregate margin/qty and S6/S7/S8/S9 correlation |
| U13 | authoritative P&L/fee/multiplier | validation pending; actual per-leg marks/fills/fees needed |
| U14 | exact expiry/session service | partly specified; YYYYMMDD, same-day expiry, 11:00/15:10; calendar/broker verification BLOCKED |
| U15 | Shrimp Resume Context access/update | UNAVAILABLE unless actual tool evidence exists; this task does not claim update |

### G01–G12
| Gate | S6 state in this draft | Remaining evidence |
|---|---|---|
| G01 purpose/payoff | intent specified | quantitative payoff/stress/cost validation |
| G02 entry/exit | formulas/times specified; first_rank/timeout_split/limit details provisional | boundary and priority scenarios |
| G03 contract/expiry/qty | qty/rank offsets specified | listed exact YYYYMMDD contracts |
| G04 partial/cancel | state flow specified | actual order/fill/cancel tests |
| G05 hedge | no futures/additional leg | resolver must not add unintended leg |
| G06 trailing/time | per-leg 2×/10%, 15:10 | actual marks/fills/close evidence |
| G07 session/expiry | same-day, 11:00, 15:10 | official calendar/broker cutoff |
| G08 risk | fixed qty; common account cap remains | config + runtime enforcement |
| G09 recovery | reconcile-before-reset specified | durable restart evidence |
| G10 traceability | F01–F29 mapped below | exact test IDs/evidence after approval |
| G11 assumptions | first_rank, timeout_split, price/freshness remain explicit | REAL_VTS validation |
| G12 validation vs approval | process separation PASS only | v0.3 remains unapproved |

## 8. Scenario test plan — planning only, NOT_RUN

| Case ID | Class | Setup | Expected result | Evidence |
|---|---|---|---|---|
| TP-S6-V03-N01 | normal | valid session, IV ratio >1.3, rank-5 quote valid | one order only; no active before fill | IV/source times, config hash, order plan |
| TP-S6-V03-B01 | boundary | ratio exactly 1.3 | eligible only if all other gates pass | canonical IV inputs |
| TP-S6-V03-B02 | boundary | ratio just below 1.3 | no order | input and reason |
| TP-S6-V03-B03 | boundary | signal at 11:00 and just after | config-defined boundary; after cutoff no new entry | official KST timestamp |
| TP-S6-V03-B04 | boundary | before official session open | no order | calendar/source |
| TP-S6-V03-N02 | sequential rank | rank 5 has no executable contract/quote, rank 6 valid | only one candidate order at a time | preflight/cancel evidence |
| TP-S6-V03-E01 | timeout | first order has zero fills at 10 min | cancel, reconcile, close entry for day; no retry | order/cancel/fill timestamps |
| TP-S6-V03-E02 | cancel race | fill arrives during cancel pending | apply late fill; no next candidate until reconciled | event sequence/execution IDs |
| TP-S6-V03-N03 | first leg | CALL fills before PUT | store CALL fill; start opposite timer; not pair-active | fill and position |
| TP-S6-V03-N04 | pair complete | PUT fills inside permitted window | pair-active only after both reconciled | both fills and positions |
| TP-S6-V03-E03 | opposite no-fill | opposite order not filled in 10 min | cancel and retain actual single-leg position | cancel race and position snapshot |
| TP-S6-V03-E04 | partial fill | any leg partial | filled/leaves separate; no assumed full qty | fill reports/lots |
| TP-S6-V03-B05 | trailing arm | per-leg mark equals entry fill ×2 | arm that leg, not immediate close | fill/mark/watermark |
| TP-S6-V03-B06 | trailing boundary | mark just above and exactly 90% of high | hold above; close at/below 90% | per-leg high-water |
| TP-S6-V03-N05 | independent trail | CALL reaches 2×, PUT does not | CALL armed, PUT unarmed | per-leg state |
| TP-S6-V03-E05 | stale mark | open lot with stale/missing mark | no fabricated P&L/trailing; reconciliation state | source/receive times |
| TP-S6-V03-B07 | 15:10 | before/at/after 15:10 | at/after cutoff close all actual residual S6 legs | official clock/close batch |
| TP-S6-V03-E06 | partial close | one close leg filled, other remains | EXIT_PENDING until all flat | leg fills/positions |
| TP-S6-V03-R01 | restart | single leg/pair/pending order/trailing watermark open | reconcile and restore before evaluation | before/after state |
| TP-S6-V03-E07 | bad contract | wrong expiry/type/strike/multiplier or unlisted | BLOCKED, no order | Option Master result |
| TP-S6-V03-E08 | missing config | first_rank/timeout_split/quote source/freshness null | BLOCKED, no default | config validation |
| TP-S6-V03-X01 | account interaction | S6/S7/S8/S9 insurance overlap | aggregate premium/margin/qty/correlated stress; no double credit | account risk snapshot |
| TP-S6-V03-X02 | S1 overlap | S1 broad strangle/short exposure and S6 pair coexist | separate owner/group; each actual lot counted once | provenance/risk snapshot |
| TP-S6-V03-X03 | config reload | config changes with open S6 lot | old lot keeps original config version | config hash/lot lineage |

No tests were run in this task. The above are test plans, not test results.

## 9. 설정·외부 증거 blockers

- first_rank: 5 or 6, selected after REAL_VTS liquidity/coverage validation.
- timeout_split: per_order or shared_elapsed; compare without silently choosing.
- rank fallback trigger: distinguish preflight-unavailable from submitted-order no-fill. S6 no-fill after 10 minutes ends entry for day.
- quote_mark_source, quote_max_age_seconds, max_spread_ticks, limit basis and tick rounding.
- official session calendar and broker behavior for 15:10 close.
- actual option mark/fill/fee/multiplier, partial fill/restart and position reconciliation.
- account capital/premium/margin/max-loss config and runtime enforcement.
- independent REAL_VTS tuning and validation windows with config hash/version.

## 10. Safety and version status

- v0.2 is preserved unchanged.
- v0.3 remains **draft / unverified / unapproved**.
- No code or test file was changed; no tests run; no Git stage/commit/push; no KIS Live orders.
- This static code-intent table is not implementation authorization.
- Decision Log items are not deleted or rewritten; I/U/G IDs remain intact and changes are a versioned proposal.


## 11. 명시적 분류 등록부 — v0.2 U/G/I 보존 및 S6 갱신

**분류 의미:** “확정 해결”은 사용자 의도/정책 질문이 정의되었다는 뜻이며 코드 구현이나 실거래 검증 PASS를 뜻하지 않는다. “설정 이관”은 사용자에게 다시 묻지 않고 versioned config 또는 REAL_VTS/외부 증거로 검증할 항목이다. “사용자 확인 필요”는 이 S6 문서가 다른 전략의 미해결 정책을 대신 결정하지 않는다는 뜻이다.

### I01–I16: S6 관련 interaction items
| ID | 분류 | §1 근거 | 이유 / 남은 증거 |
|---|---|---|---|
| I01 | 설정 이관 | §1.5–1.6 | S6 수량은 고정; 계좌 premium/margin/max-loss 값과 runtime reserve는 별도 config/evidence |
| I02 | 확정 해결 | §1.1, §1.6 | S6에 Futures hedge 없음; 다른 전략의 Futures 역할 결정은 별도 |
| I03 | 설정 이관 | §1.6 | per-leg ownership/provenance를 account read model에 연결하는 구현 증거 필요 |
| I04 | 설정 이관 | §1.6 | S6/S7/S8/S9 correlated insurance payoff/stress aggregation 검증 필요 |
| I05 | 확정 해결 | §1.3–1.4, §1.6 | sequential orders, per-leg fills, cancel-race reconciliation; runtime은 미검증 |
| I06 | 확정 해결 | §1.5–1.6 | actual option mark/fill 기준; 데이터·원장 연결은 미검증 |
| I07 | 확정 해결 | §1.2, §1.5 | 11:00/15:10/당일 만기/정확한 expiry policy 정의; calendar/broker 확인은 미검증 |
| I08 | 확정 해결 | §1.5–1.6 | S6 15:10 close가 S6 trailing보다 우선; 공통 계좌 emergency override는 별도 승인 범위 |
| I09 | 확정 해결 | §1.2, §1.6 | stale/mismatch fail-closed policy 정의; quote age 숫자는 설정 이관 |
| I10 | 확정 해결 | §1.6 | restart reconcile/no reset until flat 정책 정의; persistence 검증 미완료 |
| I11 | 확정 해결 | §1.1 | S6 futures conversion 없음; S5 관련 미결은 유지 |
| I12 | 확정 해결 | §1.1 | S6 futures spread 아님; S3 관련 미결은 유지 |
| I13 | 설정 이관 | §1.6 | S6 lot ownership과 S4 delta/basecamp inventory 분리 증거 필요 |
| I14 | 확정 해결 | §1.1, §1.3 | S6에 PUT-only add-on 없음; S8 add-on resolver와 분리 |
| I15 | 확정 해결 | §1.2, §1.4, §1.6 | max one entry/day, old orders/positions reconciliation before reset; runtime 미검증 |
| I16 | 설정 이관 | §1.2–1.6 | version/hash, first_rank, timeout_split, price/freshness and account caps need validation |

### U01–U15: v0.2 unresolved register (all IDs retained)
| ID | 분류 | §1 근거 | v0.3 treatment |
|---|---|---|---|
| U01 | 사용자 확인 필요 | 해당 없음(S1 전용) | S1 payoff/3-leg decision untouched |
| U02 | 사용자 확인 필요 | 해당 없음(S2 전용) | S2 payoff/stop decision untouched |
| U03 | 사용자 확인 필요 | 해당 없음(S3 전용) | S3 tradable spread identity untouched |
| U04 | 사용자 확인 필요 | 해당 없음(S4 전용) | S4 eligible lots/delta/basecamp untouched |
| U05 | 사용자 확인 필요 | 해당 없음(S5 전용) | S5 Futures role/quantity/sequence untouched; No.1151 and retired No.1168 remain |
| U06 | 확정 해결 | §1.2–1.6 | S6 entry window/count, order timeout, per-leg MTM/trailing and 15:10 intent specified; runtime/data validation still BLOCKED |
| U07 | 사용자 확인 필요 | 해당 없음(S7 전용) | S7 skew/expiry decisions untouched |
| U08 | 사용자 확인 필요 | 해당 없음(S8 전용) | S8 add-on/rounding/DTE≤4 decisions untouched |
| U09 | 사용자 확인 필요 | 해당 없음(S9 전용) | S9 entry/open/skip-window decisions untouched |
| U10 | 설정 이관 | §1.6 | common account capital/premium/max-loss/margin values and runtime enforcement |
| U11 | 확정 해결 | §1.4, §1.6 | common partial/cancel/restart/flat policy specified; runtime persistence evidence pending |
| U12 | 설정 이관 | §1.6 | account-wide aggregate exposure/correlation/netting model |
| U13 | 설정 이관 | §1.5–1.6 | authoritative marks/fills/multiplier/fees and strategy attribution |
| U14 | 설정 이관 | §1.2, §1.5–1.6 | exact expiry/session policy specified; common calendar and broker boundary evidence |
| U15 | 사용자 확인 필요 | 해당 없음(도구 접근) | Shrimp Resume Context cannot be marked updated without an accessible action/result |

### G01–G12: S6 completeness gate classification
| Gate | 분류 | §1 근거 | Meaning/status |
|---|---|---|---|
| G01 | 설정 이관 | §1.1 | intent defined; quantitative payoff/stress/cost validation remains |
| G02 | 설정 이관 | §1.2–1.5 | core rules specified; first_rank, timeout_split and pricing boundary candidates remain |
| G03 | 설정 이관 | §1.3, §1.5 | rank/qty/expiry policy specified; listed contract/multiplier evidence required |
| G04 | 확정 해결 | §1.4, §1.6 | partial/reject/cancel-race policy specified; runtime tests not run |
| G05 | 확정 해결 | §1.1 | no futures/additional hedge leg in S6 |
| G06 | 확정 해결 | §1.5 | per-leg 2×/10% and 15:10 policy specified; actual mark/close evidence pending |
| G07 | 설정 이관 | §1.2, §1.5 | session/expiry policy defined; official calendar/broker cutoffs must be validated |
| G08 | 설정 이관 | §1.6 | fixed S6 qty; account-wide risk values and enforcement pending |
| G09 | 확정 해결 | §1.6 | reconcile-before-reset and no blind retry specified; persistence evidence pending |
| G10 | 설정 이관 | §1.6 | trace mapping created; exact test/evidence IDs remain NOT_RUN |
| G11 | 설정 이관 | §1.2–1.6 | config/data dependencies explicitly listed; null values block |
| G12 | 확정 해결 | §1.6 | validation is separate from user approval; draft remains unapproved |
