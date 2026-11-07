# Strategy 1~9 통합 명세 v1.0 (draft)

- 작성일: 2026-10-13
- 상태: draft / unverified / unapproved — 구현 기준으로 사용 금지
- 조사 기준: Project200 / 7eb9945e29774fb61fd2d07801762871b2506b98
- 문서 전용. 코드·테스트·설정/manifest·commit/push·KIS Live 주문 금지.
- 우선순위: 현재 사용자 지시 → 최신 유효 확정 Decision Log → AGENTS.md. 과거 문서는 증거일 뿐 승인이나 구현 권한이 아니다.
- 필수 입력/설정/계약 identity/신선도/포지션 대사가 null·UNSET·PROVISIONAL·불일치면 신규 주문 차단.
- S9는 “S1 풋 보험”으로 통일한다. 폐기된 스트래들 매도 명칭과 No.1168 BUY2는 재사용하지 않는다.

## 1. 최신 입력 및 델타 대조

| 영역 | 최신 입력 | 델타 입력 | 통합 상태 |
|---|---|---|---|
| S1 | strategy_1_tail_defense_spec_v0.4.md | strategy_1_code_intent_diff_v0.4.md | U28 기준점/행사가 요지 반영; 코드 차이는 미해결 |
| S2 | strategy_2_asymmetric_trap_spec_v0.4.md | S2 matrix/trace/scenario delta v0.5/v0.2/v0.2; code-intent diff v0.3 | 취소확정·체결대사 후 잔여량 재주문 반영 |
| S3 | strategy_3_statistical_arbitrage_spec_v0.3.md | No.1237; matrix v1.3 / traceability v0.9 / scenario v1.0 | enabled=false/capital_gate_min=null; preserve No.956; conflict keeps S3 BLOCKED |
| S4 | strategy_4_gamma_scalping_spec_v0.3.md | matrix v1.3 / traceability v0.9 / scenario v1.0 | enabled=false/capital_gate_min=null; Greek and futures role evidence needed before reactivation |
| S5 | strategy_5_gap_divergence_spec_v0.4.md | S5 matrix/trace/scenario delta v0.5/v0.4/v0.4 | 휩소 제안은 미검증 |
| S6 | strategy_6_daily_tail_insurance_spec_v0.4.md (신규 초안) | 2026-10-13 사용자 확정 델타 | 10분 무체결 + CALL/PUT 양쪽 취소 완료면 당일 재시도 없음; 구현 검증 미실시 |
| S7 | strategy_7_weekly_volatility_skew_insurance_spec_v0.3.md | matrix v1.3 / traceability v0.9 / scenario v1.0 | 월·목 세트/15:00 cutoff 검증 필요 |
| S8 | strategy_8_macro_regime_monthly_strangle_spec_v0.4.md | matrix v1.3 / traceability v0.9 / scenario v1.0 | DTE10, 예산 조건 폐기, 3거래일 재시도 반영 |
| S9 | strategy_9_s1_put_insurance_spec_v0.4.md | S9 matrix/trace/scenario delta v0.6/v0.4/v0.4 | D-4 11:00, S1→S9, 3번째 행사가 대기 반영 |
| Matrix | 02_decision_factor_integrated_design_matrix_v1.2.md | S2/S5/S9 deltas | v1.3 생성, 델타 원문 부록 흡수 |
| Traceability | 03_requirements_spec_code_test_traceability_v0.8.md | S2/S5/S9 deltas | v0.9 생성, 델타 원문 부록 흡수 |
| Scenario | 04_strategy_1_to_9_scenario_test_plan_v0.9.md | S2/S5/S9 deltas | v1.0 생성, 델타 원문 부록 흡수 |
| Data | Notion No.1232 | KIS timestamp/VTS freshness | BLOCKED: observed WS sample has 0 H0IOASP0 option order-book frames |

델타 세부 원문은 새 통합표·추적표·시나리오의 부록으로 흡수했다. 이 세 신규 파일을 최신 문서로 사용하고 기존 델타 파일은 역사 보존용으로 유지한다. “흡수”는 문서 반영을 뜻하며 구현/검증 완료를 뜻하지 않는다.

## 1-A. 최신 입력 버전 및 델타 반영 대조 (2026-10-13 갱신)

| 전략 | 최신 명세 입력 | 델타/보조 입력 | 대조 결과 |
|---|---|---|---|
| S1 | `strategy_1_tail_defense_spec_v0.4.md` | `strategy_1_code_intent_diff_v0.4.md`; U28/No.1238 | 반영됨: 직전 기준점 ± offset 후 ATM 갱신; code/runtime 차이는 미검증 |
| S2 | `strategy_2_asymmetric_trap_spec_v0.4.md` | matrix delta v0.5, trace delta v0.2, scenario delta v0.2, code-intent diff v0.3 | 반영됨: 취소 완료·실제 체결 대사 후 잔여 수량만 재주문 |
| S3 | `strategy_3_statistical_arbitrage_spec_v0.3.md` | No.1237; No.956 scope comparison | 반영됨: enabled=false, capital_gate_min=null; No.956 충돌 시 계속 BLOCKED |
| S4 | `strategy_4_gamma_scalping_spec_v0.3.md` | current matrix/trace/scenario; 별도 delta file 미확인 | 부분 반영: 보류 게이트 기록; 추가 확정 델타 파일은 미확인 |
| S5 | `strategy_5_gap_divergence_spec_v0.4.md` | matrix delta v0.5, trace delta v0.4, scenario delta v0.4 | 반영됨: 30분 종료 승인 정책 및 휩소는 검증형/미확정 |
| S6 | `strategy_6_daily_tail_insurance_spec_v0.4.md` | 사용자 직접 확정 2026-10-13 | 반영됨: 당일 재시도 없음; 새 v0.4는 초안·미검증 |
| S7 | `strategy_7_weekly_volatility_skew_insurance_spec_v0.3.md` | current matrix/trace/scenario; 별도 delta file 미확인 | 반영됨: 월·목 별도 세트, 15:00 KST까지 retry 정책 유지 |
| S8 | `strategy_8_macro_regime_monthly_strangle_spec_v0.4.md` | prior S8 delta content; DTE10/3 trading days | 반영됨: 3거래일 창; 달력 근거 없으면 DTE 게이트 차단 |
| S9 | `strategy_9_s1_put_insurance_spec_v0.4.md` | matrix delta v0.6, trace delta v0.4, scenario delta v0.4 | 반영됨: S1→S9 D-4 11:00, 3번째 행사가 비유동이면 대기 |
| Market data | No.1157 + No.1232 | subscription rotation / timestamp freshness | 부분 반영: 회전 요청은 ACK 증거 아님; 77,310 WS frames에 H0IOASP0 0건인 관측, quote thresholds UNSET |

흡수 상태: S1/S2/S5/S9 deltas = 반영됨; S3/S4/S6/S7/S8 supporting records = 본문/상호작용에 반영됨; 코드-의도 diff는 확인된 S1/S2만 개별 파일 확보, 다른 전략의 개별 diff 파일은 미확인으로 표시. 구버전·델타 파일은 삭제하지 않는다. Matrix v1.3, traceability v0.9, scenario v1.0, integrated spec v1.0 draft 및 본 boundary table이 이번 정리의 최신 후보 문서다. 

## 2. 공통 실행 계약
1. 일반 KOSPI200 옵션만 허용. 계약 코드·옵션 유형·행사가·정확한 YYYYMMDD 만기·승수는 authoritative Option Master로 확인한다. Mini 대체 금지(No.1070).
2. KST를 사용한다. D-4/DTE10은 KRX 공식 거래일 달력과 실제 만기 마스터로 계산한다. 거래일 경계 포함 규약은 UNSET이며 근거 없으면 차단한다.
3. source timestamp와 receive timestamp를 분리한다. No.1232에서 WS bsop_hour는 HHMMSS로 관찰됐고 canonical observed_at는 수신 시각이었다. 77,310개 WS 프레임에서 H0IOASP0 옵션 호가 프레임은 0건이었다. 수신 시각만으로 신선도를 증명하지 않는다.
4. CANCEL_REQUESTED ≠ CANCEL_CONFIRMED. 취소 완료와 late/partial fill 및 포지션을 대사한 뒤 잔여 목표 수량만 재주문한다. 상태 불명/대사 불일치면 신규 주문 차단.
5. 각 레그의 주문·체결·lot을 독립 관리하고 strategy/group/leg/client_order/execution ID를 보존한다. 동일 계약을 여러 전략이 보유해도 한 전략의 fill을 다른 전략의 fill로 간주하지 않는다.
6. 지정가, 호가 freshness/depth, tick/price limit, 재호가/슬리피지, 수수료/승수 및 계좌 위험 게이트는 검증 전 UNSET이다. 미검증이면 fail-closed.
7. config/schema version/hash, exact expiry, quote provenance, actual fills, fees, position and account risk snapshot을 실행별로 기록한다.
8. 설정 파일이 존재한다는 사실만으로 runtime risk enforcement가 입증되는 것은 아니다. 실제 주문 경로에서 증거가 확인될 때까지 BLOCKED.

## 3. 전략별 요약

### S1 — Tail Defense / 가두리 매도
기본 방어: ATM 기준 CALL BUY 1(+12.5pt) + PUT BUY 1(−12.5pt). 매 2.5pt 상승 교차마다 직전 기준점−7.5pt의 PUT 매도, 하락은 직전 기준점+7.5pt의 CALL 매도. 행사가 계산 후 기준점을 새 ATM으로 갱신. 예: 100→102.5 PUT 92.5, 102.5→105 PUT 95. 매도 미청산 수량 상한 10. Mini futures hedge 폐기, 옵션 hedge는 실제 미청산 매도 fill/lot 기준. 만기 4거래일 전 전량 청산.
- 설정 후보: short_step_pt=2.5, short_offset_pt=7.5, short_qty_cap=10; hedge trigger, listed-strike rounding, quote freshness UNSET.
- 상태: MONTH_WAIT → BASE_OPTIONS_PENDING → ACTIVE → SHORT/HEDGE_PENDING/FILLED → D4_EXIT → RECONCILIATION_REQUIRED/FLAT.
- 미결: 실제 strike mapping, hedge trigger, D-4 calendar boundary, legacy futures route difference.

### S2 — Asymmetric Trap
안쪽 PUT/CALL BUY 각 1 + 바깥 PUT/CALL SELL 각 1, 순차 지정가 주문, 월물별 1사이클, 기존 feature 묶음 유지. 레그를 all-or-none으로 가정하지 않는다.
- 설정: volatility/feature thresholds, timeout, retry price/attempts, stop/trailing remain PROVISIONAL/UNSET.
- 상태: PREFLIGHT → LEG_ORDERED → PARTIAL/FILLED_GROUP → MONITOR → EXIT → RECONCILIATION/FLAT.
- 취소된 레그는 취소 확정 및 실제 fills/positions 대사 후 잔여 목표 수량만 재주문한다.

### S3 — Statistical Arbitrage / Futures calendar spread
근월·원월 KOSPI200 futures calendar spread 후보. 선물의 PRIMARY_ALPHA/SPREAD와 HEDGE 역할을 구분하며 옵션 수량으로 대체하지 않는다. No.956 basis 정의는 승인 없이 변경 금지.
- enabled=false, capital_gate_min=null, 보류.
- 재개: 정확한 계약/월물 identity, No.956 적용 범위, payoff/margin/risk 및 VTS evidence, 별도 사용자 승인.
- 범위 충돌이면 임의 해석하지 않고 S3를 계속 BLOCKED.

### S4 — Gamma Scalping
실제 옵션 position/authoritative Greeks를 기준으로 futures rebalance/unwind 목적을 검토. Basecamp NON_EXECUTION은 fill이 아니다. 선물 헤지는 옵션 수량으로 치환하지 않는다.
- enabled=false, capital_gate_min=null, 보류.
- 재개: Greeks source/age, futures role/quantity/unwind, capital/margin gates 검증 및 별도 승인.

### S5 — Gap Divergence
시초 갭이 threshold 이상이면 갭 방향 ATM 옵션 매수. 약 30분 세션. 갭 방향 1.0pt 진행 전 반대 움직임은 반대 옵션 1계약 헤지 후보; 1.0pt 진행 후 peak/trough에서 gap×0.10 되돌림은 hedge가 아니라 이익 청산. 휩소 2회 시 당일 신규 진입 중단 및 잔여 노출 정리. 과거 futures 5계약은 방어 목적이며 option 1계약으로 기계 치환 금지.
- 설정: session_minutes=30, min_gap_pt=1.0, advance_pt=1.0, reversal_ratio=0.10, hedge_contracts=1, whipsaw_limit=2; reversal_min_pt, hedge_reversal_pt, session_end_action, stop_loss_pt UNSET.
- 휩소는 거래소 공통 정의가 아니다. 실제 반대 옵션 fill 이후 가격 재반전과 hedge-reversal 종료를 묶는 완결 cycle을 1회로 세는 제안은 REAL_VTS replay/승인 전 미확정.

### S6 — Daily Tail Insurance
일물 단위 독립 세트, 레그별 fill/lifecycle 독립 관리. 반대편 10분 timer 이후 재시도 규칙을 해당 만기·세션 cutoff와 함께 적용한다.
- 설정: exact expiry, strike, retry count/price bounds, freshness, exit cutoff PROVISIONAL/UNSET.
- 미결: 세션/만기 종료 행동 및 retry price/attempts. 근거 없으면 차단.

### S7 — Weekly Volatility Skew Insurance
월요일·목요일 2개 독립 세트. 반대편 레그 10분 timer, 당일 15:00 KST 이후 신규 재시도 금지.
- 설정: entry_days=[Monday,Thursday], opposite_leg_timer_minutes=10, retry_cutoff=15:00 KST; IV/skew thresholds and retry bounds UNSET.
- 미결: 두 세트 overlap, cutoff의 working order/position 처리.

### S8 — Macro Regime Monthly Strangle
월물 양매수. 만기까지 10거래일 이상 남아야 진입. 기존 200,000원 예산 조건 폐기. 반대편 미체결 레그는 10분 timer 후 재시도하며 재시도 창은 3거래일. 공통 계좌/전략 위험 한도는 유지.
- 설정: entry_min_dte_trading_days=10, retry_window_trading_days=3, opposite_leg_timer_minutes=10.
- 미결: DTE 경계 포함 규약, 3거래일째 cutoff, freshness/retry price limits. UNSET이면 차단.

### S9 — S1 풋 보험
S1 실제 미청산 short PUT 수량을 기준으로 표준 KOSPI200 OTM PUT 보험. 우선 rank 4, 다음 rank 3. 세 번째 행사가도 비유동이면 임의 가격 진입 없이 대기 후 같은 계약의 새 호가 재확인. 만기 4거래일 전 11:00 KST에 청산 lifecycle 시작. 같은 만기 충돌 시 S1 → S9.
- 상태: LINK_S1_LOTS → RANK4 → WAIT/RECHECK_OR_RANK3 → BUY_PENDING/FILLED → MONITOR → D4_1100_EXIT → RECONCILIATION/FLAT.
- S1 청산으로 S9 target=0이면 S9 pending buy 취소/대사; 이미 체결된 S9 lot은 별도 청산한다. 같은 lot의 중복 청산 주문 금지.
- 미결: D-4 trading-day boundary, liquidity threshold/recheck interval, legacy DTE7 rollover relation.

## 4. 확정 의도 체크리스트

| ID | 의도 | 위치 | 누락 |
|---|---|---|---:|
| INT-S1-01 | base strangle ±12.5pt, qty 1 | §3 S1 | 0 |
| INT-S1-02 | previous reference ±2.5pt; strike at previous reference ∓7.5pt; refresh after calculation | §3 S1 | 0 |
| INT-S1-03 | short cap 10; option hedge; D-4 exit; no Mini Futures hedge | §3 S1 | 0 |
| INT-S2-01 | 4 legs sequential; independent fills | §3 S2 | 0 |
| INT-S2-02 | cancel confirm + fill/position reconcile + remaining qty only | §3 S2 | 0 |
| INT-S3-01 | futures calendar spread; No.956 preserved; disabled | §3 S3 | 0 |
| INT-S4-01 | actual option/Greeks anchor; disabled | §3 S4 | 0 |
| INT-S5-01 | 30m, gap, advance, reversal, hedge | §3 S5 | 0 |
| INT-S5-02 | whipsaw limit 2; event rule still proposed | §3 S5 | 0 |
| INT-S6-01 | daily set and independent leg lifecycle/timer | §3 S6 | 0 |
| INT-S7-01 | Mon/Thu sets, 10m timer, 15:00 cutoff | §3 S7 | 0 |
| INT-S8-01 | DTE≥10 trading days; remove 200,000 KRW gate; 3-day retry | §3 S8 | 0 |
| INT-S9-01 | S1-linked PUT insurance; rank4→rank3→wait/recheck | §3 S9 | 0 |
| INT-S9-02 | D-4 11:00 KST and S1→S9 | §3 S9 | 0 |
| INT-COM-01 | fail-closed, cancel/fill reconciliation, provenance/config hash | §2 | 0 |
| INT-COM-02 | source time != receive time; No.1232 blocker | §2 | 0 |

## 5. 상태
명세 통합 초안일 뿐 승인 아님. 코드-의도 비교는 문서 증거다. 시나리오 테스트와 REAL_VTS replay는 NOT_RUN. 설정 미확정 값은 UNSET/BLOCKED.


## 6. Source version/header audit ? unresolved metadata mismatch

Latest input candidate paths were selected by the requested filename versions, but the first-line embedded headings of these five files still say v0.3: S1 v0.4, S2 v0.4, S5 v0.4, S8 v0.4, and S9 v0.4. This is a metadata conflict, not evidence that their content is older. Existing inputs were not edited because the deliverables require new versions and preservation. Treat the requested filename versions as candidate inputs only; before a final approved baseline, correct the headings in a new follow-up revision or explicitly confirm the intended version labels. No strategy behavior was inferred from this mismatch.

## 7. Explicit delta comparison table

| Strategy | Delta requirement | Status in consolidated draft | Conflict / remaining issue |
|---|---|---|---|
| S1 | U28 previous-reference strike formula | Reflected in integrated spec and canonical matrix/trace/scenario base | Source filename/header mismatch; code still differs |
| S2 | Cancel-confirm, actual fill reconciliation, remaining target quantity only | Reflected in spec summary and S2 delta appendix in v1.3/v0.9/v1.0 | Broker cancel/fill replay not run |
| S3 | Futures calendar spread, No.956 unchanged, disabled/capital gate null | Reflected | No.956 signal/unit/scope comparison unresolved |
| S4 | Disabled/capital gate null; actual Greeks and futures role | Reflected | authoritative Greeks/runtime path unresolved |
| S5 | Whipsaw event scenarios and 30-minute end behavior | Partially reflected | Whipsaw remains proposal; session_end_action UNSET |
| S6 | Daily independent set and opposite-leg timer | Reflected at summary level | retry/cutoff detail UNSET |
| S7 | Monday/Thursday two sets, 10-minute timer, 15:00 cutoff | Reflected at summary level | overlapping lots/cutoff order handling unverified |
| S8 | DTE ?10 trading days, remove 200,000 KRW gate, 3 trading-day retry | Reflected | exact calendar boundary and retry cutoff UNSET |
| S9 | D-4 11:00 KST, S1?S9, rank-3 wait/recheck | Reflected | D-4 boundary, liquidity threshold/recheck interval UNSET |
| No.1232 | quote source/receive timestamp and option order-book coverage | Reflected | H0IOASP0 frames=0; quote freshness remains BLOCKED |

All delta source files are included verbatim as appendices in the three canonical matrix/traceability/scenario files. That is documentary absorption only, not a claim of semantic verification or runtime implementation.


## 8. U-register delta (IDs preserved; no renumbering)

| U-ID | Item | Status | Resolution / next action |
|---|---|---|---|
| U28 | S1 short-strike reference anchor | Resolved as user intent | Previous reference point ? offset; refresh reference to newly reached ATM only after strike calculation. Code implementation remains unauthorized and unverified. |
| U38 | S1/S2/S5/S8/S9 filename version vs embedded heading | 처리 방침 해결 | Keep v0.4 filename as candidate; preserve original v0.3 title in existing file and align title only in next new version. |
| U39 | D-4 and DTE10 trading-day counting boundary | 해결 경로 지정; dates UNSET | `trading_day_boundary_table_draft.md`; exact KRX calendar and Option Master YYYYMMDD not yet obtained; fail-closed until then. |
| U40 | S5 30-minute session-end handling | 정책 선택 해결; runtime NOT_RUN | Stop new entries, confirm cancels and reconcile fills; existing positions follow separately approved exit/risk rules only. |
| U41 | S5 whipsaw event count | Proposed / unverified | Candidate event is a completed opposite-option hedge cycle followed by price return satisfying the hedge-reversal condition. Validate with actual price/fill sequence and deduplicate by event ID; no approval implied. |
| U42 | No.956 basis definition scope for S2/S3 | 정책 선택 해결; source compatibility unresolved | Preserve No.956. If official definition conflicts with S3 signal semantics, keep S3 BLOCKED; no silent change. |
| U43 | S6 same-day retry after 10-minute no-fill | 정책 선택 해결; runtime NOT_RUN | No fill within 10 minutes + both CALL/PUT orders confirmed cancelled and reconciled → no same-day retry. |
| U44 | Common quote freshness/liquidity thresholds | UNSET / evidence blocker | Use No.1157/No.1232 and the documented multi-day/multi-contract measurement plan; numeric values remain null/BLOCKING. |

No existing U identifier was deleted or renumbered. U38?U44 are integration-level items; U45 records incomplete per-strategy code-intent-diff source coverage. Full historic U-register duplicate audit remains unverified.


## 사용자 확인 결과 2026-10-13
네 항목 모두 예로 승인됨. 이는 정책 결정이며 코드 구현/테스트/REAL_VTS/실거래 승인은 아님.

1. S5 30분 종료: 신규 진입 중단, 미체결 취소 완료 확인, 체결 및 포지션 대사. 기존 포지션은 별도 승인된 청산/위험 규칙만 적용한다.
2. S1/S9 D-4: S1 청산 완료 확인 -> S9 목표 수량 재계산 -> 대기 매수 취소 완료 및 체결/포지션 대사 -> 실제 남은 S9 lot 청산. 요청/접수만으로 완료를 간주하지 않는다.
3. No.956/S3: 공식 No.956 베이시스를 임의 변경하지 않는다. 정의/단위/source identity가 충돌하면 S3는 BLOCKED 유지.
4. 버전: S1/S2/S5/S8/S9 파일명 v0.4를 버전 후보로 유지한다. 원본 제목 v0.3은 수정하지 않고 이후 신규 버전에서 파일명/제목을 일치시킨다.

U38/U40/U42/U43의 정책 처리 방침은 해결됨. 런타임 검증은 미완료. D-4/DTE10 실제 날짜는 자료 미확보로 UNSET; S5 whipsaw는 검증형 후보; S6 재시도 정책은 해결됐으나 런타임 미검증; 공통 quote freshness/liquidity 임계값은 UNSET/BLOCKING.

## 해결 경로 — 남은 항목 상태 (2026-10-13)

| 항목 | 처리 유형 | 현재 처리 | 상태 |
|---|---|---|---|
| D-4/DTE10 거래일 경계 | 자료 확보형 | `trading_day_boundary_table_draft.md`에 공식 소스 후보, 12개월 후보 날짜, UNSET 칼럼 및 경계 테스트 벡터 기록 | 해결 경로 제시; 실제 날짜 UNSET/BLOCKED |
| S5 휩소 판정 | 검증형 | 현재 제안 정의를 설정 후보로 유지하고 REAL_VTS replay로 검증 | 미확정; 설정 후보 |
| S6 재시도 | 사용자 확정 | 10분 안에 아무것도 체결되지 않고 양쪽 주문이 모두 취소 완료되면 당일 재시도 없음 | 정책 해결; 런타임 검증 NOT_RUN |
| 공통 호가 신선도·유동성 | 검증형 | 임계값 null/UNSET 유지. No.1157/No.1232 기반 갱신 간격·깊이·5/6번째 행사가 잔량/거래량 분석 계획 | 값 UNSET/BLOCKING |

### 공통 호가 신선도·유동성 측정 계획
- No.1232: source timestamp와 receive timestamp는 다르며, `bsop_hour`는 HHMMSS로 관찰됐다. 한 계약·한 날짜 178 프레임의 receive interval 중앙값 4.619초, p95 238.805초, 최대 576.946초였으나 표본/출처 충돌로 임계값 근거로 사용할 수 없다. 여러 관측일의 WS raw 77,310 프레임에서는 H0IOASP0 0건이었다. freshness limit과 clock-skew limit은 UNSET/BLOCKING.
- No.1157: 5.0pt 이동에 따른 재중심화와 41개 구독 한도, 회전 이벤트를 기록하나 `ROTATION_REQUESTS_SENT`는 broker ACK/실제 구독 완료 증거가 아니다.
- 향후 분석 지표: (1) 계약별 source timestamp와 receive timestamp 분포, 갱신 간격 median/p95/p99/max, 장시간 공백, (2) 호가 나이·시계 차이·중복/역행 timestamp, (3) bid/ask spread ticks 및 locked/crossed quote 비율, (4) 1~5단계 호가 깊이와 양쪽 잔량, (5) ATM에서 5·6번째 행사가의 quote availability, 잔량 및 거래량 분포, (6) 재중심화·구독 회전 중 공백 길이와 실제 ACK/프레임 커버리지, (7) REST/WS source capability/provenance.
- 판단은 충분한 일수·계약·장세 표본과 source capability 증거를 분리한 뒤 제안한다. 숫자 threshold는 이 문서에서 정하지 않으며, 검증 및 사용자 승인 전까지 주문 차단.

## 확정 의도 체크리스트 인덱스
모든 전략별 확정 의도는 각 `strategy_*_spec_v0.x.md`의 사용자 확정 의도 절을 원문 기준으로 대조해야 한다. 이 통합 초안의 체크리스트는 S1 U28, S2 cancel-confirm/reconcile, S5 session policy, S6 no-retry, S7 15:00 retry, S8 DTE10/3 trading days, S9 D-4 11:00/S1-first, S3/S4 disabled/capital gate, No.956 보호를 포함한다. 원문 전체와의 누락 0건은 시나리오/델타 전수 검증 전까지 `NOT_VERIFIED`로 유지한다.
## 확정 의도 체크리스트 — source item ↔ 통합 위치 (draft)

| ID | 확정 의도 / 원문 기준 | 통합 위치 | 대조 상태 |
|---|---|---|---|
| G-01 | 사용자 확정 의도만 현재 요구사항/승인 기준; 과거 문서는 증거 | §0, §1-A | 반영됨 |
| G-02 | No.1131 조용한 논지 변경 금지; No.1132/1134 레그별 주문·체결·취소 및 flat 대사 | §2 공통 실행 계약; §3 각 전략 state summary | 반영됨; runtime NOT_RUN |
| G-03 | No.1119 정확한 expiry YYYYMMDD; No.1070 미니옵션 금지 | §2; S6 v0.4; trading-day boundary table | 반영됨; Option Master 미확보 |
| G-04 | No.1151 선물 역할 구분, 옵션 계약 수로 선물 수량 대체 금지 | S3/S4 summary; 충돌표 #11 | 반영됨 |
| G-05 | No.1046 및 fail-closed: null/UNSET/PROVISIONAL이면 신규 거래 차단 | §0, §2, config schema §A | 반영됨 |
| S1-01 | 상승 2.5pt 교차마다 직전 기준점−7.5pt PUT 매도; 하락은 직전 기준점+7.5pt CALL; 이후 ATM으로 기준점 갱신 (U28/No.1238) | §3 S1; §1-A; matrix v1.3 | 반영됨; strike mapping/runtime 미검증 |
| S1-02 | 만기 D-4 전량 청산, 동시 만기면 S1 먼저 | §3 S1; §1-A; trading-day table | 반영됨; actual dates UNSET |
| S2-01 | 4레그를 all-or-none으로 가정하지 않음; 취소 완료·fills/positions 대사 후 잔여 목표량만 재주문 | §3 S2; matrix/trace/scenario v1.3/v0.9/v1.0 | 반영됨; runtime NOT_RUN |
| S3-01 | 선물 role classification 유지; No.956 정의 임의 변경 금지; 충돌 시 S3 BLOCKED | §3 S3; conflict review #11 | 반영됨; basis compatibility BLOCKED |
| S4-01 | `enabled=false`, `capital_gate_min=null`; 별도 검증·승인 전 보류 | §3 S4; conflict review #11 | 반영됨; reactivation gate open |
| S5-01 | 장 시작 후 약 30분만 진입; 30분 종료 신규 진입 중단, 미체결 취소 확인·체결 대사; 기존 포지션은 별도 승인 규칙만 적용 | §3 S5; conflict review #8 | 정책 반영; whipsaw definition remains unverified |
| S5-02 | 1pt gap threshold/advance; opposite option hedge; 10% gap reversal proposal; whipsaw limit 2 proposal | §3 S5; config schema; scenario plan | proposal retained; REAL_VTS validation pending |
| S6-01 | 장 시작 후 11:00까지 변동성 조건 관찰/진입 시도; 10분 무체결 + CALL/PUT 양쪽 취소 완료이면 당일 재시도 없음 | `strategy_6_daily_tail_insurance_spec_v0.4.md`; scenario TP-S6-V04-E01..R01; config schema | 사용자 확정 의도 반영; runtime NOT_RUN |
| S6-02 | 한쪽 체결은 양쪽 무체결 취소와 구분; 실제 체결 lot 보존, 취소·포지션 대사 후 승인된 one-leg policy만 적용 | S6 v0.4; scenario TP-S6-V04-E03/E04 | 반영됨; runtime NOT_RUN |
| S7-01 | 월·목 각 별도 세트, 15:00 KST까지 eligible retry | §1-A; config schema; scenario retry comparison | 반영됨; calendar/replay NOT_RUN |
| S8-01 | 월물 시작 후 3거래일 retry window; 진입 DTE≥10; 기존 200,000 KRW budget gate 폐기 | §1-A; config schema; scenario retry comparison | 반영됨; actual DTE UNSET |
| S9-01 | S9는 S1 풋 보험; S1 target=0이면 목표량 재계산·대기 매수 취소/대사 후 실제 lot 청산; S1 우선 | §3 S9; conflict review #1; trading-day table | 반영됨; runtime NOT_RUN |
| S9-02 | D-4 11:00 KST exit; rank-3 liquidity shortage means wait/recheck, no arbitrary price | §3 S9; config schema; scenario plan | 반영됨; calendar/quote thresholds UNSET |
| DATA-01 | No.1157 rotation request ≠ broker ACK; No.1232 quote freshness thresholds UNSET/BLOCKING | §2; §1-A; quote evidence plan | 반영됨; coverage unresolved |
| CAL-01 | D-4/DTE10 count real KRX trading days backward from exact expiry D=0 | trading-day table; scenario CAL-* | policy rule reflected; dates UNSET |
| DL-01 | Decision Log candidate only; do not directly register/delete | decision_log_candidates_draft.md; this report | 반영됨 |

**누락 건수 판정:** 이 체크리스트는 지시서에서 명시적으로 식별한 핵심 확정 의도 항목을 매핑한 것이다. 각 전략 원문의 모든 문장을 의미 단위로 전수 검증한 결과는 아니므로 전체 원문 대비 누락 0건을 확정하지 않는다. 상태는 `NOT_VERIFIED`; scenario/REAL_VTS replay는 NOT_RUN.
## 최신 U-register 상태 (2026-10-13)
- U38 해결: 기존 v0.4 파일명과 v0.3 제목의 불일치는 원본을 바꾸지 않고 후속 신규 버전에서 정렬.
- U39 해결 경로 지정: boundary table 생성; 실제 D-4/DTE10 날짜는 공식 KRX calendar + Option Master 미확보로 UNSET.
- U40 해결: S5 30분 종료 정책 사용자 승인; runtime NOT_RUN.
- U41 미해결: S5 whipsaw definition은 제안/설정 후보이며 REAL_VTS replay로 확정해야 함.
- U42 정책 해결: No.956 보존; basis/source identity 충돌 시 S3 BLOCKED. 실제 호환성은 미검증.
- U43 해결: S6 no same-day retry under the confirmed zero-fill/both-cancel condition; runtime NOT_RUN.
- U44 미해결: common quote freshness/depth/spread thresholds UNSET/BLOCKING.
- U45 신규: individual code-intent-diff files were found for S1/S2 only; S3-S9 per-strategy code-intent diff evidence unavailable in the local docs directory. Keep source-to-code mapping NOT_VERIFIED.

## 1-B. 전략별 델타 대조표 — 재개 점검 결과 (2026-10-13)

| 전략 | 최신 명세/델타 입력 | 반영된 변경 | 미반영·충돌·검증 한계 |
|---|---|---|---|
| S1 | strategy_1_tail_defense_spec_v0.4.md, code-intent diff v0.4, U28/No.1238 | 옵션 short-strike offset과 ATM 재중심화 의도 반영 | 실제 코드 차이·hedge trigger·D-4 실행은 미검증 |
| S2 | v0.4, matrix delta v0.5, trace delta v0.2, scenario delta v0.2, code-intent diff v0.3 | 취소 확정 후 fills/positions 대사, 잔여 목표량만 재주문 | 네 개 leg의 실제 동시/부분체결·restart replay 미실행 |
| S3 | v0.3, No.1237, No.956 | enabled=false, capital_gate_min=null; No.956 정의 보존 | 개별 code-intent diff 파일 없음; No.956 scope 충돌은 S3 BLOCKED |
| S4 | v0.3 | enabled=false, capital_gate_min=null; Greeks/futures ownership gate 유지 | 개별 code-intent diff 및 authoritative Greek/futures role evidence 없음 |
| S5 | v0.4, matrix delta v0.5, trace delta v0.4, scenario delta v0.4 | 30분 종료·hedge/reversal·whipsaw 후보 반영 | whipsaw cycle은 제안 상태; REAL_VTS replay 전 확정 금지 |
| S6 | v0.4 신규 초안 (v0.3 보존) | 10분 무체결 + CALL/PUT 양쪽 취소 완료 + fills/positions 대사 후 당일 재시도 금지 | 런타임 상태 저장·cancel/fill race·late fill 미검증 |
| S7 | v0.3, 통합 matrix/trace/scenario | 월·목 독립 세트, 15:00 KST까지 retry 정책 유지 | 개별 code-intent diff 없음; cutoff 경계/복수 set replay 미실행 |
| S8 | v0.4, No.1235/No.1239 및 기존 delta 내용 | DTE10 이상, 200,000원 예산 gate 폐기, 3거래일 retry window | 개별 code-intent diff 없음; expiry/calendar boundary 미확정 |
| S9 | v0.4, matrix delta v0.6, trace/scenario delta v0.4 | S1 풋 보험, D-4 11:00, S1→S9 청산 순서, rank-3 대기/재확인 | 개별 code-intent diff 없음; actual expiry/calendar/liquidity threshold 미확정 |

증거 경계: docs/strategy_specifications에서 개별 code-intent diff 파일은 S1/S2만 확인됐다. S3–S9 코드-의도 대조표는 입력 증거가 없으므로 만들었다고 주장하지 않는다. 해당 전략의 코드 대조는 NOT_VERIFIED이며, 이 누락을 해결한 것으로 취급하지 않는다.

## Resolution paths for the four remaining items (current status)

| Item | Type | Resolution path | Current status / gate |
|---|---|---|---|
| D-4 / DTE10 trading-day boundaries (U39) | Data acquisition | Obtain the official KRX trading/holiday calendar and exact option expiry YYYYMMDD from authoritative Option Master; record source URL, retrieval time and SHA-256; count actual KRX trading sessions with expiry D=0 and exclude holidays | UNSET/BLOCKED; candidate dates in the boundary table are not executable |
| S5 whipsaw definition (U41) | Verification | Keep the currently described completed hedge-reversal cycle as a candidate; replay event-ID deduplication, two-cycle cutoff, partial/late fills and day reset against REAL_VTS before user approval | PROVISIONAL; do not mark confirmed |
| S6 same-day retry (U43) | User intent resolved; runtime verification pending | No same-day retry after 10 minutes without fills once both CALL and PUT orders are confirmed cancelled and fills/positions reconciled; separately test late fills, cancel race, restart and persisted no-retry fence | Intent confirmed; runtime/replay NOT_RUN |
| Common quote freshness/liquidity limits (U44) | Data acquisition + verification | First resolve supported KIS VTS option-book source/capability; capture multi-day/multi-contract source and receive timestamps, update-interval distribution, quote age, depth, spread, and 5th/6th strike OI/volume/remaining quantity; then derive candidate thresholds and request explicit approval | UNSET/BLOCKING; null values block new entries |

No threshold, expiry date, or strategy approval is inferred from missing evidence. No.1157 subscription-rotation requests are not broker ACK proof; No.1232 freshness/coverage evidence remains insufficient.


## KIS_SINGLE_SOURCE_UPDATE_20261014 — 공통 데이터 계약(초안)

이 추가 사항은 데이터 입력 계약 초안일 뿐 Strategy 1~9의 로직 승인 또는 구현 허가가 아니다.

1. Strategy 1~9의 시장 데이터·옵션/선물 식별·exact 만기·호가·시세는 KIS 출처 및 검증된 공통 데이터 경계에서 공급한다.
2. 마스터의 월 라벨 `YYYYMM` 또는 주 라벨 `YYMMWn`은 exact 만기로 승격하지 않는다. 계약별 KIS REST `futs_last_tr_date`가 검증되고 provenance가 연결된 경우에만 exact expiry를 제공한다.
3. 월물/월요일 위클리/목요일 위클리와 콜/풋/행사가/표준·미니 구분은 KIS 마스터 코드와 ASCII 라벨이 서로 일치할 때만 제공한다. 불일치 유형은 제외한다.
4. 승수는 관측한 KIS 마스터에 명시 필드가 없으므로 현재 `UNSET`이다. 하드코딩된 250,000/50,000을 KIS 권위 출처로 표현하지 않는다. 승수 미확정 시 승수 의존 계산은 fail-closed 한다.
5. 거래일·휴장일 연간 범위가 검증되지 않으면 D-4, DTE10, 만기 전 종료 시점 및 거래일 게이트는 `BLOCKED`이다. 주말만으로 거래일을 추정하지 않는다.
6. 주문·체결·위험관리·전략별 상태 전이는 본 초안에서 변경하지 않는다. 모든 전략 변경은 신규 상세 명세 검증과 사용자 승인 이후 별도 단계에서 진행한다.

 
## Directive F common-data addendum (2026-10-14; draft / not strategy approval)
- This addendum changes no Strategy 1-9 signal, threshold, risk limit or order path.
- Exact expiry identity requires KIS REST futs_last_tr_date with source time, TR/path, field and response hash; month/week labels never become YYYYMMDD.
- Strategy subscription requirements must be emitted by a separately validated selector. The planner only validates identity/freshness and capacity; it does not infer ATM, legs or signals.
- Unknown trading calendar, stale master (>24h), missing exact-expiry provenance, missing required quote channel or exceeded subscription capacity must block the affected strategy stage.
- S3/S4 remain intended disabled. Mini-futures feeds are permitted only when S3/S4 are enabled; S5's existing mini-futures dependency remains an unresolved conflict, not a new approval.