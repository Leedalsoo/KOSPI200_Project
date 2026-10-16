# Strategy 9 — S1 풋 보험 상세 명세 v0.3 (초안)

- 상태: **draft / unverified / unapproved — 구현 기준 사용 금지**
- 작성일: 2026-10-12
- 기준 브랜치/HEAD: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- 원본 strategy_9_event_overnight_insurance_spec_v0.2.md는 수정하지 않는다.
- 이 문서는 2026-10-12 사용자 직접 지시를 기존 v0.2보다 우선 적용한 신규 초안이다. 코드·테스트·commit/push·KIS Live 주문 승인이 아니다.
- 코드 사실과 목표 의도를 분리한다. 기존 코드·과거 PASS는 신규 요구사항이나 승인 근거가 아니다.

## 1. 의도 변경 이력

### v0.2 — 폐기되는 의도
장 마감 전 PUT+CALL 양매수로 overnight strangle을 만들고 다음 거래일 시초 급변동으로 다른 전략 손실까지 상쇄하려는 구조였다. 사용자가 다른 전략 손실을 커버하지 못했다고 판단해 목적·양매수·익일 청산 구조를 폐기한다. v0.2 파일은 역사 보존을 위해 유지한다.

### v0.3 — 새 의도
- 전략 역할은 S1이 보유한 매도 풋(short PUT)의 급락 위험을 부분 보강하는 OTM long PUT 보험이다. 완전 상쇄/완전 헤지를 약속하지 않는다.
- S1이 실제 풋 매도 포지션을 보유한 뒤 자동으로 진입 검토/주문한다. 월초 고정 시각이나 이벤트/야간 신호는 트리거가 아니다.
- S1 풋 보유 수량에 s1_put_link_ratio를 적용해 보험 목표 수량을 계산한다. 기준은 s1_put_link_basis: sold_puts.
- ATM 아래 4번째 행사가를 우선하고 불가 시 3번째를 후보로 한다. 호가 공백 또는 거래량 부족 때는 취소·late fill 대사 전 fallback 주문을 금지한다.
- 월 프리미엄 한도는 별도 설정하지 않는다. 실제 수량×가격×승수와 수수료는 파생 비용으로 기록·모니터링하며, 공통 계좌 위험/증거금 게이트는 별도로 적용한다.
- ID 변경 후보는 §11에 제안으로만 기재한다. 코드·기존 파일명·설정키·테스트 이름은 변경하지 않는다.

## 2. F01–F29 재분류

“확정”은 의도가 정해졌다는 뜻이지 구현/시장 검증 PASS가 아니다.

| ID | 항목 | 분류 | v0.3 의도 / 검증 사항 |
|---|---|---|---|
| F01 | 목적·보호 대상 | 확정 | S1 short PUT 급락위험의 부분 보강, 완전 헤지 아님 |
| F02 | 시장·상품 | 확정 | 표준 KOSPI200 옵션의 OTM PUT 매수 |
| F03 | 진입 트리거 | 확정 | S1 실제 PUT 보유가 트리거; 월초/이벤트/야간 트리거 폐기 |
| F04 | 입력·source·시점 | 사용자 확인 필요 | authoritative S1 position/lot source, freshness 및 누락 복구 확인 필요 |
| F05 | 중복 방지 | 확정 | S1 풋 보유 이후 target-vs-actual quantity를 계산하고 idempotency로 중복 방지 |
| F06 | 수량 연동 | 설정/검증값 | s1_put_link_ratio; S1 수량 증가·감소에 따라 S9 목표 수량 조정 |
| F07 | 주문·부분체결·취소 | 확정/검증 | 레그별 상태, 4번째 취소 확인 후 3번째, cancel-race 대사 |
| F08 | 행사가 선택 | 확정 | strike_rank=4, 불가 시 strike_rank_fallback=3 |
| F09 | 유동성·호가 공백 | 설정/검증값 | min_volume 및 quote gap/freshness 검사; 3번째도 불충분하면 확인 필요 |
| F10 | 만기·계약 identity | 확정 | 정확한 YYYYMMDD 만기 및 Option Master 계약 identity(No.1119) |
| F11 | 수량·승수·비용 | 설정/검증값 | S1 short PUT 잔여 수량×link ratio; 정수화 규칙 검증 필요 |
| F12 | 프리미엄·위험 | 확정/검증 | 별도 월 프리미엄 한도 없음; 공통 계좌 위험/증거금 게이트 유지 |
| F13 | 주문 가격·재가격 | 사용자 확인 필요 | LIMIT 및 30분 timeout 확정; 최초 limit 가격/재가격 횟수 미정 |
| F14 | 주문 전 preflight | 확정/검증 | config, contract, quote, liquidity, cost, account risk가 모두 유효해야 함 |
| F15 | partial/reject/cancel race | 확정/검증 | late fill·partial을 실제 lot과 대사; 취소 확인 전 fallback 금지 |
| F16 | 전략 레그·역할 | 확정 | OTM PUT 보험만; CALL 양매수 및 이벤트 트리거 폐기 |
| F17 | 실제 보유·노출 | 사용자 확인 필요 | S1 PUT와 S9 lots를 authoritative source로 대사해야 함 |
| F18 | 손절·최대손실 | 사용자 확정 의도 / 검증 필요 | 각 실제 매수 lot의 프리미엄이 해당 lot 실제 매수가의 50% 이하가 되면 해당 lot 청산; 공통 위험 게이트 유지 |
| F19 | 이익 실현 | 사용자 확정 의도 / 검증 필요 | 각 lot 프리미엄이 lot별 실제 매수가의 2배 이상 도달 시 high-water mark 추적 시작; 이후 최고가 대비 10% 하락 시 해당 lot 청산 |
| F20 | 시간 종료·rollover | 사용자 확정 의도 / 달력 검증 필요 | S1 노출이 0이어도 S9 lot을 독립 보유; 손절/추적청산이 먼저 발생하지 않으면 DTE7 rollover 정책까지 유지 |
| F21 | 청산 범위·수량 | 확정/검증 | 실제 S9 open lots 잔여 수량만 청산, flat 확인 전 reset 금지 |
| F22 | 손익·재매수 | 확정/검증 | TP 후 동일 종목을 이전 매수가의 130% 이하에서 재매수 |
| F23 | trigger 우선순위 | 사용자 확인 필요 | TP, S1 수량 감소, DTE7 roll, cancel/fill race 동시 발생 시 순서 미정 |
| F24 | 설정 버전·provenance | 확정 | 실행마다 spec/config version/hash와 order/fill/position provenance 기록 |
| F25 | restart·복구 | 사용자 확인 필요 | 재시작 후 S1/S9 lots, pending order, expiry 대사 후 재개 |
| F26 | 전략 간/계좌 위험 | 확정/검증 | S1/S9 premium·margin·stress 합산, 보호효과 중복 credit 금지 |
| F27 | 데이터 실패 | 확정 | null/stale/mismatch/UNAVAILABLE이면 신규 주문 차단 |
| F28 | 설정 스키마 | 확정 | PROVISIONAL 또는 필수 null이면 fail-closed |
| F29 | 테스트·수용 기준 | 설정/검증값 | REAL_VTS 튜닝/검증 기간 분리; 이번 작업에서 테스트 미실행 |

**F 재분류 집계(주 분류):** 확정/확정-검증 16, 설정·검증값 7, 사용자 확인 필요 6. 이는 의도 분류이지 완전성 검증 결과가 아니다.

## 3. 설정 스키마 초안 — PROVISIONAL

    strategy9:
      status: PROVISIONAL
      strategy_role: S1_PUT_INSURANCE
      strike_rank: 4
      strike_rank_fallback: 3
      order_timeout_minutes: 30
      fallback_requires_cancel_confirmed: true
      rebuy_same_instrument: true
      rebuy_max_ratio: 1.30
      hold_until_dte: 7
      next_expiry_buy_dte: 7
      stop_loss_ratio_of_entry: 0.50
      take_profit_multiple: 2.00
      trailing_drawdown_from_peak: 0.10
      min_volume: null
      s1_put_link_ratio: null
      s1_put_link_basis: sold_puts
      third_strike_insufficient_action: null

- monthly_premium_cap 설정은 만들지 않는다. 파생 비용은 실제 체결 수량×체결가×승수 및 수수료로 기록한다.
- status=PROVISIONAL이거나 필수값 min_volume, s1_put_link_ratio 등이 null/미검증이면 신규 진입·증액·fallback·rebuy·roll을 차단한다. stop_loss_ratio_of_entry=0.50, take_profit_multiple=2.00, trailing_drawdown_from_peak=0.10은 사용자 지정 정책값이나, 실행 전 가격 source/lot accounting/trigger order 검증이 필요하다.
- 공통 Risk/OMS preflight와 계좌 위험 한도는 우회할 수 없다.
- 실행마다 config version/hash, spec version, source timestamp, S1 position snapshot ID를 기록한다.

## 4. 계약·수량·시점 규칙

1. S1 PUT 수량은 매도해 아직 보유 중인 short PUT의 authoritative 잔여 계약 수(sold_puts)로 해석한다. 계좌 전체 PUT이나 과거 누적 체결 수량을 쓰지 않는다.
2. 목표 S9 수량은 검증된 s1_put_link_ratio와 S1 short PUT 잔여 수량으로 계산한다. 정수화/올림·내림 방식은 U33 검증 전 확정하지 않는다.
3. ATM과 3/4번째 OTM strike는 동일한 Option Master snapshot, 정확한 expiry YYYYMMDD, 표준 KOSPI200 옵션, strike ladder로 선택한다. strike 간격 2.5pt는 제공된 기준이며 실제 계약 identity로 확인한다.
4. 4번째 strike가 호가 공백/거래량 미달이면 그 주문을 취소한다. 취소 완료와 late-fill 대사 전에는 3번째 주문을 내지 않는다. 취소 중 4번째가 체결되면 3번째는 금지하고 target-vs-actual 수량을 다시 계산한다.
5. 30분 미체결은 실패 판정 및 취소 요청 시점이다. 취소 요청은 취소 완료가 아니다. 취소 확인 및 late-fill reconciliation 후에만 3번째 후보를 평가한다.
6. S1 PUT 수량 증가 시 S9 target과 actual 차이만 추가 매수하고, 감소 시 초과 보험 수량 일부 청산을 계획한다. 각 주문의 group/leg provenance를 보존한다.
7. TP 후 재매수 기준은 이전 실제 매수가의 1.30배 이하이다. 동일 종목·정확한 만기/행사가 identity를 사용한다. 거래 불가 시 대체 계약을 추측하지 않고 BLOCKED 처리한다.
8. hold_until_dte=7은 현 월물 청산/roll 시점 후보, next_expiry_buy_dte=7은 해당 시점에 차기 월물이 상장·거래 가능하면 매수 준비를 의미한다. DTE calendar/trading day 기준 및 실행 시각은 검증 전 확정하지 않는다.

## 5. 상태 전이표

| 현재 상태 | 이벤트/가드 | 다음 상태 | 안전 동작 |
|---|---|---|---|
| DISABLED/BLOCKED | config PROVISIONAL/null/invalid | BLOCKED | 신규 주문 금지, 이유/hash 기록 |
| WAIT_FOR_S1_PUT | authoritative S1 short PUT lot > 0 | S1_EXPOSURE_DETECTED | snapshot/lot provenance 기록 |
| S1_EXPOSURE_DETECTED | config/risk/expiry/quote valid | CONTRACT_PREFLIGHT | ATM/4th/3rd strike, volume, quote freshness 확인 |
| CONTRACT_PREFLIGHT | 4th eligible | FOURTH_LIMIT_WORKING | LIMIT 예약주문, 30분 timeout |
| CONTRACT_PREFLIGHT | 4th no quote/volume fail | FOURTH_NOT_ELIGIBLE | 3rd eligibility 별도 검사; 3rd도 불충분하면 U30 전까지 BLOCKED |
| FOURTH_LIMIT_WORKING | fill/partial fill | FOURTH_PARTIAL_OR_FILLED | 실제 체결량 반영; fallback 중단 또는 잔여량 재계산 |
| FOURTH_LIMIT_WORKING | 30분 경과, 미체결 | CANCEL_REQUESTED_4TH | 취소 요청; 3rd 주문 금지 |
| CANCEL_REQUESTED_4TH | cancel confirmed + late-fill reconciliation zero | FOURTH_CANCELLED_CONFIRMED | 3rd eligibility와 잔여 목표량 재계산 |
| CANCEL_REQUESTED_4TH | cancel race/late fill/unknown | RECONCILIATION_REQUIRED | 3rd 금지; broker/order/fill/position 재대사 |
| FOURTH_CANCELLED_CONFIRMED | 3rd eligible and risk valid | THIRD_LIMIT_WORKING | 3rd LIMIT 대체 주문 |
| THIRD_LIMIT_WORKING | fill/partial | INSURANCE_HOLD | actual fill/remaining qty 기준 |
| THIRD_LIMIT_WORKING | timeout/illiquid/no quote | BLOCKED_NO_ELIGIBLE_STRIKE | U30 전 시장가 전환·다른 strike 하강 금지 |
| INSURANCE_HOLD | S1 PUT qty increase | QTY_INCREASE_PENDING | 추가 수량만 주문, pending risk 포함 |
| INSURANCE_HOLD | S1 PUT qty decrease | QTY_REDUCTION_PENDING | 초과량 일부 청산, fill 후 target 갱신 |
| INSURANCE_HOLD | net P&L reaches configured TP | TAKE_PROFIT_EXIT_PENDING | actual open lots 기반 청산 |
| TAKE_PROFIT_EXIT_PENDING | fills complete + flat reconciled | REBUY_WAIT | 이전 실제 매수가 보존 |
| REBUY_WAIT | same instrument price <= prior buy ×1.30 | REBUY_PENDING | risk/quote preflight 후 동일 종목 재매수 |
| INSURANCE_HOLD | authoritative DTE reaches 7-day boundary | ROLL_OR_EXIT_PENDING | 현 월물 청산과 차기 월물 preflight를 별도 추적 |
| ROLL_OR_EXIT_PENDING | next expiry listed/valid and S1 exposure remains | NEXT_MONTH_ENTRY_PENDING |independent S9 lot policy follows user decision; DTE7 semantics validation pending |
| ROLL_OR_EXIT_PENDING | next expiry not listed/invalid | BLOCKED_NEXT_EXPIRY_UNAVAILABLE | U34 전 임의 대체/연장 금지 |
| any pending state | restart/stale/mismatch/partial/reject/cancel race | RECONCILIATION_REQUIRED | 재대사 전 재개 금지 |
| terminal close | all relevant lots flat confirmed | FLAT_CONFIRMED | 이후 reset; S1 exposure가 남으면 target 재계산 |

## 6. 부분체결·집행 묶음·안전 규칙

- No.1132/1134의 grouped execution, leg별 ExecutionReport, run/group/evaluation/exit-batch provenance 및 authoritative position-flat 확인 규칙을 유지한다.
- 주문 ACK는 체결이 아니고 취소 요청은 취소 완료가 아니다. fill/position read model 불일치는 RECONCILIATION_REQUIRED.
- pending buy는 실제 S9 보유량으로 계산하지 않는다. pending worst-case exposure도 Risk에 포함한다.
- S1 수량 감소에 따른 S9 일부 청산 중 S1 수량이 다시 증가해도 기존 close/cancel/fill race가 정리되기 전 반대 주문을 중복 발행하지 않는다.
- 시장가 강제 전환, 만기 연장, 다른 strike/expiry 추정, position reset은 허용하지 않는다.

## 7. REAL_VTS 검증 설계 — 값 확정 금지

- 튜닝 구간과 holdout 검증 구간을 거래일 기준으로 분리하고 동일 거래일/급락 이벤트가 중복되지 않게 한다. dataset ID, source provenance, 날짜 범위, config hash를 기록한다.
- take_profit_multiple=2.00은 사용자가 정한 trailing 활성화 문턱이다(고정 익절가 아님). REAL_VTS는 이 정책을 대체 후보로 재선정하는 데 쓰지 않고, 체결/슬리피지/수익환원 및 위험 특성을 검증하는 데 사용한다.
- min_volume: 후보 하한별로 spread/depth/quote age, quote gap, fill/partial/reject rate, slippage, fallback frequency를 비교한다. 거래량만으로 유동성을 대체하지 않는다.
- s1_put_link_ratio: 후보별 premium spend, S1 short PUT stress offset, account drawdown, margin, target-vs-actual qty 및 overlap/double-credit를 비교한다. 델타 환산으로 비율을 정당화하지 않는다.
- acceptance threshold/sample size는 사전 정의가 필요하고 미확정이다. 튜닝에서 고른 값은 holdout 통과와 사용자 승인 전 확정하지 않는다.
- Mock/Synthetic/DERIVED_SCENARIO는 REAL_VTS와 구분한다. 이번 작업에서 REAL_VTS 수집/실행은 하지 않았다.

## 8. 코드-의도 차이표 (읽기 전용 조사)

| 대상 | 현재 관찰 | v0.3 차이 | 분류 |
|---|---|---|---|
| core/strategy/track9_event_overnight_insurance.py | Track9EventOvernightInsurance / track9_event_overnight_insurance; 15:10 진입, ATM PUT/CALL pair, next-session opening shock, 30% giveback, qty default 1 | OTM PUT 단독, S1 short PUT 연동, rank 4→3, TP/rebuy/DTE7 roll 없음 | 잔재(폐기 대상) + 미구현 |
| Track9State | exact expiry 및 S1 lot link 없음; v0.2 조사상 _sync_date가 정의돼도 evaluate에서 호출되지 않음 | exact YYYYMMDD expiry, S1 snapshot/lot provenance, restart reconciliation 필요 | 불일치/미구현 |
| entry/exit | overnight pair entry/next-open close path | S1-held PUT trigger, PUT-only, TP/rebuy/roll lifecycle | 잔재(폐기 대상) |
| automated_virtual_runtime_factory.py / resolve_track9 | 기존 class 및 pair-plan 경로 연결 | 새 strategy_id/단일 OTM PUT/S1 linked quantity 경로 없음 | 수정 대상 차이; 코드 변경 금지 |
| tests/strategy/test_strategy9.py | 기존 overnight pair/time/opening-shock/trailing 중심 | 신규 PUT-only, S1 ratio, cancel-confirm fallback, rebuy, DTE7 roll을 검증하지 않음 | 레거시 테스트 |
| config/risk enforcement | PROVISIONAL/null 차단의 실제 주문 경로 강제 증거 미확보 | config gate와 account aggregate risk 검증 필요 | 미검증 |

**코드-의도 차이:** 주요 영역 5개, 상세 차이 8개: 양매수→PUT 단독; overnight→S1 trigger; ATM→rank 4/3; event/opening trigger 제거; TP multiple; 130% same-instrument rebuy; DTE7 roll; S1 linked quantity/config enforcement.

## 9. 사용자 확인 필요 — 확정 전 fail-closed

1. U30: 3번째도 거래량 미달/호가 공백이면 매수를 포기할지, 데이터가 유효해질 때까지 대기할지. 후보 설정 BLOCK_FOR_SESSION / WAIT_AND_RECHECK.
2. U31–U33: U31의 trailing 활성화 배수는 사용자 결정으로 2.00x 확정(고정 익절가가 아님). min_volume 및 s1_put_link_ratio는 §7의 REAL_VTS 튜닝/holdout으로 검증하며, 값 미확정이면 fail-closed.
3. U34: DTE7에 차기 월물이 상장되지 않았으면 BLOCKED. 이후 재시도할지, 현 월물 보험을 유지/청산할지 사용자 확인 필요.
4. U35: 사용자 결정으로 해결 — S1은 DTE4에 flat이 되어도 S9 보험 lot을 자동 청산하지 않는다. S9는 독립 포지션으로 유지하며, lot별 50% 손절 또는 2x 활성화 후 고점 대비 10% trailing 청산이 먼저 발생하지 않은 잔여 lot은 DTE7 rollover 정책까지 유지한다. 정확한 DTE calendar/trading 기준과 rollover 실행 시각은 검증 대기다.
5. U36: 최초 LIMIT 가격/재가격 간격·횟수와 3번째 strike 재시도 횟수는 미정. 확인/검증 전 임의 설정 금지.
6. U37: 파일명 후보 strategy_9_s1_put_insurance_spec_v0.3.md, strategy_id 후보 track9_s1_put_insurance 또는 strategy_9_s1_put_insurance. 기존 ID/path를 alias/retired history로 남기는 제안이며 실제 변경 금지.

## 10. 이름 변경 후보 및 영향 범위 — 제안만

- 신규 문서: strategy_9_s1_put_insurance_spec_v0.3.md.
- 후보 strategy_id: track9_s1_put_insurance 또는 strategy_9_s1_put_insurance.
- 기존 track9_event_overnight_insurance와 v0.2 path는 역사적 alias/retired mapping으로 보존한다.
- 영향 후보: core class/strategy_id, resolve_track9, registry, config schema/key, tests/fixtures, persisted state, position provenance, Control Tower labels, metrics/logs, traceability/matrix/scenario docs.
- 코드·기존 파일·설정·테스트는 변경하지 않았다.

## 11. 상태 및 승인 경계

필수 null/PROVISIONAL이면 신규 진입·증액·fallback·rebuy·roll을 fail-closed한다. S1 position/lot, exact expiry YYYYMMDD, quote, liquidity, multiplier, fills/positions, account risk가 유효하지 않으면 주문하지 않는다. 테스트 및 REAL_VTS 검증 실행 없음. Git commit/push 없음. KIS Live 주문 없음. 상태는 draft / unverified / unapproved.

## 12. 사용자 결정 반영 — S9 lot별 청산·독립 보유 정책 (2026-10-12)

- 승인된 정책 의도: S9 보험은 S1 short PUT 노출이 0이 되어도 자동으로 비례 청산하지 않고 독립 포지션으로 유지한다.
- lot별 손절: 각 매수 lot의 실제 체결 매수가를 기준으로 현재 옵션 프리미엄이 그 가격의 50% 이하이면 해당 lot의 실제 잔여 수량을 청산한다. 이는 lot 매수가 대비 50% 손실 수준이며, 다른 lot의 평균매수가로 대체하지 않는다.
- lot별 이익 추적: 각 lot의 프리미엄이 해당 lot 실제 매수가의 2.00배 이상에 처음 도달하면 해당 lot의 high-water mark 추적을 활성화한다. 이후 최고 관측 프리미엄 대비 10% 이상 하락하면 그 lot의 잔여 수량을 청산한다.
- 고점은 해당 lot/계약 identity별로 추적하고 restart 후 복원한다. mark/quote stale 또는 누락이면 손절/추적 조건을 0이나 임의 값으로 평가하지 않고 RECONCILIATION_REQUIRED / BLOCKED 처리한다.
- 위 조건 중 하나가 DTE7 rollover 시점 전에 충족되면 해당 lot은 그 조건에 따라 청산한다. 둘 다 충족되지 않으면 DTE7 경계에서 기존 rollover 절차를 적용한다. exact expiry는 YYYYMMDD이고 DTE calendar/trading semantics와 실행 시각은 별도 검증 전까지 미확정이다.
- 유효한 lot별 손절은 해당 lot의 신규 매수/재매수/롤보다 우선한다. 2x 이후 trailing exit가 활성화된 lot은 trailing 조건을 평가한다. 실제 fill/position 대사 완료 전 high-watermark/lot state reset 금지.
- take_profit_multiple=2.00은 2배에서 즉시 익절하는 고정 목표가가 아니라 trailing 감시를 시작하는 문턱이다.
- 이 정책은 문서상의 사용자 의도 확정이며, 구현 승인/시장 검증/REAL_VTS PASS를 의미하지 않는다.

Policy consistency note (2026-10-12): the user-selected lot stop/trailing/independent-hold policy in §12 supersedes any earlier provisional statement that the S9 stop or take-profit trigger is undecided.

## 13. 검증 게이트 추가 — 거래일 캘린더·호가 신선도·재시작 대사 (2026-10-12)

- DTE7 거래일 계산의 1차 출처는 KRX 공식 파생상품 연별 일정(https://open.krx.co.kr/contents/MKD/01/0110/01100303/MKD01100303.jsp)으로 한다. exact expiry YYYYMMDD와 차기월물 실제 상장 여부는 authoritative KRX/KIS Option Master 계약 스냅샷으로 교차 확인한다. 검증된 KRX 캘린더 캐시 외 임의 fallback은 금지하며 source/cache 모두 불능 또는 불일치이면 UNKNOWN/BLOCKED.
- DTE7의 포함/제외 off-by-one(만기 세션 포함 여부), 예외 휴장일 반영, 11:00 KST 결정 시각과 주문 제출 시각 관계는 실행 가능한 규칙/테스트 벡터로 검증하기 전 미확정이다. 11:00 KST 자체는 사용자 확정값으로 유지한다.
- 호가 신선도 한계값은 미확정이며 임의 숫자를 사용하지 않는다. KIS 옵션 REST/WS timestamp의 의미·단위·timezone·수신시각과 source시각 차이를 확인하고, VTS 관측자료에서 max quote age와 clock-skew/spread/depth 기준을 검증·승인해야 한다. 그 전까지 freshness config는 UNSET/BLOCKING이다.
- 재시작 복원은 lot별 실제 entry fills/가격, filled residual qty, exact contract+expiry, trailing armed, high-water mark, last processed market-data timestamp를 복원하고 broker orders/executions/positions와 대사해야 한다. missing/corrupt/mismatch/partial/late fill/cancel race면 RECONCILIATION_REQUIRED; 재진입·fallback·rebuy·roll 금지.
- quote source timestamp/receive timestamp/age, contract identity, calendar version/hash, order/execution IDs, broker position snapshot ID, reconciliation result와 spec/config hash를 증거로 보존한다. ACK 또는 cancel request만으로 체결/취소/flat을 확정하지 않는다.
- 상세 검증표와 테스트 케이스는 `05_strategy_9_dte7_quote_restart_validation_addendum_v0.1.md` 참조. 현재 상태 BLOCKED/NOT_RUN이며 구현 승인이나 PASS가 아니다.


### DTE7 deterministic counting convention — test contract, not runtime PASS
For a testable oracle, at 11:00:00 Asia/Seoul on decision date D, count KRX-open derivatives sessions strictly after D through exact contract expiry E inclusive. DTE7 triggers only when exactly seven such sessions remain; calendar days and guessed expiry patterns are prohibited. If E is not a valid session for the exact contract, or calendar/contract metadata is missing or conflicting, fail closed as UNKNOWN/BLOCKED. This proposed inclusion convention must be checked against product-specific intended semantics before runtime activation. Fixture test vectors and evidence requirements are in `05_strategy_9_dte7_quote_restart_validation_addendum_v0.1.md`.
