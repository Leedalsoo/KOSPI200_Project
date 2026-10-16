# Strategy 7 — Weekly Option Tail Insurance 상세 명세 v0.3

- 상태: **초안 v0.3 / 미검증 / 미승인 / 구현 기준 사용 금지**
- 작성일: 2026-10-13
- 기준 브랜치/HEAD: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- v0.2는 역사적 참고 자료로 보존하며 덮어쓰지 않는다.
- 이 명세의 §1은 사용자가 직접 확정한 의도로서 v0.2 및 과거 분석보다 우선한다.
- null/PROVISIONAL/검증되지 않은 필수 설정 또는 신뢰할 수 없는 데이터가 있으면 신규 주문은 fail-closed로 차단한다.

## 1. 사용자 확정 의도

### 1.1 S6·S7·S8 공통 주문·청산 구조
1. CALL·PUT을 동시 제출하는 멀티레그 묶음 주문이 아니다. 조건을 만족한 단일 레그를 한 번에 하나씩 지정가 예약주문한다.
2. 옵션 마스터로 계약을 확인한 뒤 ATM 기준 5번째 또는 6번째 행사가 후보를 사용한다. 2.5pt 간격 기준 5번째=ATM±12.5pt, 6번째=ATM±15pt. 실제 strike, expiry, symbol, product type, multiplier는 마스터로 확인하며 추측·하드코딩하지 않는다.
3. 5번째/6번째는 순차 시도한다. 동시에 열어두지 않는다. 다음 후보로 넘어가기 전에 이전 주문의 취소 완료 및 누적 체결량 대사를 확인한다. 취소 중 체결이 발생하면 다음 주문을 제출하지 않고 체결/포지션을 대사한다.
4. 한 레그가 먼저 체결되면 편매수 상태로 기록하고 반대 레그 주문을 최대 10분 유지한다. 반대 레그의 실제 체결 확인 전에는 양매수 완성 상태로 승격하지 않는다.
5. CALL 1계약, PUT 1계약 고정이다. 수량 확대 로직은 폐기 대상이다.
6. 각 레그는 실제 매수가 기준으로 독립 청산한다. 프리미엄이 매수가의 2배 이상에 도달한 후 해당 레그 고점을 추적하고, 고점 대비 10% 하락 시 해당 레그 잔여 수량을 청산한다. 2배 도달 자체는 익절 청산이 아니다.
7. 주문 ACK는 체결이 아니며 취소 요청은 취소 완료가 아니다. partial fill, cancel-race, late fill, 재시작 후 주문·체결·포지션 대사를 지원한다. 실제 flat 확인 전 상태 초기화 및 다음 동일 그룹 진입을 금지한다.
8. 관련 시간·비율·행사가 순위·timeout은 versioned config로 관리한다. REAL_VTS 튜닝 기간과 별도 검증 기간을 분리하고 각 실행에 config version/hash를 기록한다.
9. quote/contract identity/expiry가 stale·누락·불일치하거나 예산/설정이 미검증이면 신규 진입을 차단한다. 보유 포지션의 관리 상태를 임의로 지우지 않는다.

### 1.2 Strategy 7 개별 확정 규칙
1. 주물은 **월요일 만기 위클리와 목요일 만기 위클리 모두**다. 두 expiry 그룹은 독립적인 group/lot/order/high-water 상태를 가지며 동시 보유 가능하다. 목표 수량은 그룹별 CALL 1 + PUT 1, 최대 두 그룹 합계 CALL 2 + PUT 2다. 실제 수량은 체결 원장 기준이다.
2. 각 그룹의 시작일과 만기는 상장/만기 Option Master 및 공식 거래일 달력으로 확인한다. 휴일 단축 주간도 포함한다. 요일 계산이나 calendar.is_new_week_start만으로 추정·하드코딩하지 않는다.
3. 그룹 시작일에도 변동성 조건을 적용한다. 유효한 active volatility / base volatility 비율이 1.3 이상일 때만 진입 후보가 된다. base/active 산식, 출처, observation window, timestamp 및 freshness가 검증되지 않으면 진입 차단한다.
4. 각 그룹 시작일 장 시작부터 **15:00까지** 변동성 조건을 재평가하며 체결될 때까지 반복 시도한다. 하루 1회 제한은 아니다. 미체결 주문은 10분 timeout → 취소 요청 → 취소 terminal 확인 및 fill 대사 → 다음 순차 후보/재시도 순으로 처리한다. 편매수 후 반대 레그 timeout 및 15:00 경계에 관한 모호점은 U16/U17에 기록한다.
5. 각 레그 프리미엄이 실제 매수가의 **50% 이하**면 해당 레그 잔여 수량을 손절한다. 기존 “고점 대비 20% 하락”은 폐기 대상이다.
6. 각 레그는 2배 활성화 후 고점 대비 10% trailing도 적용한다. 트리거 우선순위는 만기 강제 종료 > 매수가 대비 50% 손절 > trailing으로 정의한다. 동시 실행/취소 레이스는 실제 주문·체결 원장으로 대사한다.
7. 각 그룹 **만기일 15:10에 무조건 청산**한다. 과거 15:00은 정정한다. 공식 달력·브로커 cut-off 검증 전에는 runtime 통과로 보지 않는다.
8. 진입 조건에 IV skew 지표가 명시되지 않았으므로 “skew”를 이름에서 제외하는 후보를 제안한다. 실제 strategy_id, filename, alias/registry, telemetry, UI label, saved state, tests, historical position identity는 바꾸지 않는다. 이름 변경은 별도 승인 대상이다.

## 2. F01–F29 재분류표

분류 의미: “확정 의도”는 사용자 정책이 명확해졌다는 뜻이며 코드 검증 PASS가 아니다. “설정/검증 이관”은 설정·REAL_VTS·공식 소스 증거가 필요하다는 뜻이다. “사용자 확인 필요”는 새 모호점만 뜻한다.

| ID | 항목 | 현재 사실/갱신 기준 | 분류 |
|---|---|---|---|
| F01 | 목적·경제적 역할 | 주간 옵션 tail insurance, CALL+PUT 매수; IV skew 진입 조건은 확정되지 않음 | 확정 의도 |
| F02 | 시장·상품 | KOSPI200 옵션, Mini 제외, 정확한 identity/expiry/multiplier | 설정/검증 이관 |
| F03 | 주간 lifecycle | 월요일·목요일 expiry 그룹 각각 독립, 휴일 단축 주간 포함 | 확정 의도 |
| F04 | 기준가·시간 | base/active volatility 및 quote는 source/as-of/freshness 필요 | 설정/검증 이관 |
| F05 | 진입 신호 | 시작일 active/base volatility ≥1.3 | 확정 의도 |
| F06 | 반복 진입 | 시작일부터 15:00까지 반복 시도, 동일 그룹 중복 방지 | 확정 의도 |
| F07 | pending/cancel/reprice | 주문당 10분, cancel terminal + fills 확인 후 다음 시도 | 확정 의도 |
| F08 | 계약 선택 | Option Master로 월/목 만기, symbol, product, expiry, multiplier 확인 | 설정/검증 이관 |
| F09 | strike/tick/quote | 5번째·6번째 순차 후보, 실제 행사가·tick·유동성 확인 | 설정/검증 이관 |
| F10 | volatility/skew | IV skew는 entry trigger로 확정되지 않음; 이름에서 제거 후보 | 확정 의도 |
| F11 | 주간 달력 | 공식 달력과 각 계약의 실제 만기; is_expiry_day와 state expiry 대조 | 설정/검증 이관 |
| F12 | 수량·자본·비용 | 각 그룹 CALL/PUT 1계약 고정; 계좌 예산 별도 검증 | 확정 의도 |
| F13 | 주문 가격/재주문 | 단일 레그 지정가, 10분 timeout, cancel-confirm 순차 재시도 | 확정 의도 |
| F14 | 사전 위험검사 | contract/quote/volatility/budget/account risk 모두 확인 후 주문 | 설정/검증 이관 |
| F15 | partial/reject/unknown | actual per-leg fill로 상태 전이; cancel-race/late fill 대사 | 확정 의도 |
| F16 | hedge/extra leg | S7에는 Futures/추가 hedge leg 없음 | 확정 의도 |
| F17 | 보유/노출 | 월·목 그룹과 레그별 lots/qty/high-water 분리 | 확정 의도 |
| F18 | 손절 | 매수가 대비 50% 하락 시 레그별 손절 | 확정 의도 |
| F19 | trailing/P&L | 실제 매수가 2배 도달 후 해당 레그 고점 대비 10% 하락 | 확정 의도 |
| F20 | 만기/시간 | YYYYMMDD 정규화, 각 만기일 15:10 강제청산 | 확정 의도 |
| F21 | 청산 수량/방향 | 실제 잔여 lot/qty별 청산, flat 대사 전 완료 처리 금지 | 확정 의도 |
| F22 | P&L/비용 | actual fill, multiplier, fees/slippage 필요 | 설정/검증 이관 |
| F23 | 트리거 우선순위 | expiry > 50% stop > trailing | 확정 의도 |
| F24 | lifecycle/provenance | run/group/leg/order/execution/position/config hash 연결 | 설정/검증 이관 |
| F25 | restart/duplicate/timeout | restart 시 orders/fills/lots/high-water/config 복원 후 재개 | 확정 의도 |
| F26 | 계좌 전체 위험 | 두 S7 그룹과 S1/S6/S8/S9 premium/margin/correlated stress 합산 | 설정/검증 이관 |
| F27 | data error/unavailable | stale/missing/mismatched source는 신규 진입 차단, 값 추정 금지 | 확정 의도 |
| F28 | editable settings | versioned config; null/PROVISIONAL이면 신규 주문 차단 | 확정 의도 |
| F29 | tests/acceptance | 모든 F행에 시나리오/증거 연결, 미실행은 NOT_RUN | 설정/검증 이관 |

집계: **확정 의도 20 / 설정·검증 이관 9 / 사용자 확인 필요 0**. 새 모호점은 S7-U16~U20에 별도 기록했다.

## 3. 상태 전이표

| 현재 상태 | 조건/입력 | 작업/다음 상태 | 실패·복구 |
|---|---|---|---|
| WAITING_FOR_GROUP | Option Master에서 월/목 그룹 시작일 확인; 이전 동일 그룹 주문/포지션이 reconciled flat | CONTRACT_VALIDATION | 잔존 lot/order면 신규 동일 그룹 진입 차단 |
| CONTRACT_VALIDATION | 정확한 expiry YYYYMMDD, product, option type, strike, symbol, multiplier | VOLATILITY_PREFLIGHT | 필수 필드 불일치면 BLOCKED |
| VOLATILITY_PREFLIGHT | valid active/base volatility ratio ≥1.3, fresh and same as-of | FIRST_RANK_ORDER_WORKING | source/freshness/ratio 미검증이면 신규 주문 차단 |
| RANK_n_ORDER_WORKING | 단일 레그 지정가 주문 제출 | ACK는 order state만; actual fill에서만 LEG_PARTIAL/LEG_FILLED | 10분 timeout 시 CANCEL_PENDING |
| CANCEL_PENDING | 취소 요청 전송 | terminal cancel 확인과 cumulative fill 대사 후 다음 후보/재시도 | 취소 중 체결이면 다음 주문 금지, actual position reconcile |
| LEG_PARTIAL/LEG_FILLED | 첫 레그 실제 체결량 >0 | SECOND_LEG_WORKING | 양쪽 fill 전에는 PAIR_ACTIVE 아님 |
| SECOND_LEG_WORKING | 반대쪽 fill/partial/timeout | 양쪽 체결 확인 후 PAIR_ACTIVE; timeout은 U16 정책 | 미체결 잔여 상태를 유지, 추정으로 완성 처리 금지 |
| PAIR_ACTIVE | 양쪽 actual fills 및 lots 대사 | PER_LEG_MONITORING | fill/mark/qty provenance 누락 시 BLOCKED |
| PER_LEG_MONITORING | 각 레그 fresh mark와 actual entry fill | 50% stop / 2× activation 후 10% trailing | mark unavailable이면 계산 불가로 표시; 추정 mark 금지 |
| EXPIRY_EXIT_PENDING | own expiry date 15:10 | 잔여 레그별 close order | ACK만으로 flat 처리 금지; reject/partial/cancel-race 재대사 |
| FLAT_RECONCILIATION | orders/fills/positions 대조 | 모든 lot flat 확인 후 CLOSED | residual qty/unknown order이면 상태 유지 |
| RECOVERY_RECONCILIATION | restart/reconnect | pending orders, fills, lots, expiry, high-water, config hash 복원 | authoritative snapshot 없으면 신규 주문 금지 |

### 3.1 순차 행사가/timeout 경계
- 5번째/6번째 주문은 동시에 열지 않는다. 설정 first_rank 순서로 1개씩 제출한다.
- 10분 timeout 후에는 cancel terminal state 및 fill 대사 전 다음 주문 금지.
- first_rank와 timeout_split(후보별 10분 vs 전체 합산)은 사용자에게 재질문하지 않고 설정 후보로 두며 REAL_VTS 검증 후 확정한다.
- 첫 레그 체결 후 반대쪽 10분 timeout 동작은 U16; 15:00 cutoff보다 늦게 timeout되는 주문 처리 방식은 U17로 남긴다.
- 시작일 15:00 이후 새 주문/재주문 금지. U17 해결 전에는 cutoff 경계의 미해결 주문을 임의로 계속하지 않고 cancel/reconcile 상태로 fail-closed한다.

### 3.2 레그별 stop/trailing
각 레그 i에 대해 actual entry fill E_i, fresh mark M_i, high-water H_i를 독립 추적한다.
- 손절: M_i ≤ E_i × 0.50 → 해당 레그 잔여 수량 청산.
- trailing 활성화: M_i ≥ E_i × 2.00 도달 시 high-water 추적 시작.
- trailing 청산: 활성화 후 M_i ≤ H_i × 0.90 → 해당 레그 잔여 수량 청산.
- 만기 종료: 해당 expiry group 만기일 15:10에 모든 잔여 레그 청산.
- 우선순위: expiry > stop > trailing. actual fills와 position ledger가 우선하며 close ACK만으로 완료 판정하지 않는다.

## 4. 설정 스키마 초안 (PROVISIONAL)

    strategy7:
      status: PROVISIONAL
      expiry_groups: [monday_weekly, thursday_weekly]
      expiry_source: option_master_required
      calendar_source: official_trading_calendar_required
      vol_ratio_min: 1.3
      volatility_base_source: null
      volatility_active_source: null
      volatility_freshness_seconds: null
      entry_end_time: "15:00"
      strike_ranks: [5, 6]
      first_rank: null
      order_timeout_minutes: 10
      timeout_split: null
      qty_call: 1
      qty_put: 1
      stop_loss_enabled: true
      stop_loss_ratio: 0.50
      trailing_activate_multiple: 2.0
      trailing_drawdown: 0.10
      force_close_time: "15:10"
      option_mark_freshness_seconds: null
      limit_price_rule: null
      max_strategy_premium: null
      max_strategy_loss: null
      max_account_loss: null
      config_version: required
      config_hash: required

Any mandatory null/PROVISIONAL/unverified value blocks new orders. This schema does not modify runtime config.

## 5. 코드-의도 차이표 (read-only inspection)

| # | 코드 경로 | 확인된 현행 동작/증거 | v0.3 의도와 차이 | 분류 |
|---|---|---|---|---|
| D01 | core/strategy/track7_volatility_skew_weekly_insurance.py | entry gate uses calendar.is_new_week_start; no 1.3× base volatility comparison in inspected conditions | Monday/Thursday Option Master start dates plus vol ratio | 불일치 |
| D02 | same strategy | insurance_active is set while generating entry proposal before actual fills | active only after per-leg actual fills and reconciliation | 불일치 |
| D03 | strategy + resolve_track7/MultiLegBridge | PUT BUY proposal becomes equal-quantity PUT+CALL MultiLegExecutionPlan | sequential single-leg orders and rank candidates | 불일치 |
| D04 | strategy | TRAILING_DRAWDOWN=0.20; pair mark sum × multiplier | per-leg 50% stop and 2×/10% trailing | 불일치 |
| D05 | strategy | pair value does not multiply by configured qty when qty>1; peak is pair value, not net profit | fixed qty one per leg; actual per-leg cost basis | 불일치/잔재 |
| D06 | strategy | expiry compared to analytics ISO date and closes at 15:00 | canonical YYYYMMDD and expiry-day 15:10 close | 불일치 |
| D07 | strategy | calendar.is_expiry_day feature requested but not used for own expiry close | authoritative own expiry group and official calendar cross-check | 불일치 |
| D08 | application/composition/track7_option_contract_source.py | selects nearest strike to reference±12.5 from listed candidates | resolve ranks 5/6 and sequential liquidity fallback | 부분/미구현 |
| D09 | same source | expiry candidate string strips hyphens but exact product class and source provenance need proof | exact canonical expiry, weekly product identity, no Mini | 부분/증거 부족 |
| D10 | resolve_track7/plan bridge | entry/close are group pair plans | runtime strategy remains unchanged pending approval | 불일치 |
| D11 | core/analytics/track7.py + source | fresh same-snapshot mark/base/active volatility contract not proven | authoritative timestamp/freshness and reproducible vol ratio | 증거 부족 |
| D12 | tests/strategy/test_strategy7.py | tests cover pair plan and flat confirmation; no complete v0.3 case mapping | add v0.3 test plan IDs and evidence | 테스트 매핑 부족 |
| D13 | strategy state | single state for one expiry pair; two independent concurrent groups not evidenced | per-group/expiry/leg lots and watermarks | 증거 부족 |
| D14 | strategy_id/name/registry/UI/test references | existing identity includes volatility_skew | propose rename only; preserve old identity as alias | 변경 금지/영향 조사 필요 |

### 5.1 이름 변경 후보 (제안만, 실제 변경 없음)
- 표시명 후보: Weekly Option Tail Insurance
- 파일명 후보: track7_weekly_option_tail_insurance.py
- strategy_id 후보: track7_weekly_option_tail_insurance
- 변경 영향 조사 범위: registry/factory, resolver/plugin manifest, Control Tower UI labels, telemetry, persisted state/group provenance, test imports, docs, aliases and historical positions. 기존 ID를 호환 alias로 유지해야 한다. 별도 사용자 승인 전에는 이름/파일/ID를 바꾸지 않는다.

## 6. 시나리오 테스트 계획 — 전부 NOT_RUN

| Test ID | 시나리오 | 예상 결과 | 증거 | 상태 |
|---|---|---|---|---|
| S7-V03-N01 | 월요일 그룹 시작, vol ratio=1.30, 마스터·호가 정상 | 모든 data/risk gate 통과 후에만 첫 단일 레그 주문 | Option Master, active/base, timestamps, config hash | NOT_RUN |
| S7-V03-N02 | 목요일 그룹 시작 시 월요일 그룹 잔존 | 별도 group/lot/expiry/high-water, 덮어쓰기 금지 | group/lot/order/position snapshots | NOT_RUN |
| S7-V03-N03 | 5번째 행사가 정상 | rank 5 단일 주문만 제출 | order timeline | NOT_RUN |
| S7-V03-B01 | ratio 1.2999/1.3000/1.3001 | threshold 이상만 통과 | source values, decision trace | NOT_RUN |
| S7-V03-B02 | rank 5 무효/유동성 부족, rank 6 가능 | cancel+fill reconciliation 후 rank 6 | quote, cancel ACK, fills | NOT_RUN |
| S7-V03-B03 | timeout 9:59/10:00/10:01, cancel 중 fill | 다음 주문 전 terminal state 및 fill 대사 | event sequence/order IDs | NOT_RUN |
| S7-V03-B04 | 14:59:59/15:00:00/15:00:01 진입 마감 | 15:00 이후 신규 주문 금지; timeout crossing은 U17 | KST clock/config/order state | BLOCKED U17 |
| S7-V03-E01 | 첫 레그 체결, 반대 레그 10분 미체결 | 편매수 lot 유지; 재시도/보유 정책은 U16까지 BLOCKED | fills/cancel/residual qty | BLOCKED U16 |
| S7-V03-E02 | mark 49.99%/50%/50.01% entry | 해당 레그만 50% 이하 손절 | fill basis/mark/close report | NOT_RUN |
| S7-V03-E03 | 1.99×/2×/2.01× entry | 2× 이상에서 high-water 활성화 | mark sequence/state | NOT_RUN |
| S7-V03-E04 | high-water 하락 9.99%/10%/10.01% | 10% 이상 하락에서 해당 레그 청산 | watermark/marks | NOT_RUN |
| S7-V03-E05 | 한 레그 손절, 다른 레그 잔존 | 해당 레그 잔여 수량만 청산; 다른 레그 별도 관리 | per-leg positions/fills | NOT_RUN |
| S7-V03-E06 | 월·목 그룹 동시 보유 | 그룹/레그 상태 독립; account risk 합산 | group IDs/risk snapshot | BLOCKED account risk |
| S7-V03-E07 | expiry YYYYMMDD vs YYYY-MM-DD | canonical expiry identity 정확히 일치 | raw/canonical expiry | NOT_RUN |
| S7-V03-E08 | 휴일 단축 주간 | 공식 달력+Option Master 사용, 요일 추정 금지 | calendar/master snapshot | BLOCKED source |
| S7-V03-E09 | 만기일 15:09:59/15:10:00/15:10:01 | 15:10 청산 시작, flat은 fill/position 확인 후 | clock/orders/fills/flat snapshot | NOT_RUN |
| S7-V03-R01 | 재시작 시 pending order/open lot/high-water | 두 그룹을 원장 기준 복원; blind reset 금지 | persisted state + ledger | NOT_RUN |
| S7-V03-R02 | stale/missing base vol, active vol 또는 mark | 신규 진입 BLOCKED; 0/synthetic 대체 금지 | timestamps/BLOCKED reason | BLOCKED freshness |
| S7-V03-R03 | partial close/reject/cancel-race/late fill | actual residual qty로 재대사 후 진행 | order/fill/position timeline | NOT_RUN |
| S7-V03-X01 | S1/S6/S7/S8/S9 tail exposure overlap | premium/margin/correlated stress 합산, 이중 보호 credit 금지 | account risk by group/expiry | BLOCKED |
| S7-V03-X02 | 두 S7 그룹과 S6/S8/S9 예산 경쟁 | cap unset/exceeded이면 신규 주문 차단; 수량 확대 금지 | config/reserve/risk decision | BLOCKED |

## 7. I/U/G 레지스터

분류 의미: 확정 해결은 정책/의도 정의가 완료됐다는 뜻이며 코드 검증 PASS가 아니다. 설정 이관은 config/REAL_VTS/source evidence 필요. 사용자 확인 필요는 다른 전략 정책을 S7이 대신 결정하지 않거나 새로 발견한 모호점이다.

### I01–I16 (기존 ID 모두 보존)
| ID | 분류 | S7 관련 처리 |
|---|---|---|
| I01 | 설정 이관 | 계좌 총자본/premium/max-loss/margin 및 두 S7 그룹+S6/S8/S9 atomic reserve |
| I02 | 확정 해결 | S7 Futures hedge 없음 |
| I03 | 설정 이관 | group/leg ownership, actual fills, position provenance |
| I04 | 설정 이관 | 월·목 그룹과 S6/S8/S9 tail correlation/premium aggregation |
| I05 | 확정 해결 | per-leg sequential/cancel-race 정책 정의; runtime evidence pending |
| I06 | 확정 해결 | actual fill/mark per leg 정의; ledger evidence pending |
| I07 | 확정 해결 | own expiry와 15:10 의도 정의; calendar/broker proof pending |
| I08 | 확정 해결 | expiry > stop > trailing 우선순위 |
| I09 | 확정 해결 | stale/unavailable fail-closed; threshold/source는 설정 |
| I10 | 확정 해결 | flat 전 reset 금지; two-group durable restore 미검증 |
| I11 | 확정 해결 | S7 Futures conversion 없음 |
| I12 | 확정 해결 | S7 Futures spread 아님 |
| I13 | 설정 이관 | S7 lots를 S4/S1 holdings와 분리 |
| I14 | 확정 해결 | S7 PUT-only add-on 없음 |
| I15 | 확정 해결 | 월·목 독립 lifecycle; duplicate prevention evidence pending |
| I16 | 설정 이관 | config hash, first_rank, timeout_split, volatility source, pricing/risk caps |

### U01–U15 (기존 ID 모두 보존)
| ID | 분류 | S7 처리 |
|---|---|---|
| U01 | 사용자 확인 필요 | S1 전용, 변경 없음 |
| U02 | 사용자 확인 필요 | S2 전용, 변경 없음 |
| U03 | 사용자 확인 필요 | S3 전용, 변경 없음 |
| U04 | 사용자 확인 필요 | S4 전용, 변경 없음 |
| U05 | 사용자 확인 필요 | S5 전용; No.1151/폐기 No.1168 변경 없음 |
| U06 | 확정 해결 | S6 의도 정의됨; runtime 검증은 별도 |
| U07 | 사용자 확인 필요 | 과거 S7 쟁점은 §1로 대체하되 기존 ID 보존; 신규 쟁점은 S7-U16+ |
| U08 | 사용자 확인 필요 | S8 전용, 변경 없음 |
| U09 | 사용자 확인 필요 | S9 전용, 변경 없음 |
| U10 | 설정 이관 | 공통 계좌 위험값/runtime enforcement |
| U11 | 확정 해결 | partial/cancel/restart/flat 공통 정책 정의; 구현 증거 pending |
| U12 | 설정 이관 | 계좌 전체 exposure/correlation/netting |
| U13 | 설정 이관 | authoritative marks/fills/multiplier/fees |
| U14 | 설정 이관 | expiry/session 의도 정의; official calendar/master/broker evidence |
| U15 | 사용자 확인 필요 | Shrimp Resume Context는 도구 결과 없이는 갱신 주장 금지 |

### 신규 S7 미결 U16–U20
| ID | 미결 사항 | 안전한 임시 동작 | 해결 증거 |
|---|---|---|---|
| S7-U16 | 첫 레그 체결 후 반대 레그가 10분 동안 미체결이면 cancel 확인 뒤 15:00까지 재시도할지, 편매수를 유지할지 | 실제 편매수 lot 유지, 양매수로 가정 금지, 무조건 reset 금지 | 명시 정책/승인된 상태 전이 |
| S7-U17 | 15:00 직전 제출한 주문의 10분 timeout이 15:00 이후라면 cutoff 때 취소할지 자연 timeout까지 둘지 | 15:00 이후 신규 주문 금지; pending 상태 대사 및 fail-closed | 명시 정책과 경계 시나리오 |
| S7-U18 | base/active volatility 산식·window·source·freshness 정의 | 지표가 없거나 stale/mismatch면 신규 주문 차단 | authoritative feature definition/source |
| S7-U19 | 두 주간 그룹과 S1/S6/S8/S9 계좌 위험 통합 정책 | aggregate caps unset/미검증이면 신규 주문 차단 | 공통 risk config 및 runtime evidence |
| S7-U20 | 제안된 표시명/filename/strategy_id 변경과 호환 alias 범위 | 현재 ID 보존, 실제 rename 금지 | 전체 참조 영향표와 별도 승인 |

### G01–G12
| Gate | 분류 | S7 증거 상태 |
|---|---|---|
| G01 | 설정 이관 | payoff/stress/cost profile, two-expiry overlap 검증 필요 |
| G02 | 설정 이관 | ratio/timeout/rank/cutoff 경계 및 U16/U17 |
| G03 | 설정 이관 | Option Master expiry/strike/product/multiplier |
| G04 | 확정 해결 | per-leg cancel/partial policy 정의; tests NOT_RUN |
| G05 | 확정 해결 | S7 Futures/extra leg 없음 |
| G06 | 확정 해결 | 50% stop/2×-10% trailing/15:10 의도 정의; actual mark/fill evidence pending |
| G07 | 설정 이관 | holiday calendar/broker cutoff |
| G08 | 설정 이관 | account risk config/enforcement |
| G09 | 확정 해결 | reconcile-before-resume/reset policy 정의; durable recovery 미검증 |
| G10 | 설정 이관 | traceability 추가; exact test evidence NOT_RUN |
| G11 | 확정 해결 | S7-U16–U20 및 가정 명시 |
| G12 | 확정 해결 | draft와 user approval 분리 |

## 8. 검증 및 승인 상태
- F01–F29 재분류: 완료 (확정 의도 20 / 설정·검증 이관 9 / 사용자 확인 필요 0).
- 코드-의도 차이표: 14건 (명시적 불일치 8, 구현/증거 부족 3, 부분 일치/legacy/data validation 3).
- 새 U: S7-U16–S7-U20. U16/U17은 실행 상태 모호점, U18/U19는 source/account risk 의존성, U20은 rename 승인 경계다.
- 테스트: NOT_RUN (사용자 지시).
- REAL_VTS: NOT_RUN.
- 코드 수정: 없음. Git stage/commit/push: 없음. KIS Live 주문: 없음.
- 명세 상태: 초안 / 미검증 / 미승인. 구현 기준 사용 금지.
