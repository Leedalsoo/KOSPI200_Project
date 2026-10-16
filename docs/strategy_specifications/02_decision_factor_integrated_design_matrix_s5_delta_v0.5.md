# Strategy 1~9 통합설계표 — Strategy 5 갱신 초안 v0.4

- 작성일: 2026-10-12
- 상태: draft / unverified / unapproved
- 기준: S5 명세 v0.3 초안; 기존 matrix v0.3/v0.4 파일은 보존
- 범위: S5 관련 delta only. 기존 매트릭스 원문 레지스터와 병합 전 원문 대조가 필요하다.

## S5 F01–F29 변경 요약
- 확정 의도: F01, F02, F14–F17, F22, F24–F25, F27–F28.
- 설정 이관 후 검증: F03, F05, F10–F12, F18–F20, F29.
- 사용자 확인/authoritative evidence 필요: F04, F06–F09, F13, F21, F23, F26.
- 상세 항목별 분류와 근거는 `strategy_5_gap_divergence_spec_v0.3.md` §4에 있다. 이 요약은 기존 통합 매트릭스의 전체 F 행을 대체하지 않는다.

## S5 목표 구조 (신규 초안)
- 진입: abs(open - previous_close) >= min_gap_pt이면 갭 상승 CALL BUY / 갭 하락 PUT BUY, ATM. 임계값은 설정·REAL_VTS 검증 후 확정.
- advance 전 반전: hedge_reversal_pt 충족 시 반대 옵션 hedge_contracts=1 매수.
- advance 후 반전: 갭 크기 × reversal_ratio를 기준으로 이익 청산. reversal_min_pt와 max 조합은 검증 후보.
- 재반전: 헤지 청산 후 원 옵션의 이익을 실제 option P&L/trigger로 판정.
- whipsaw_limit=2 도달: 당일 신규 거래 전면 중단, 포지션 청산 절차.
- session_minutes=30. session_end_action null이면 신규 거래/종료 동작을 임의로 결정하지 않고 fail-closed.
- mini futures 5계약은 과거 구현 잔재/폐기 대상이며 S5 목표 수익원이나 옵션 동일수량 변환 기준이 아니다.
- No.1168 BUY2는 폐기되었고 재사용하지 않는다.

## S5 상호작용 I01–I16
| ID | 연결 | 통합 설계 요구 |
|---|---|---|
| I01 | S5-S1 hedge overlap | 계약·방향·expiry·position provenance 기반 중복 확인 |
| I02 | S5-S9 overnight/event overlap | 세션 종료 잔여 포지션을 S9 상태로 간주하지 않고 대사 |
| I03 | S1/S5/S9 premium | actual fills/open qty 기준 합산, 원장 중복 합산 금지 |
| I04 | account margin/capital | authoritative capital/margin 없으면 신규 진입 차단 |
| I05 | common risk/max loss | option hedge를 futures 동일수량/동일위험으로 간주 금지 |
| I06 | Option Master | exact expiry/strike/type/multiplier identity 검증 |
| I07 | MarketDataHub | official open/previous close/quote timestamp freshness 검증 |
| I08 | OMS | group plan과 각 leg order state 분리 |
| I09 | ExecutionReport | execution_id/fill/remaining qty 대사 |
| I10 | PositionLotStore | partial close/hedge close의 잔여 lot 보존 |
| I11 | Calendar/session | KST official session start와 30분 window |
| I12 | Config registry | config version/hash 실행별 기록 |
| I13 | restart/recovery | reconciliation 전 신규 주문 금지 |
| I14 | whipsaw | 2회 도달 후 당일 재진입 금지 |
| I15 | P&L/read model | actual option premium P&L과 account P&L 구분 |
| I16 | REAL_VTS evidence | REAL_VTS/DERIVED_SCENARIO/SYNTHETIC/VIRTUAL provenance 분리 |

## U01–U15 / G 게이트 상태
이 delta는 기존 matrix에 존재하는 U/G 레지스터 원문 전체를 확인했다고 주장하지 않는다. S5 명세 v0.3 §7의 U01–U15와 G01–G10은 신규 매핑 초안이다. matrix v0.4 원문 레지스터와 대조해 ID 충돌/누락을 확인하기 전에는 완전성 PASS가 아니다.

- 설정 이관: U02, U03, U04, U05, U06, U07.
- 사용자 확인 필요: U01, U08, U09, U11, U12, U13, U14, U15.
- 확정 방향이나 구현/검증 필요: U10.
- G01–G10: 모두 미충족. 상세 차단 사유는 S5 v0.3 §7 참조.

## 판정
초안 작성만 완료. matrix 본문과 레지스터 전체 병합 검증은 BLOCKED/미완료. 사용자 승인 및 코드 구현을 의미하지 않는다.

## 정정 — 기존 U/G/I ID 보존 (2026-10-12)

원본 matrix v0.4의 U01–U15, I01–I16, G01–G12를 확인했다. 아래가 원래 ID 기준의 S5 갱신이며, 본 파일 앞부분의 임시 U01–U15 매핑은 **폐기하고 이 절을 우선 적용**한다. 기존 ID를 재번호화하지 않는다.

### U 레지스터의 S5 관련 항목
| ID | 기존 항목 | S5 분류 | 처리 |
|---|---|---|---|
| U05 | S5 Futures role/qty/terminal sequence | 확정 해결(의도), 검증 필요 | 선물 5는 헤지 수단, 옵션 헤지로 대체; 반대 옵션 1계약; 휩소 2회; advance 전/후 반전 분기. runtime/cost 미검증 |
| U10 | 계좌 총자본 및 전략/계좌 위험 수치 | 설정 이관, 사용자 확인 필요 | config schema 및 검증 프로토콜, 실제 숫자 미확정 |
| U11 | 공통 주문/부분체결/취소/재시작 지속성 | 설계 방향 해결, 증거 미충족 | S5 leg별 partial/reject/cancel-race/restart 시나리오 필요 |
| U12 | 계좌 전체 노출/상관/상계 정책 | 사용자 확인 필요 | S1/S9 포함 premium·margin·stress 합산, 중복 제거 |
| U13 | authoritative P&L/fee/multiplier source | 사용자 확인 필요 | 실제 option fills/marks/cost source |
| U14 | exact expiry/session/rollover | 사용자 확인 필요 | 30분 종료 이후 position/expiry 정책 |
| U15 | Shrimp Resume Context access/update | UNAVAILABLE | 이 세션에서 관련 도구가 노출되지 않아 확인/갱신 불가 |
| U01–U04, U06–U09 | S1–S4 및 S6–S9 전용 미결 | 변경 없음 | S5 결정으로 전파하지 않음 |

### G01–G12
| Gate | S5 분류 | 증거/조건 |
|---|---|---|
| G01 목적/경제적 역할 | 의도 해결, 구현 미검증 | gap-direction option + opposite-option hedge |
| G02 진입/추가/청산 신호 | 검증값/미완료 | config threshold and boundary tests |
| G03 계약/만기/수량/승수 | 미충족 | authoritative option identity/expiry/multiplier/quote |
| G04 부분체결/거절/취소/timeout | 미충족 | independent leg state and cancel race |
| G05 헤지/재조정/overlay | 의도 해결, runtime 미검증 | option hedge 1; futures 5 removed; BUY2 not reused |
| G06 손절/목표/트레일링/시간청산 | 설정 이관/미완료 | stop/session end null blocks |
| G07 세션/만기/롤오버 | 미충족 | session edge/exit policy/exact expiry |
| G08 자본/프리미엄/최대손실/계좌 위험 | 미충족 | config, authoritative costs, account aggregation |
| G09 실패/재시작/복구 | 방향 확정, 증거 미충족 | reconciliation before any new order |
| G10 요구사항-명세-코드-테스트 추적 | 부분 작성 | all factors to code/test/evidence required |
| G11 source/freshness | 미충족 | open/close/quotes/contracts provenance |
| G12 approval/version boundary | 규칙 확정, 현재 미승인 | v0.3 cannot be implemented before user approval |

### I01–I16 원본 ID 기준 영향
S5 관련: I01 account capital/premium/max-loss/margin; I02 shared Futures identity; I03 option holdings/delta attribution; I04 insurance-pair overlap including S1/S9; I05 multi-leg partial fill/cancel race; I06 strategy/account P&L; I07 expiry/session/overnight; I08 exit priority; I09 freshness; I10 restart/duplicate/state restore; I11 S5 Futures role vs option alternative; I16 editable config consistency. I12(S3), I13(S4), I14(S8), I15(S6/S7/S9 re-entry)는 S5 목표를 바꾸지 않으며 계좌 집계 범위에서만 영향 가능. 원본 ID 유지.

### 신규 S5-U16–S5-U20 (이번 S5 작성에서 발견)
| ID | 모호점 | 상태 |
|---|---|---|
| S5-U16 | whipsaw count event/idempotency definition | 사용자 확인 필요 |
| S5-U17 | ATM tie-break/quote unavailable behavior | 사용자 확인 필요 |
| S5-U18 | simultaneous stop/reversal/profit/session-end priority | 사용자 확인 필요 |
| S5-U19 | hedge close 후 원 옵션 유지/청산/당일 재진입 범위 | 사용자 확인 필요 |
| S5-U20 | authoritative “session start” timestamp semantics | 사용자 확인 필요 |


## S5-U namespace decision amendment (2026-10-12)
- User decision: preserve S1 U-ID values; namespace S5-specific new items as S5-U16 through S5-U20. This appendix controls references in this S5 delta document.
- Documentation-only resolution; no code, test, Git, or Live order action is authorized.

---
## v0.5 — S5 whipsaw count proposal
No exchange-wide standard whipsaw counter was identified in KRX order/trade rules; exchange matching priorities are not a strategy event definition. Proposed S5 event: a real opposite-option hedge fill after the pre-advance adverse trigger, followed by an underlying/futures return to the original gap direction across the configured hedge-reversal boundary. Count once per completed cycle using idempotent event ID; tick noise, option premium-only movement, ACK without fill and duplicate reports do not count. Two confirmed events stop new entry for the day and trigger close of all actual remaining S5 lots. DRAFT / VERIFYING / UNAPPROVED; REAL_VTS replay NOT_RUN.
