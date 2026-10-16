# Strategy 1~9 교차 전략 충돌 검토표 (draft)

- 작성일: 2026-10-13
- 상태: draft / unverified / unapproved
- 이 문서는 충돌 검토 초안이며 미확정 정책을 임의 확정하지 않는다.

## 1. 필수 상호작용 11항목

| # | 충돌/상호작용 | 현재 결론 | 상태/다음 확인 |
|---|---|---|---|
| 1 | S1 D-4 전량 청산 ↔ S9 D-4 11:00 및 우선순위 | S1 → S9. S1 청산으로 S9 target=0이면 S9 pending buy 취소·대사, 이미 체결된 S9 lot은 별도 청산. 같은 lot 중복 청산 금지 | 정책 일치; runtime 검증 NOT_RUN. S1/S9 lot linkage 및 D-4 replay 필요 |
| 2 | D-4/DTE10 거래일 계산 | 거래일 기준. KRX calendar source는 공식 자료, 정확한 expiry는 Option Master. 경계 포함 규약은 UNSET | 정책 확정, 계산 BLOCKED. 휴장/주말/만기일 경계 테스트 필요 |
| 3 | S1 short ↔ S6/S7/S8 long 같은 계약 | strategy/group/leg provenance로 각 fill을 귀속. 계좌 netting/margin 상계는 증거 없이는 가정하지 않음 | 동일 계약 동시 롱/숏 및 broker margin snapshot 비교 필요 |
| 4 | S6/S7/S8 동시 보유 | 일물·주물·월물 및 S7 월/목 두 세트를 별도 group/run/expiry로 식별 | 합산 margin은 BLOCKED. overlap/동일 행사가 시나리오 필요 |
| 5 | S2 4레그 ↔ S8 월물 양매수 | 같은 계약이라도 각 전략 fill을 따로 귀속. S2 fill을 S8 target fill로 대체하지 않음 | 부분체결/restart/position reconciliation 검증 필요 |
| 6 | 계좌/전략 공통 위험 한도 | 공통 risk layer가 계좌 자본, 계좌 최대손실, margin 이용률, 전략별 최대 프리미엄을 소유. null/집행 미검증이면 차단 | 값과 runtime enforcement BLOCKED; authoritative balance/margin 및 risk path 확인 |
| 7 | 10-minute opposite-leg timer vs one-leg fill and retry | Common OMS terminal-state reconciliation applies; S6: no same-day retry after 10-minute zero-fill timeout once both CALL/PUT cancels are confirmed and fills/positions reconciled; S7: Mon/Thu set retries through 15:00 KST; S8: three-trading-day window, day-three cutoff 15:00 KST; S2: cancel-confirm + fill/position reconciliation before remaining-target retry | Policy differences reflected; S6 persistence/cancel-race/late-fill and S7/S8 boundary replay NOT_RUN |
| 8 | S5 30분 종료·휩소와 S1/S9 동시 노출 | whipsaw는 전략 자체 정의이며 후보는 미검증. 사용자 승인: 신규 진입 중단·미체결 취소 확인·체결 대사; 기존 lot은 별도 승인 규칙만 적용. 전략별 lot 분리, 계좌 위험은 공통 적용 | session_end_action, reversal min, event identity, REAL_VTS fill replay 필요 |
| 9 | 공통 지정가·취소 경합·부분체결·호가 공백 | preflight → limit order → working/partial → cancel request → cancel confirmed → fill/position reconcile → remaining target only. 상태 불명은 신규 주문 차단 | 정책 통일, KIS VTS broker behavior 미검증 |
| 10 | 용어/S1 기준점 규칙 | S9 명칭은 S1 풋 보험. 폐기된 스트래들 매도 용어 사용 금지. S1은 직전 기준점 ± offset으로 strike 산출 후 새 ATM으로 기준점 갱신 | 신규 통합표/추적표/시나리오에 반영; 충돌 문구 검색 필요 |
| 11 | S3/S4 보류와 다른 전략의 futures | S3/S4 enabled=false, capital_gate_min=null. 이 상태가 다른 전략의 선물 사용을 자동 금지하지는 않음. No.1151 역할 구분 적용, futures→options 수량 대체 금지. No.956 정의는 승인 없이 변경 금지 | No.956 exact scope와 S2/S3 basis field/unit/sign 비교. 불일치면 사용자 확인 전 S3 BLOCKED |

## 2. 주문 상태 불변 조건
- 거래소에서 취소 완료된 주문 자체를 유지할 수는 없다. “레그를 유지”한다는 것은 전략의 목표 노출 의도를 보존한다는 뜻이다.
- 대체 주문 전에 취소 확정, 취소 중/후 늦은 체결, 부분체결 및 실제 포지션을 대사한다.
- 잔여 재주문 수량 = 목표 수량 − 대사된 실제 open 수량 − 같은 목표에 대해 아직 working인 수량. client order ID는 중복 방지 가능해야 한다.
- broker position snapshot과 execution ledger가 불일치하면 RECONCILIATION_REQUIRED, 추가 노출 차단.
- stale/missing/crossed/identity-mismatch quote 또는 source timestamp 의미 불명 시 주문 차단.
- 타이머 만료만으로 반대 레그가 미체결이라고 단정하지 않는다.

## 3. No.1232 데이터 차단 근거
관측 77,310 WS frames: H0IFCNT0 64,099, H0UPCNT0 12,575, H0IOCNT0 636, H0IOASP0 option order-book frames 0. REST: 4,876 SUCCESS, 789 DUPLICATE, 140 BLOCKED(139 HTTP 500 EGW00201 rate limit, 1 timeout). WS bsop_hour는 HHMMSS로 관찰됐고 canonical observed_at는 receive time. 이 결과만으로 quote freshness/liquidity를 확정할 수 없다.

## 4. 기존 확인 질문의 답변 기록 — 새 질문 없음
기술적으로 검증할 수 있는 수치는 질문하지 않고 UNSET 설정으로 둔다.

1. **S5 30분 종료:** 사용자 답변 2026-10-13 = 예. 신규 진입 중단, 미체결 취소 완료 확인, 체결 대사; 기존 포지션은 별도 승인된 청산/위험 규칙만 적용.
2. **S1/S9 D-4 실행 순서:** 사용자 답변 2026-10-13 = 예. S1 청산 완료 확인 → S9 목표 수량 재계산 → 대기 매수 취소 완료/체결 대사 → 실제 잔여 S9 lot 청산.
3. **No.956 범위 충돌:** 사용자 답변 2026-10-13 = 예. 공식 No.956 정의를 임의 변경하지 않으며, S3와 충돌하면 S3를 BLOCKED로 유지한다.


## 5. U-register references
- U28: resolved as user intent; implementation remains unverified.
- U38: requested filename versions conflict with embedded title versions for S1/S2/S5/S8/S9.
- U39: D-4/DTE10 trading-day boundary convention UNSET.
- U40: S5 session-end handling requires user choice.
- U41: S5 whipsaw definition is proposed and unverified.
- U42: No.956 basis scope comparison; preserve existing definition if conflict.
- U43: S6 retry policy resolved by user on 2026-10-13; 10-minute zero-fill plus both orders confirmed cancelled means no same-day retry. Runtime validation NOT_RUN.
- U44: common quote freshness/liquidity threshold blocked by missing option order-book evidence.
- U45: individual strategy code-intent-diff source coverage incomplete; S3-S9 mapping NOT_VERIFIED.


## 사용자 확인 결과 2026-10-13
네 항목 모두 예로 승인됨. 이는 정책 결정이며 코드 구현/테스트/REAL_VTS/실거래 승인은 아님.

1. S5 30분 종료: 신규 진입 중단, 미체결 취소 완료 확인, 체결 및 포지션 대사. 기존 포지션은 별도 승인된 청산/위험 규칙만 적용한다.
2. S1/S9 D-4: S1 청산 완료 확인 -> S9 목표 수량 재계산 -> 대기 매수 취소 완료 및 체결/포지션 대사 -> 실제 남은 S9 lot 청산. 요청/접수만으로 완료를 간주하지 않는다.
3. No.956/S3: 공식 No.956 베이시스를 임의 변경하지 않는다. 정의/단위/source identity가 충돌하면 S3는 BLOCKED 유지.
4. 버전: S1/S2/S5/S8/S9 파일명 v0.4를 버전 후보로 유지한다. 원본 제목 v0.3은 수정하지 않고 이후 신규 버전에서 파일명/제목을 일치시킨다.

U38/U40/U42/U43의 정책 처리 방침은 해결됨. 런타임 검증은 미완료. D-4/DTE10 실제 날짜는 자료 미확보로 UNSET; S5 whipsaw는 검증형 후보; S6 재시도 정책은 해결됐으나 런타임 미검증; 공통 quote freshness/liquidity 임계값은 UNSET/BLOCKING.

## 최신 11개 충돌 항목별 결론 — 2026-10-13 (draft)

| # | 검토 영역 | 결론 | 상태/증거 요구 |
|---|---|---|---|
| 1 | S1 D-4 전량 청산 ↔ S9 D-4 11:00 | 승인된 순서: S1 청산 완료 확인 → S9 목표 수량 재계산 → 대기 매수 취소 완료·체결 대사 → 실제 잔여 S9 lot 청산. S1 target=0이 S9 lot 청산 완료를 뜻하지 않는다. 동일 lot 중복 청산 금지. | 정책 확정; exact expiry/calendar와 broker-position replay NOT_RUN |
| 2 | D-4/DTE10 거래일 규약 | 만기일 D=0; 실제 KRX 거래일만 역산. exact `YYYYMMDD`는 Option Master. 후보표 `trading_day_boundary_table_draft.md` 작성. | 경로 해결; 공식 연간 달력·Option Master 미확보로 날짜 UNSET/BLOCKED |
| 3 | S1 매도 strike ↔ S6/S7/S8 매수 strike | 전략별 group/leg/expiry/contract identity로 분리 귀속. 계좌 상계/증거금 offset은 브로커 margin snapshot과 규정 증거 없이는 가정하지 않는다. | 설계 규칙 있음; same-contract lots와 actual margin evidence NOT_RUN |
| 4 | S6/S7/S8 동시 보유 | 일물·주물·월물, S7 월/목 두 세트를 별도 group/run/expiry로 관리; 계좌 risk는 전체 합산. | provenance 규칙; 동일 strike/expiry overlap 및 합산 margin 검증 BLOCKED |
| 5 | S2 4레그 ↔ S8 월물 양매수 | 같은 계약이어도 전략별 lot attribution은 유지하고, 실제 execution IDs·remaining qty를 대사한다. net account position만으로 전략별 소유권을 추정하지 않는다. | 별도 strategy ledger 필요성은 설계상 요구; 구현 증거 NOT_RUN |
| 6 | 계좌/전략 공통 위험 한도 | 공통 config owner는 account risk gate; 전략별 premium/max-loss/qty caps와 계좌 총 premium/margin/stress-loss caps를 별도 키로 둔다. 필수 값 null/UNSET이면 신규 주문 차단. | 값·실행 경로 미검증; config schema에 정의, runtime enforcement BLOCKED |
| 7 | 10분 timer/한쪽 레그 보유/재시도 | OMS 상태 용어는 통일하되 재시도 정책은 전략별. S6: 10분 무체결 + 양쪽 취소 완료면 당일 재시도 없음. S7: 월·목 각 세트 15:00까지 retry. S8: 월물 시작 후 3거래일. S2: 취소 완료·체결 대사 후 잔여량만 재주문. | 정책 분리 반영; replay NOT_RUN. 한쪽 fill은 무체결/양쪽 취소와 구분 |
| 8 | S5 30분 종료 ↔ S1/S9 보험 lot | S5 신규 진입 중단, 미체결 취소 완료 확인, 체결 대사. 기존 포지션은 별도 승인된 청산/위험 규칙만 적용; 임의로 전량 청산하거나 계속 보유하는 규칙을 추가하지 않는다. | 사용자 승인 정책; 상호작용/계좌 위험 replay NOT_RUN; whipsaw는 검증형 후보 |
| 9 | 공통 주문 집행 | 모든 전략은 같은 상태어휘 사용: ORDER_SUBMITTED → ACK/WORKING → PARTIAL/FILLED 또는 CANCEL_REQUESTED → CANCEL_CONFIRMED/REJECTED/UNKNOWN → RECONCILIATION_REQUIRED. cancel request ≠ confirmed; late/partial fills 대사 전 재주문 금지. | 문서 규약; runtime enforcement NOT_RUN/BLOCKED |
| 10 | 용어/S1 기준점 | S9는 “S1 풋 보험”; 폐기된 “스트래들 매도” 및 No.1168 BUY2 미사용. S1 strike는 직전 기준점 ∓ short_offset_pt로 계산 후 기준점을 새 ATM으로 갱신. | 문서 대조 반영; 전수 문자열 검사/구현 검증 NOT_RUN |
| 11 | S3/S4 보류 ↔ 다른 전략의 선물 사용 | S3/S4는 `enabled=false`, `capital_gate_min=null`로 보류. No.1151의 선물 역할 분류 유지; 옵션 계약 수로 선물 수량 대체 금지. No.956과 S3 signal이 충돌하면 No.956을 바꾸지 않고 S3 BLOCKED. | 정책 확정; official basis definition/source identity와 margin/role mapping 검증 BLOCKED |

## U-register update
- U38 처리 방침 해결: 파일명 v0.4는 버전 후보, 제목이 v0.3인 원본은 수정하지 않고 후속 신규 버전에서 일치.
- U39 해결 경로 지정: trading-day boundary table 작성. 실제 expiry/calendar 자료 미확보이므로 계산은 여전히 UNSET/BLOCKED.
- U40 해결: S5 30분 종료 정책 사용자 승인; runtime verification NOT_RUN.
- U41 미해결: S5 whipsaw event definition is a proposal/config candidate; decide only after REAL_VTS replay.
- U42 정책 해결: No.956 공식 정의를 보존하고 충돌 시 S3 BLOCKED; actual compatibility unresolved.
- U43 해결: S6 retry policy user-confirmed; 10-minute zero-fill + both orders confirmed cancelled => no same-day retry. Implementation/replay NOT_RUN.
- U44 미해결: quote freshness/liquidity numeric thresholds remain UNSET/BLOCKING; evidence plan defined.
- U45 신규: strategy-specific code-intent-diff source coverage is incomplete in the local docs directory (individual diff files were found for S1/S2 only); S3-S9 source-to-code mapping must remain NOT_VERIFIED until separately evidenced.

사용자에게 새 질문 없음: 남은 수치·달력·유동성 기준은 검증 자료로 해결하며, 전문적 임계값을 추측해 묻거나 확정하지 않는다.

## Superseding correction — conflict check #7 (2026-10-13)

The earlier row #7 text stating that S6 retry policy was unresolved is superseded by the user's explicit confirmation dated 2026-10-13. Correct outcome: S6 has no same-day retry after 10 minutes with zero fills, once both CALL/PUT orders are confirmed cancelled and fills/positions are reconciled. The user-intent decision is resolved; runtime persistence, cancel race, late fill and restart behavior remain NOT_RUN. S7 retries on its Monday/Thursday set through 15:00 KST; S8 uses a three-trading-day window with a 15:00 KST cutoff on day three. These windows are intentionally different. All other conflict-check conclusions remain draft/unverified.
