# R1 — D1–D6 결정 반영 기록 (2026-10-28)

- 상태: **R1 문서 반영 완료 / 구현·Decision Log 등록은 후속 단계**
- 근거: 사용자 직접 지시(현재 대화), 원격 `Project200/AGENTS.md`, R0 `reports/synth/STATE_SYNC_20261028.md`, Q&A No.1344·No.1354·No.1355
- 작업 범위: 결정의 적용 경계와 후속 단계 인수인계만 기록. 코드·테스트·원본 데이터·설정·스케줄러는 변경하지 않음.
- 장중 가드: 08:29–16:01 KST. 오늘(20261028) raw 파일 내용/해시는 조회하지 않음.

## D1–D6 확정 사항

| ID | 확정 적용 사항 | 적용 경계 / 현재 상태 |
|---|---|---|
| D1 | Synthetic Option Master는 validation-only 전용이다. | `synthetic=true`, `provenance=DERIVED_SCENARIO`, `validation_only=true`, `production_runtime_eligible=false`; identity owner가 해결되지 않으면 `BLOCKED_IDENTITY_OWNER_UNRESOLVED`. Synthetic ID를 Standard production ID로 승격하지 않는다. 기존 구현의 전체 계약 적합성은 후속 검증 전까지 미확정이다. |
| D2 | REAL_VTS 프로파일링은 기존에 확인 가능한 약 10거래일의 원본만 대상으로 한다. | 관측 가능한 필드와 추정 불가 필드를 분리한다. 데이터에서 추정할 수 없는 값은 `assumed: true`와 근거·가정을 명시한다. 원본을 변경하지 않으며 오늘 장중 raw는 접근하지 않는다. R2에서 프로파일 산출물을 만든다. |
| D3 | 고해상도 데이터는 Strategy 5/6의 시간 간격·체결/대기 의미를 검증하는 데 필요한 범위로 제한한다. | 전체 3개월/1년 데이터를 무조건 고해상도로 확장하지 않는다. 용량·실행시간·체크포인트 추정치를 R3 명세에 기록한다. 세부 수치는 측정 전까지 가정/추정으로 표시한다. |
| D4 | 승인된 범위의 변경은 현재 작업 브랜치에서 선택적으로 commit할 수 있다. | unrelated 변경·미추적 파일은 포함하지 않는다. Push는 R7에서 별도 사용자 확인을 받은 뒤에만 한다. 이 R1 단계에서는 commit/push하지 않는다. |
| D5 | UI smoke는 완료 조건에서 제외한다. | 도구 사용 불가 상태는 `BLOCKED_TOOL_UNAVAILABLE`로 기록한다. UI smoke 미실행만으로 R 단계 전체를 실패 처리하지 않으며, 실행하지 않은 것을 PASS로 표시하지 않는다. |
| D6 | 세션 시작·종료 시각은 KIS master 및 실제 관측 증거로 검증한다. | 확인 전에는 08:45 시작, 정규 세션 종료 및 만기일 조기 종료를 확정된 KIS 관측 사실로 취급하지 않는다. 명세에서는 출처별 상태를 `assumed: true`로 표시하고, 실제 근거가 확보되면 별도 검증 결과로 승격한다. |

## 합성 전용 만기 정책 — Decision Log 등록 초안

- 정책 ID: `synthetic-expiry-krx-calendar-v1`
- 적용 범위: `DERIVED_SCENARIO`/validation-only 생성·검증만.
- 월물: 계약월 둘째 목요일, 비거래일이면 이전 거래일.
- 주간 월요일물: 선언된 월별 순번 월요일, 비거래일이면 다음 거래일.
- 주간 목요일물: 선언된 월별 순번 목요일(둘째 목요일 제외), 비거래일이면 이전 거래일. 시리즈 표기가 규칙과 충돌하면 생성 차단.
- 출처/달력: 기존 데이터셋 manifest에 기록된 버전·경로·해시를 유지한다.
- 금지 경계: KRX를 KIS runtime authority, production contract identity 또는 fallback으로 사용하지 않는다. Synthetic contract ID를 Standard ID로 alias하지 않는다.
- 상태: **초안만 준비**. 사용자의 R7 승인 전 Decision Log에는 등록하지 않는다.

## 후속 단계 인수인계

1. **R2**: 기존 REAL_VTS 원본만으로 `reports/synth/real_data_profile.md`, `.json`, `reports/synth/REALISM_COMPARISON.md` 작성. 원본 변경 금지; 오늘 raw 미접근.
2. **R3**: `docs/synthetic_3m_generator_p4_spec.md`를 v0.2로 갱신해 SYN-EVT/SYN-1M/2M/3M/1Y, 월별 체크포인트·분할/일괄 결정성, validation-only Option Master, 세션 시각 가정, Strategy 5/6 고해상도 용량 추정을 명세한다. 구현 전 명세 승인을 별도로 받는다.
3. **R4**: 시간 의존성 스캔과 Replay RPL-01..12 계약·파일 범위·테스트·격리 계획을 먼저 제출한다. Replay 코드 변경 전 별도 승인을 받는다.
4. **R7**: D1–D6 및 합성 만기 정책을 Decision Log에 실제 등록하고, 승인된 파일만 commit한다. Push는 별도 사용자 확인 후 수행한다.

## 검증 및 안전 기록

- R0에서 확인한 기준선: `py -m pytest -q` — 165 passed; 이는 프로젝트 테스트 기준선이며 Strategy E2E PASS가 아니다.
- R1에서 코드 테스트·KIS API·Live/주문/계좌 API·구독 변경·스케줄러 변경을 실행하지 않았다.
- 파일 삭제/이동, stage/commit/push를 수행하지 않았다.
- Decision Log는 수정하지 않았다.