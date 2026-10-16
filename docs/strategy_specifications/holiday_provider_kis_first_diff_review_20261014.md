# Holiday Provider KIS-first Diff Review — 2026-10-14

상태: 코드 차이 검토 / 사용자 승인 대기 / 런타임 연간 달력은 BLOCKED

## 1. 현재 작업 트리와 목표 정책 비교

| 파일/경계 | 이전 정책/위험 | 현재 작업 트리 상태 | 이번 Directive F 변경 | 판정 |
|---|---|---|---|---|
| infrastructure/kis/holiday_provider.py | 기본 auth manager가 환경을 명시하지 않으면 live 기본 설정으로 해석될 수 있음 | KIS read-only holiday endpoint parser; complete-year coverage validation | 기본 auth 생성에 is_vts=True를 명시하고 단위 테스트 추가 | 코드 변경, VTS 전용으로 제한 |
| infrastructure/kis/holiday_fallback_provider.py | 과거 KRX-first fallback이 KIS 단독 정책과 충돌 | KRX runtime provider는 KRX_NON_AUTHORITATIVE로 차단; KIS complete annual → USER_APPROVED list → UNKNOWN | 이 우선순위 변경은 E 이후 현재 작업 트리에 이미 존재했으며, 이번 F에서 재작성하지 않음 | 현재 코드가 정책 방향과 일치하나 API 연간 커버리지는 미입증 |
| application/composition/market_calendar_hub.py | hub가 KRX fallback을 직접 호출하면 KIS 단독 기준 위반 | provider resolution을 공통 hub로 전달; KRX runtime fallback 의존은 금지되어야 함 | 이번 F에서 hub 자체는 수정하지 않음 | 관련 diff의 승인·정합성은 기존 작업 트리 감사 대상으로 보존 |
| core/trading_day_calculator.py | calendar source provenance 없이 날짜 계산하면 미확정 날짜를 사용 가능 | untracked existing file; calendar provider state와 exact expiry를 이용 | D-4 11:00 KST exit-due helper와 timezone-aware 검증 추가 | 단위 테스트 범위; 운영 달력 승인 전 계산은 BLOCKED |
| data/reference/calendar/holidays_2026_draft.json, holidays_2027_draft.json | KRX cache를 runtime authority로 오해할 위험 | 새 초안, DRAFT_USER_REVIEW_REQUIRED, runtime_eligible=false | KRX cache는 draft input only; 사유 UNVERIFIED; SHA-256 보존 | 승인 전 runtime에서 사용할 수 없음 |

## 2. 영향받는 테스트

- tests/unit/test_holiday_fallback_provider_priority.py: KIS-first / KRX runtime fallback 차단을 검증하는 직접 영향 테스트.
- tests/unit/test_kis_holiday_provider_coverage.py: 연간 커버리지 및 VTS auth 기본값을 검증.
- tests/unit/test_synthetic_trading_calendar_expiry.py: 기존 synthetic calendar/expiry boundary 검증; synthetic PASS를 운영 달력 PASS로 해석하지 않음.
- tests/unit/test_trading_day_calculator.py: D-4, DTE10, D-4 11:00 KST 전후, timezone-naive 차단 검증.
- KRX source 관련 과거 조사·fixture 테스트는 보존하되, runtime authority로 승격하지 않는다.

## 3. 실제 API 확인 결과

- CTCA0903R VTS read-only probe는 1회 수행: HTTP 500, rt_cd=1, msg_cd=EGW02006. msg1은 UTF-8 해석에서 읽을 수 없었고, 응답 hash만 보존했다. 한 번의 호출만 수행했으며 재시도하지 않았다.
- 이 응답만으로 annual holiday API가 VTS에서 지원된다고 판단할 수 없다.
- HHMCM000002C0의 date1-date5 의미는 공식 필드 정의로 입증되지 않았다. 날짜를 보이는 응답만으로 연간 휴장일 목록을 대체하지 않는다.
- 운영 경로: 완전성이 입증된 KIS 연간 달력 → 명시적으로 사용자 승인된 해시 검증 목록 → UNKNOWN/BLOCKED.
- 승인 목록이 없으면 거래 판단은 fail-closed. KRX runtime fallback은 금지.

## 4. Safety

- 수집기/collector는 변경·중지·재시작하지 않음.
- 추가 WebSocket 세션을 열지 않음.
- 주문/정정/취소 API 호출 없음.
- commit/push, Decision Log 및 AGENTS.md 수정 없음.
