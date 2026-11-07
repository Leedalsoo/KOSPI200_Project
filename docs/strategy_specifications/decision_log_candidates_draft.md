# Decision Log 등록 후보 초안 — 사용자 승인 전 미등록

- 작성일: 2026-10-13
- 상태: draft / unverified / unapproved
- 이 문서는 후보만 작성한다. Decision Log에는 등록하지 않았다.
- 기존 Decision Log는 삭제하지 않는다. 폐기 상태 변경은 항목 식별·근거·대안 작성 후 별도 승인 필요.

## 등록 후보

| 후보 ID | 결정 내용 | 근거 | 영향 범위 | 등록 전 조건 |
|---|---|---|---|---|
| CAND-01 | 과거 문서는 역사적 증거이며, 새 명세의 사용자 승인 버전만 구현 기준으로 사용 | 공통 지시, 2026-10-13 | S1~S9 전체 | 사용자 통합 초안 검토 |
| CAND-02 | S1: 상승 2.5pt마다 이전 기준점−7.5pt PUT, 하락은 이전 기준점+7.5pt CALL; strike 계산 뒤 ATM 기준점 갱신 | U28 / No.1238 | S1, matrix, traceability, scenario | 명세 반영 확인; 구현 승인 별도 |
| CAND-03 | S2: 취소 확정 및 실제 fills/positions 대사 후 잔여 목표 수량만 재주문 | 사용자 직접 지시, 2026-10-13 | S2/OMS | broker cancel/fill lifecycle 검증 |
| CAND-04 | S8: DTE≥10 거래일 진입; 200,000원 예산 게이트 폐기; 10분 timer와 3거래일 재시도 창 | 사용자 직접 지시, 2026-10-13 | S8/calendar/OMS | calendar boundary 검증 |
| CAND-05 | S9: D-4 11:00 KST 청산 lifecycle; 동시 만기 S1→S9; rank 3도 비유동이면 대기·재확인 | 사용자 직접 지시, 2026-10-13 | S1/S9/calendar/OMS | calendar/quote 검증 |
| CAND-06 | S5 whipsaw는 거래소 공통 사건 수가 아니며 전략별 기준을 실제 price/fill replay로 검증 | 사용자 지시, 2026-10-13 | S5 | replay 후 별도 승인 |
| CAND-07 | S3/S4는 enabled=false, capital_gate_min=null로 보류 유지 | 사용자 지시, 2026-10-13 | S3/S4 | readiness gate 및 별도 해제 승인 |
| CAND-08 | 공통 OMS는 주문 상태·체결·포지션을 분리하고 cancel race/partial/late fill/restart를 대사 | 공통 지시 | multi-leg strategies | runtime evidence |
| CAND-09 | quote/contract identity/account risk 미검증 시 fail-closed | 공통 지시 및 No.1232 | S1~S9 | authoritative data/risk enforcement evidence |

## No.956 — 적용 범위 충돌 후보(결정 아님)
No.956 선물-지수 basis 정의는 이 작업에서 변경하지 않는다. S2 basis feature threshold >0.3의 단위/부호/source와 S3 신호 계산이 같은 정의를 쓰는지 실제 source field와 대조한다. 차이가 있으면 No.956을 조용히 바꾸지 않고, 사용자 확인 전 S3를 보류한다. “폐기”는 현재 제안하지 않는다.

## 역사 항목 폐기 제안(실행 안 함)
- No.1168 BUY2는 재사용 금지. 실제 기존 항목과 상태를 확인하지 않고 수정하지 않는다.
- 과거 S9 overnight PUT+CALL/straddle-sale wording은 식별된 Decision Log 항목이 있고 신규 기준과의 관계가 확인된 경우에만 “폐기됨” 변경 후보로 제안한다. 삭제하지 않는다.
- No.956은 범위 충돌 증거가 확보되기 전 폐기 제안 대상이 아니다.

## 등록 게이트
사용자가 후보 ID와 최종 문구를 명시적으로 승인하기 전까지 Decision Log 생성/수정 금지. 이 작업에서는 등록하지 않았다.


## 사용자 확인 결과 2026-10-13
네 항목 모두 예로 승인됨. 이는 정책 결정이며 코드 구현/테스트/REAL_VTS/실거래 승인은 아님.

1. S5 30분 종료: 신규 진입 중단, 미체결 취소 완료 확인, 체결 및 포지션 대사. 기존 포지션은 별도 승인된 청산/위험 규칙만 적용한다.
2. S1/S9 D-4: S1 청산 완료 확인 -> S9 목표 수량 재계산 -> 대기 매수 취소 완료 및 체결/포지션 대사 -> 실제 남은 S9 lot 청산. 요청/접수만으로 완료를 간주하지 않는다.
3. No.956/S3: 공식 No.956 베이시스를 임의 변경하지 않는다. 정의/단위/source identity가 충돌하면 S3는 BLOCKED 유지.
4. 버전: S1/S2/S5/S8/S9 파일명 v0.4를 버전 후보로 유지한다. 원본 제목 v0.3은 수정하지 않고 이후 신규 버전에서 파일명/제목을 일치시킨다.

U38/U40/U42의 정책 처리 방침은 해결됨. 런타임 검증은 미완료. D-4/DTE10 실제 날짜는 자료 미확보로 UNSET; S5 whipsaw는 검증형 후보; S6 재시도 정책은 해결됐으나 런타임 미검증; 공통 quote freshness/liquidity 임계값은 UNSET/BLOCKING.

## 추가 등록 후보 — 2026-10-13 (등록하지 않음)

| Candidate | 제안 문구 | 근거 | 상태/게이트 |
|---|---|---|---|
| CAND-10 | S6: 장 시작~11:00 KST 진입 감시; 10분 내 무체결이며 CALL/PUT 양쪽 주문이 취소 완료되고 체결 대사가 끝나면 당일 재시도 없음 | 사용자 직접 확정, 2026-10-13 | 정책 의도 확정; S6 v0.4 초안, runtime/replay NOT_RUN |
| CAND-11 | D-4/DTE10은 exact Option Master `YYYYMMDD`와 공식 KRX 거래일 달력으로 계산하고 휴장일은 제외 | No.1119 및 사용자 지시 2026-10-13 | 계산 규약 후보; 자료 미확보, actual dates UNSET |
| CAND-12 | Quote freshness/liquidity limits remain UNSET/BLOCKING until source capability, timestamp distribution, depth and 5th/6th strike liquidity evidence are adequate | No.1157 / No.1232, 2026-10-13 | 등록 후보; 숫자 미확정, runtime enforcement unverified |

기존 Decision Log에는 어떤 항목도 직접 등록·수정하지 않았다. No.956의 공식 정의를 변경/폐기하는 안건은 실제 충돌의 authoritative evidence가 확보되기 전에는 별도 확정 제안으로 올리지 않는다. 현재 정책은 충돌 시 S3를 BLOCKED로 유지하는 것이다.

## S6 retry intent — candidate status distinction

The S6 same-day no-retry behavior is user-confirmed intent, not an implementation approval. Keep the candidate item as an evidence trail; implementation/runtime enforcement remains unverified until restart, cancel-race, late-fill and REAL_VTS replay gates pass. S7 and S8 retain separate retry windows.


## KIS_SINGLE_SOURCE_UPDATE_20261014 — Decision Log 등록 후보(미등록/초안)

다음 항목은 결정로그에 직접 등록하지 않았다. 사용자 검토·승인 전까지 모두 후보 초안이다.

- KIS 단독 런타임 데이터 정책: KRX 런타임 fallback/보정/우선순위 제거; KRX 자료는 역사적 참고·fixture 전용.
- KIS 마스터 수명주기: KST 거래일별 최대 1회 refresh, append-only 원본/manifest, SHA-256, 24시간 TTL, 만료·손상 시 차단.
- exact 만기 provenance: 단축코드별 `futs_last_tr_date` + 요청/응답 시각 + endpoint/TR/응답 hash/master hash 저장; YYYYMM/YYMMWn 추정 금지.
- 휴장일 정책: 완전한 KIS 연간 커버리지 → 사용자 승인 목록 → UNKNOWN; KRX cache를 런타임 fallback으로 사용하지 않음.
- 승수 authority: KIS 공식 권위 출처 확인 전 `UNSET`; 기존 코드 상수만으로 authoritative 값을 주장하지 않음.

