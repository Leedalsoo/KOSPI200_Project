# Strategy 1~9 통합 설정 스키마 (draft)

- 작성일: 2026-10-13
- 상태: draft / unverified / unapproved
- 문서 전용. 실제 config/manifest는 수정하지 않았다.
- null / UNSET / PROVISIONAL / invalid / stale / identity mismatch → 신규 주문 차단. 명시적으로 확정된 false만 false로 인정한다.

## A. 공통 키

| 키 | 쉬운 의미 | 현재값 | 상태 | 검증 방법 | null/불일치 시 동작 |
|---|---|---|---|---|---|
| schema_version | 설정표 버전 | UNSET | UNSET | schema compatibility | 차단 |
| config_version / config_hash | 실행 설정 버전과 지문 | UNSET | UNSET | run manifest / SHA-256 대조 | 차단 |
| approval_state | 사용자 승인 여부 | unapproved | 확정 정책 | 승인 버전·범위 확인 | 차단 |
| timezone | 시간 기준 | Asia/Seoul | 기술 기본 후보 | source timestamp 의미 검증 | 모호하면 차단 |
| market_calendar_source | 거래일/휴장일 출처 | KRX authoritative required | UNSET | 공식 달력 대조 | DTE/D-4 판정 차단 |
| option_master_source | 계약 identity 출처 | authoritative KRX/KIS contract data | UNSET per run | code/type/strike/YYYYMMDD/multiplier 대조 | 차단 |
| expiry_yyyymmdd | 정확한 계약 만기 | 계약별 값 | 형식 확정, 값 검증 필요 | Option Master | 차단 |
| quote_source_timestamp | 원천 시세 시각 | 계약별 원천 필드 | 의미 미확정 | raw source field mapping | 차단 |
| quote_received_at | 수집기 수신 시각 | 관측값 | 기록 가능 | collector log | source time 대체 금지 |
| max_quote_age_seconds | 최대 호가 나이 | UNSET | UNSET | multi-day/multi-contract REAL_VTS | 차단 |
| max_bid_ask_width / min_quote_depth | 최대 호가 간격/최소 잔량 | UNSET | UNSET | authoritative order book + fills | 차단 |
| limit_price_policy | 지정가 시작/재호가 방식 | UNSET | PROVISIONAL | quote/tick/limit replay | 차단 |
| price_tick_rule / price_limit_rule | 호가 단위/가격 제한 | 계약·가격·세션별 | 공식 규칙 필요 | KRX rule + broker behavior | 차단 |
| order_timeout_seconds | 주문 대기 시간 | 전략별 UNSET | UNSET | order-state replay | 차단 |
| cancel_confirm_timeout_seconds | 취소 확인 최대 대기 | UNSET | UNSET | cancel/fill race replay | 취소 상태 불명 시 재주문 금지 |
| retry_interval_seconds / retry_max_attempts | 재시도 간격/최대 횟수 | 전략별 UNSET | UNSET | REAL_VTS replay | 차단 |
| max_requote_slippage_ticks | 재호가 허용 불리한 tick | UNSET | UNSET | quote/fill/slippage distribution | 차단 |
| account_total_capital_krw | 계좌 기준 자본 | UNSET | 사용자 승인 필요 | authoritative balance | 차단 |
| account_max_loss_krw | 계좌 전체 최대손실 | UNSET | 사용자 승인 필요 | actual lots/fees/stress loss | 차단 |
| account_max_margin_utilization_ratio | 증거금 이용률 상한 | UNSET | 사용자 승인 필요 | broker margin snapshot | 차단 |
| strategy_max_premium_krw | 전략별 최대 매입 프리미엄 | 전략별 UNSET | 사용자 승인 필요 | ask×filled qty×multiplier + fees/slippage | 차단 |
| position_reconciliation_required | 주문 전 실제 포지션 대사 | true | 정책 확정 | execution/position ledger | 실패 시 차단 |
| cancel_race_reconciliation_required | 취소 중 체결 재확인 | true | 정책 확정 | cancel request/confirm/fill events | 재주문 차단 |
| provenance_required | 시세·체결 출처 기록 | true | 정책 확정 | run/evidence manifest | 차단 |
| live_orders_enabled | 실계좌 주문 허용 | false | 본 작업 금지 | 별도 명시 승인 없이는 false | false 유지 |

## B. 전략별 키

| 전략 | 키 | 의미 | 현재값 | 상태 | 검증 방법 | null/미검증 시 동작 |
|---|---|---|---|---|---|---|
| S1 | base_call_put_qty / base_offset_pt | 기본 CALL/PUT 수량·ATM 거리 | 1 each / 12.5pt | 의도 확정 | listed strike map | 차단 |
| S1 | short_step_pt / short_offset_pt | 매도 간격·직전 기준점 오프셋 | 2.5pt / 7.5pt | 의도 확정 | step/strike boundary replay | 차단 |
| S1 | short_qty_cap | 미청산 매도 상한 | 10 | 의도 확정 | actual open lots | 상한 도달 시 신규 매도 중단 |
| S1 | hedge_trigger_distance_pt | 옵션 헤지 검토 거리 | UNSET | PROVISIONAL | tuning/validation 기간 분리한 REAL_VTS | 차단 |
| S1 | expiry_exit_trading_days | 만기 전 청산 | 4 | 의도 확정 | calendar + expiry master | 차단 |
| S2 | low_vol_ratio / entry_feature_thresholds | 넓은/좁은 구조와 신호 기준 | 0.85 후보 / source-specific | PROVISIONAL | formula/unit/source validation | 차단 |
| S2 | leg_order_timeout / leg_retry_policy | 레그별 대기·재주문 | 시간 UNSET; cancel-confirm + reconcile + remaining qty only | 정책 확정, 수치 미확정 | late/partial fill replay | 상태 불명 시 차단 |
| S3 | enabled / capital_gate_min | 활성/최소 자본 게이트 | false / null | 보류 | readiness gate + approval | 계속 차단 |
| S3 | futures_role | 선물의 역할 구분 | PRIMARY_ALPHA/SPREAD vs HEDGE | 검증 필요 | No.1151 / No.956 scope review | 역할 불명 시 차단 |
| S4 | enabled / capital_gate_min | 활성/최소 자본 게이트 | false / null | 보류 | Greeks/margin evidence + approval | 계속 차단 |
| S4 | greeks_source | 실제 Greeks 출처 | UNSET | UNSET | authoritative position/Greeks source | 차단 |
| S5 | session_minutes / min_gap_pt | 세션/최소 갭 | 30 / 1.0pt | session 의도 확정; threshold provisional | market open/previous close provenance | 차단 |
| S5 | advance_pt / reversal_ratio | 진행/되돌림 기준 | 1.0pt / 0.10 | PROVISIONAL | price path replay | 차단 |
| S5 | hedge_contracts / whipsaw_limit | 반대 옵션 수량/횟수 한도 | 1 / 2 | 횟수 한도 의도 확정; event definition provisional | fill-linked event replay | 정의 승인 전 차단 |
| S5 | reversal_min_pt / hedge_reversal_pt / session_end_action | 최소 되돌림·헤지 반전·세션 종료 | UNSET | UNSET | REAL_VTS and risk scenarios | 차단 |
| S5 | stop_loss_enabled / stop_loss_pt | 손절 사용/거리 | 명시 false 가능 / UNSET | 설정 검증 필요 | config validation/replay | absent/null이면 차단 |
| S6 | expiry_series / opposite_leg_timer_minutes | 일물 계약/반대 레그 timer | daily / 10 | timer 의도; contract source 검증 필요 | Option Master and fill replay | 차단
| S6 | retry_after_both_cancelled_same_day | 10분 무체결 후 양쪽 주문 취소 완료 시 당일 재시도 여부 | false | 사용자 확정 의도; 키명은 PROVISIONAL | 10분 경계·cancel race·late fill·restart 시나리오 | null/UNSET이면 신규 진입 차단 |
| S6 | entry_end_time / session_exit_time | 신규 진입 마감/당일 청산 시각 | 11:00 / 15:10 KST 후보 | 사용자 의도; 경계 검증 필요 | 공식 거래시간과 replay | 불일치면 차단 |
| S7 | entry_days / opposite_leg_timer_minutes / retry_cutoff | 진입 요일·timer·당일 마감 | Mon,Thu / 10 / 15:00 KST | 의도 | calendar and order-state replay | 차단 |
| S7 | skew thresholds / retry bounds | IV/skew/가격 한도 | UNSET | PROVISIONAL | quote source and fill replay | 차단 |
| S8 | entry_min_dte_trading_days | 최소 남은 거래일 | 10 | 사용자 의도 확정 | KRX calendar + exact expiry | 차단 |
| S8 | retry_window_trading_days / opposite_leg_timer_minutes | 재시도 창/timer | 3 / 10 | 사용자 의도 확정 | holiday/weekend boundary replay | 차단 |
| S8 | legacy_budget_gate_krw | 과거 200,000원 게이트 | 폐기 | 사용자 지시 | verify removed from future implementation | 잘못 존재하면 차단/수정 검토 |
| S9 | expiry_exit_trading_days / expiry_exit_time | 만기 전 청산 일수/시각 | 4 / 11:00 KST | 사용자 의도 확정 | calendar + expiry boundary | 차단 |
| S9 | exit_priority | 동시 청산 순서 | S1 → S9 | 사용자 의도 확정 | scheduler/order lifecycle | 차단 |
| S9 | primary_strike_rank / fallback_strike_rank | 행사가 순위 | 4 / 3 | 기존 의도; latest-source confirmation | Option Master/quote | 차단 |
| S9 | liquidity_recheck_interval_seconds / max_wait_seconds | 비유동성 재확인/최대 대기 | UNSET / UNSET | UNSET | orderbook and REAL_VTS | 차단 |

## C. 공통 산식과 상태 정의
- 매수 프리미엄 예산 = ask × 실제 체결 수량 × authoritative multiplier + 수수료 + 보수적 슬리피지. 필요한 입력이 없으면 산출 불가.
- 순손익은 실제 fill 기반. 호가/mark는 fill을 대체하지 않는다.
- 호가 나이 계산은 source time 의미가 확인된 경우에만 한다. receive time만으로 원천 quote freshness를 판정하지 않는다.
- 공통 상태: WORKING → CANCEL_REQUESTED → CANCEL_CONFIRMED → fills/positions reconciliation → remaining target quantity → new order. 취소 pending/unknown이면 재주문 금지.
- 매 실행에 run ID, strategy ID, schema/config version/hash, active values, approval record, calendar/master version, quote provenance, order/execution IDs를 기록한다.
- 기존 risk config가 있다는 사실만으로 실제 주문 경로 enforcement를 인정하지 않는다.

## D. 검증 차단 목록
1. No.1232: 관측 WS 77,310 프레임에서 H0IOASP0 option order-book frames 0건.
2. REST rate-limit 및 multi-day/multi-contract coverage 미검증.
3. KRX calendar와 exact expiry master 연결 미검증.
4. quote freshness/depth/spread, retry interval/attempts, slippage bound 미확정.
5. tick/price limit 및 broker cancel/fill race 미검증.
6. 계좌 자본·전략별 최대 프리미엄·계좌 최대손실·margin 한도 승인/집행 미검증.
7. runtime risk enforcement와 actual position reconciliation 증거 부족.

이 스키마는 구현·주문을 허가하지 않는다.


## 사용자 확인 결과 2026-10-13
네 항목 모두 예로 승인됨. 이는 정책 결정이며 코드 구현/테스트/REAL_VTS/실거래 승인은 아님.

1. S5 30분 종료: 신규 진입 중단, 미체결 취소 완료 확인, 체결 및 포지션 대사. 기존 포지션은 별도 승인된 청산/위험 규칙만 적용한다.
2. S1/S9 D-4: S1 청산 완료 확인 -> S9 목표 수량 재계산 -> 대기 매수 취소 완료 및 체결/포지션 대사 -> 실제 남은 S9 lot 청산. 요청/접수만으로 완료를 간주하지 않는다.
3. No.956/S3: 공식 No.956 베이시스를 임의 변경하지 않는다. 정의/단위/source identity가 충돌하면 S3는 BLOCKED 유지.
4. 버전: S1/S2/S5/S8/S9 파일명 v0.4를 버전 후보로 유지한다. 원본 제목 v0.3은 수정하지 않고 이후 신규 버전에서 파일명/제목을 일치시킨다.

U38/U40/U42의 정책 처리 방침은 해결됨. 런타임 검증은 미완료. D-4/DTE10 실제 날짜는 자료 미확보로 UNSET; S5 whipsaw는 검증형 후보; S6 재시도 정책은 해결됐으나 런타임 미검증; 공통 quote freshness/liquidity 임계값은 UNSET/BLOCKING.

## S6 재시도 규칙 — 2026-10-13 확정 델타
- `retry_after_both_cancelled_same_day=false`는 사용자 확정 의도(스키마 이름은 PROVISIONAL)다. 10분 안에 아무것도 체결되지 않고 양쪽 주문의 취소 완료 및 체결 대사가 끝나면 그날 재시도하지 않는다.
- S6는 S7/S8과 같은 재시도 정책을 공유하지 않는다. 공통 order/cancel/fill 상태 기계는 같되, 전략별 재진입 정책은 아래처럼 분리한다.
  - S6: 10분 무체결 + 양쪽 취소 완료 → 당일 재시도 없음.
  - S7: 월·목 각각 독립 세트, 15:00 KST까지 유효 체결 시도 반복; cutoff 이후 retry 금지.
  - S8: 월물 시작 후 3거래일 창에서 retry; DTE10/정확한 expiry gate 미확정이면 차단.
  - S2: cancel-confirm + fill/position reconcile 후 잔여 목표 수량만 재주문; 별도 daily retry count/price bound는 UNSET이면 차단.
- 공통 quote/liquidity key는 `max_quote_age_ms`, `clock_skew_limit_ms`, depth/spread thresholds 모두 UNSET/BLOCKING이다. No.1232의 관측값을 운영 임계값으로 승격하지 않는다.
## 공통 키 이름 정규화 후보 (모두 설정 문서 초안, runtime 미검증)

| 표준 후보 키 | 쉬운 의미 | 현재값 | 상태 | 검증 방법 | null/UNSET 동작 |
|---|---|---|---|---|---|
| `order_timeout_seconds` | 주문이 체결/종결되길 기다리는 시간 | 전략별; S6 600초 후보 | 공통 키 후보 / 수치는 전략별 | broker timestamps 및 timeout replay | 해당 주문/신규 진입 차단 |
| `cancel_confirm_timeout_seconds` | 취소 완료 응답을 기다리는 최대 시간 | UNSET | UNSET | cancel request/terminal ACK/late fill replay | UNKNOWN + RECONCILIATION_REQUIRED, 신규 주문 차단 |
| `max_quote_age_ms` | 호가가 너무 오래되지 않았는지 | null | UNSET/BLOCKING | multi-day/multi-contract source/receive distribution | 신규 주문 차단 |
| `clock_skew_limit_ms` | 거래소 시각과 수신 시각의 허용 차이 | null | UNSET/BLOCKING | independent NTP/clock evidence + raw timestamp replay | 신규 주문 차단 |
| `min_depth_by_side` | 매수/매도 호가에 필요한 최소 잔량 | null | UNSET/BLOCKING | depth distribution including 5th/6th strike | 신규 주문 차단 |
| `max_spread_ticks` | 매수/매도 호가 차이의 최대 허용치 | null | UNSET/BLOCKING | spread ticks and fill/slippage replay | 신규 주문 차단 |
| `account_total_capital_krw` | 계좌 전체 기준 자본 | null | PROVISIONAL/UNSET | authoritative account snapshot + user-approved risk budget | 신규 주문 차단 |
| `account_max_premium_krw` | 계좌 전체 옵션 프리미엄 한도 | null | PROVISIONAL/UNSET | actual filled premium/fees aggregation | 신규 주문 차단 |
| `account_max_loss_krw` | 계좌 전체 최대 손실 한도 | null | PROVISIONAL/UNSET | stress loss and realized/unrealized P&L replay | 신규 주문 차단 |
| `strategy_max_premium_krw` | 전략별 최대 프리미엄 | null per strategy | PROVISIONAL/UNSET | per-strategy fills and costs | 해당 전략 신규 주문 차단 |
| `strategy_max_loss_krw` | 전략별 최대 손실 한도 | null per strategy | PROVISIONAL/UNSET | per-strategy actual P&L/stress | 해당 전략 신규 주문 차단 |
| `account_margin_limit_krw` | 계좌 증거금 한도 | null | PROVISIONAL/UNSET | broker margin snapshot; no assumed offsets | 신규 주문 차단 |
| `market_calendar_source` | 거래일 달력 출처 | KRX official calendar required | UNSET until captured | source URL, retrieval date, content hash | D-4/DTE10 and time-gated entry blocked |
| `option_expiry_master_source` | 정확한 YYYYMMDD 만기 출처 | authoritative Option Master required | UNSET until captured | symbol/expiry/multiplier identity reconciliation | contract selection and new orders blocked |
| `config_version` / `config_hash` | 실행별 설정 버전/지문 | null until run manifest | UNSET | run manifest + SHA-256 | run not eligible for validation |

설정 키 표준화는 제안일 뿐 실제 JSON/YAML/config/manifest를 수정하지 않았다. 기존 유사 이름은 삭제하지 않고, 구현 전에 단일 canonical mapping을 별도 승인해야 한다.

## S6/S7/S8 retry policy — shared OMS, distinct strategy rules

| Strategy | Retry rule | Boundary / state gate | Validation |
|---|---|---|---|
| S6 daily insurance | No same-day retry after 10 minutes with zero fills, once both CALL/PUT orders are confirmed cancelled and fills/positions reconciled | Persist a no-retry fence; late/partial fills or unknown cancel state require reconciliation, not another attempt | Intent confirmed; runtime/replay NOT_RUN |
| S7 weekly insurance | Monday/Thursday sets may retry while eligible through 15:00 KST | Each weekly set has separate group/expiry/order state; no new entry after cutoff | Boundary and two-set replay NOT_RUN |
| S8 monthly strangle | Retry within three trading days after monthly start; third-day cutoff 15:00 KST | Entry additionally requires exact expiry/calendar and DTE >= 10 | Calendar and holiday-crossing replay NOT_RUN |

The common contract is terminal-order-state reconciliation, not a shared retry count or window. CANCEL_REQUESTED is not CANCEL_CONFIRMED; do not resubmit while cancel/fill/position state is unknown.

## S6 retry key semantics — explicit interpretation

retry_after_both_cancelled_same_day: false means same-day retry is disabled after the confirmed S6 zero-fill timeout condition. This does not authorize proceeding when cancellation or position reconciliation is unknown. The intent is user-confirmed; persistence and runtime enforcement are still unverified. A null/UNSET value or unknown order/fill state blocks new orders.


## KIS_SINGLE_SOURCE_UPDATE_20261014 — 데이터 공급 설정 초안

아래는 신규 설정 후보이며, 사용자 승인 전 구현 기준이나 전략 승인으로 간주하지 않는다.

- `kis.index_master.source_url`: KIS 공식 `fo_idx_code_mts.mst.zip`
- `kis.index_master.cache_dir`: `data/reference/kis/index_master`
- `kis.index_master.refresh_timezone`: `Asia/Seoul`
- `kis.index_master.refresh_attempts_per_kst_date`: `1`
- `kis.index_master.max_age_hours`: `24`
- `kis.index_master.storage_mode`: `append_only`
- `kis.option_expiry.source_field`: `output1.futs_last_tr_date`
- `kis.option_expiry.tr_id`: `FHMIF10000000`
- `kis.option_expiry.cache_dir`: `data/reference/kis/option_expiry`
- `calendar.source_order`: `KIS_COMPLETE_ANNUAL, USER_APPROVED_LIST, UNKNOWN`
- `calendar.allow_krx_runtime_fallback`: `false`
- `calendar.unknown_action`: `BLOCKED`
- `contract_multiplier.source`: `UNSET_UNTIL_KIS_AUTHORITY_CONFIRMED`
- `api.rate_limit.auto_retry`: `false`

전략 임계값, 진입·청산 로직, 주문 경로 및 위험 한도는 이 설정 초안의 범위가 아니다.

 
## Directive F schema addendum (2026-10-14; draft / not approval)
- Proposed planner settings: websocket_subscription_limit integer 1..41 (default 41); max_quote_age_seconds=null; minimum_hold_seconds=null; atm_hysteresis_points=null; automatic_rotation_enabled=false while thresholds are unset.
- Candidate required feeds: option trade H0IOCNT0 + option book H0IOASP0 per selected option symbol; mini-futures trade H0IFCNT0 + book H0IFASP0 only when S3/S4 enabled; KOSPI200 index H0UPCNT0/2001.
- Standard futures subscription remains disallowed until S3 near/far spread design is approved. The S5 mini-futures dependency is a known conflict and should block the affected stage pending a new approved specification.
- contract_multiplier and tick_size remain null/UNSET until a documented authoritative source and user approval are recorded. Existing code constants are not authoritative.
- Holiday source order: complete KIS annual calendar -> user-approved, hash-verified list -> UNKNOWN/BLOCKED. No KRX runtime fallback.