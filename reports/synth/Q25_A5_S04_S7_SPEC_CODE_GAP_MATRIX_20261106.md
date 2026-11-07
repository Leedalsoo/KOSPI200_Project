# Q25 A5 S04 — Strategy 7 명세-코드 Gap Matrix
작성일: 2026-11-06 (KST)
판정: PSB_UNVERIFIED
범위: read-only 정적 대조. 코드·설정·데이터 변경 및 테스트 실행 없음.

## 1. 기준 및 해석 경계

- 브랜치: cleanup/p2-quarantine-20261026
- Local/remote HEAD: aa0da075a9f256c14b92997256f379bcca920543 (일치)
- AGENTS.md §1: 과거 Strategy 1~9 명세·테스트는 승인된 신규 명세가 아니다. 새 전략 기준은 사용자가 승인한 버전만 사용한다.
- AGENTS.md §20/§20.2: Q25는 SYNTHETIC/DERIVED_SCENARIO validation-only로 프로젝트 코드 경로를 검증한다. Synthetic PASS를 REAL_VTS/Live 운영 PASS로 승격하지 않는다.
- Notion No.1234의 S7 v0.3은 draft / unverified / unapproved. F01–F29 및 S7-V03 시나리오는 확정 구현 요구가 아니라 gap 분석용 초안 후보로만 취급한다.
- Notion No.1391: S7/S8 V2 calendar·Option Master 구성은 plumbing 수준 확인. S7 Runtime lifecycle은 UNVERIFIED이며 월요일/목요일 독립 group lifecycle 미구현으로 기록됨.
- S7-U16/U17(반대 레그 10분 미체결, 15:00 cutoff 이후 timeout), U18/U19(volatility source/freshness, 계좌 통합 위험), U20(rename 영향)는 미해결. 임의 기본값을 정하지 않는다.

## 2. 현행 구현 및 증거 인벤토리

| 영역 | 현재 파일 | 확인된 역할 |
|---|---|---|
| S7 전략/state | core/strategy/track7_volatility_skew_weekly_insurance.py | 단일 Track7State, entry/exit 신호, per-leg stop/trailing, execution plan |
| 계약 선택 | application/composition/track7_option_contract_source.py | Option Master에서 exact expiry, MONDAY/THURSDAY_WEEKLY, STANDARD 계약을 필터링하고 기준가 ±12.5 근접 strike 선택 |
| Runtime input | application/composition/standard_runtime_input_provider.py | 주간 계약 입력·calendar fields·Option OrderBook mark를 S7 context에 주입 |
| Analytics | application/composition/track7_analytics_provider.py | S7 volatility/mark analytics 구성 |
| Strategy lifecycle | application/strategy_hub/hub.py, core/strategy/standard_registry.py, core/strategy/registry.py | 등록된 S7 plugin 실행·callback |
| Group/position model | core/oms/position_group.py | group_id 기반 position group/leg 자료형 및 registry |
| Validation calendar | environments/high_speed/validation_only_trading_calendar.py | synthetic calendar/hash/provenance 검증; 운영 달력 아님 |
| Synthetic V2 | data/derived_scenario/q25_strategy7_8_v2/strategy7_weekly/20261103.jsonl 및 manifest.json | 216 rows, S7_MON_20261109 / S7_THU_20261112 두 그룹 |
| Tests | tests/core/test_track7_spec_alignment.py; tests/core/test_track7_entry_cutoff_1500.py; tests/application/test_track7_option_contract_source.py; tests/scripts/test_q25_strategy7_8_synthetic_assets.py | 일부 단위·contract selection·synthetic asset 검증 |
| Runtime smoke | verification/smoke_q25_s7_s8_v2_runtime_calendar_20261103.py | 전략별 max_events=1 smoke. No.1391 결과상 S7 신호 0, readiness 기본 fail-closed; lifecycle E2E 아님 |

V2 manifest:
- dataset SHA-256: 052d660e792adbda6b8fed7afce95cc54a1db007b70abfec3c0b736a6126da13
- identity_source_status=BLOCKED_IDENTITY_OWNER_UNRESOLVED
- expiry_is_authoritative=false, runtime_eligible=false, production_runtime_eligible=false
- 달력은 synthetic schedule이며 KIS/KRX authoritative calendar가 아니다.

## 3. 명세-코드 Gap Matrix

| ID | 요구/검증 주제 | 현행 코드·증거 | 차이 및 판정 |
|---|---|---|---|
| G01 | 월요일·목요일 expiry group 독립 상태 | V2 manifest/test는 두 group ID와 각 PUT/CALL quote 존재 확인. S7 plugin state는 단일 Track7State이며 group-keyed state map 없음 | 데이터의 두 group과 Runtime 독립 lifecycle은 다름. 미구현/UNVERIFIED |
| G02 | 그룹별 진입일·만기·계약 identity 연결 | Runtime provider는 tick의 weekly contract_class, expiry, underlying으로 하나의 Track7ExecutionInput 생성 | group_id 및 각 leg authoritative symbol/identity를 payload에 보존하는 연결 미확인. 부분/증거 부족 |
| G03 | Option Master 주간 계약 필터 | Track7OptionContractSource는 exact expiry, MONDAY/THURSDAY_WEEKLY, STANDARD 필터와 multiplier 일치 검사. 테스트는 MONTHLY/MINI 배제 확인 | 상품군 필터는 확인. 선택은 기준가 ±12.5 nearest strike이며 rank 5/6·liquidity 후보 선택은 아님. 부분 구현 |
| G04 | 5·6위 후보 순차 선택 | S7 source는 nearest strike 반환, rank/first_rank 필드 없음. Strategy 주석은 rank selection provisional/null | 후보 순위·first_rank·후보 fallback 미연결. 미구현 |
| G05 | volatility 1.3× entry gate | Strategy는 active_vol >= base_vol×1.3 및 new_week_start 검사. runtime_config_verified/risk_limits_available 기본 false | 비교 로직 존재. source/window/freshness/as-of lineage와 승인 config 미확정. 부분/설정 차단 |
| G06 | 단일 레그 지정가 순차 주문 | BUY signal execution plan은 PUT+CALL 두 leg를 하나의 MultiLegExecutionPlan에 포함 | PUT→CALL 순차 주문/각 레그 timeout 상태기계가 아님. 명시적 Gap |
| G07 | ACK/partial/cancel/late-fill 대사 | entry callback은 PUT과 CALL 각각 완전 FILLED, 잔량 0, execution ID/timestamp/price 및 group_complete 요구 | 한 레그 체결·부분체결·취소 경합·지연체결을 단계별 보존/재대사하는 S7 state 전이 증거 없음. 미구현/증거 부족 |
| G08 | U16/U17 timeout 경계 | Provider 생성자에 track7_order_timeout_source가 있으나 S7 strategy 실행 흐름의 10분 timeout/cancel terminal 처리 확인 불가 | 10분 timeout, 취소 확정 후 다음 주문, cutoff 이후 pending 정책 미연결. BLOCKED_SPEC (U16/U17) |
| G09 | 50% per-leg stop | 각 leg mark ≤ actual entry fill×0.50이면 해당 leg close signal | trigger 계산은 존재. 잔여 수량·partial close·authoritative fresh mark E2E 미검증. 부분 구현 |
| G10 | 2× 활성화 후 10% trailing | per-leg peak mark를 Track7State에 보관, entry fill 2× 도달 후 peak×0.90 이하에서 close | high-water는 메모리 state. restart durable restore 없음. 부분 구현 |
| G11 | trigger priority expiry > stop > trailing | evaluate는 PUT stop/trailing → CALL stop/trailing → expiry 15:10 순서 | 코드 실행 순서가 초안 우선순위와 반대. 다중 trigger에서 expiry 우선 보장 안 됨. 명시적 불일치 |
| G12 | own expiry 15:10 및 공식 달력 대조 | exact expiry YYYYMMDD normalize, state expiry와 analytics 날짜가 같고 15:10 이상이면 close. calendar.is_expiry_day는 feature requirement에만 있고 evaluate에서 미사용 | 날짜 equality는 존재하지만 official expiry calendar cross-check/short holiday week 검증 없음. V2 calendar는 synthetic-only. 부분/authoritative 검증 차단 |
| G13 | 잔여 lot/수량별 청산 | close plan은 insurance_qty 고정 수량. 단일-leg close callback은 filled_quantity가 insurance_qty와 같아야 state 변경 | partial fill 후 잔여수량 기반 재주문/대사 경로 불충분. 미구현/증거 부족 |
| G14 | restart/reconnect 복원 | initialize/reset은 Track7State와 _exit_pending 초기화. state는 plugin 인스턴스 메모리 | pending orders, actual fills, group lots, high-water, config hash durable restore 미확인. 미구현 |
| G15 | S7 및 타 전략 계좌 전체 위험 | strategy에는 risk_limits_available boolean gate만 존재 | 월·목 그룹 동시 exposure 및 S1/S6/S8/S9 premium/margin/correlation 집계·enforcement 근거 없음. BLOCKED (U19) |
| G16 | 데이터 provenance/freshness | Option Master source, Provider bid mark, analytics feature requirement 1초 freshness 선언 확인 | S7 execution input은 선택된 각 contract의 symbol/identity_source를 담지 않고 expiry/strike/multiplier만 전달. authoritative identity와 mark lineage end-to-end 증거 부족. 부분/증거 부족 |
| G17 | S7 synthetic Runtime E2E | asset test는 2 group/quote/hash/manifest 검증. smoke는 max_events=1. No.1391은 S7 signal 0 및 lifecycle UNVERIFIED 기록 | natural signal→Risk→OMS→Virtual fills→Position/PnL 및 Fast/Detailed equivalence 미검증. PSB_UNVERIFIED |
| G18 | 이름/ID 호환성 | 현재 strategy_id track7_volatility_skew_weekly_insurance 유지 | U20 rename은 제안만 존재. 승인 전 파일명/ID 변경 금지. 현 상태 유지 |

## 4. 후속 구현 후보 파일 (S04에서는 수정 금지)

1. core/strategy/track7_volatility_skew_weekly_insurance.py — group/leg state, sequential lifecycle, trigger ordering, residual close, recovery.
2. application/composition/track7_option_contract_source.py — rank candidate/weekly expiry identity/contract provenance.
3. application/composition/standard_runtime_input_provider.py 및 application/composition/track7_analytics_provider.py — group별 context, expiry calendar, volatility/mark source lineage.
4. application/strategy_hub/hub.py, core/strategy/registry.py, core/strategy/orchestrator.py — strategy instance/group ownership 및 execution callback routing.
5. application/composition/virtual_multi_leg_execution.py, core/oms/position_group.py 및 관련 OMS/order state modules — 단일 레그·partial/cancel/late fill·잔여량 대사.
6. environments/high_speed/validation_only_trading_calendar.py — validation-only 경계/holiday-week 시나리오. 운영 달력 승격 금지.
7. 테스트 후보: 위 4개 S7 테스트 파일과 신규 tests/application/composition/ 내 lifecycle/recovery tests. 정확한 파일 추가 범위는 S05/S06에서 다시 고정.

## 5. 시나리오 요구사항 후보 (전부 NOT_RUN)

| ID | 입력/경계 | 합격 조건 |
|---|---|---|
| S7-A01 | 월요일 group open 상태에서 목요일 group 진입 | 두 group/expiry/leg/lot/high-water/order 상태가 서로 덮어쓰지 않고 독립 유지 |
| S7-A02 | 동일 expiry의 MONTHLY, THURSDAY_WEEKLY, MINI, STANDARD 후보 혼재 | exact weekly STANDARD 계약만 선택; identity/multiplier/expiry를 동일 master row로 추적 |
| S7-A03 | rank 5 유효 / rank 5 무효·유동성 부족, rank 6 유효 | 승인된 first_rank 순서로 한 번에 한 주문만 제출; 취소 terminal 및 fill 대사 후에만 다음 후보 |
| S7-A04 | volatility ratio 1.2999 / 1.3000 / 1.3001 및 missing/stale/as-of mismatch | 경계값 의미가 승인 명세와 일치; 필수 source 불명/STALE이면 신규 주문 fail-closed |
| S7-A05 | 첫 PUT fill, CALL 미체결 9:59 / 10:00 / 10:01 | U16 확정 전 정책 임의 선택 금지; actual residual lot 유지, 재시도는 명시 정책 및 cancel reconciliation 뒤에만 |
| S7-A06 | 14:59:59 제출, timeout 15:00:00 이후 완료 | U17 결정 전 cutoff 이후 신규 주문/재시도 금지, pending/cancel/late-fill 증거 보존 |
| S7-A07 | stop 동시 발생, expiry 15:10, trailing trigger | expiry > stop > trailing 우선순위가 decision trace와 close order에서 입증 |
| S7-A08 | entry×0.4999 / 0.5000 / 0.5001 | 해당 leg의 actual remaining quantity만 손절 |
| S7-A09 | entry×1.999 / 2.000 / 2.001; high-water drawdown 9.99% / 10% / 10.01% | 2× activation 이후 leg별 high-water와 10% trigger 경계 정확 |
| S7-A10 | expiry 전일 15:09:59, 만기일 15:09:59 / 15:10:00 / 15:10:01 | own expiry 및 승인 달력 기준으로 force-close; fill/position flat 확인 전 종료 금지 |
| S7-A11 | close partial fill / reject / cancel race / late fill | actual residual quantity 및 execution IDs 기준 재대사; ACK/신호만으로 flat 금지 |
| S7-A12 | restart/reconnect 중 두 group open/pending | authoritative orders/fills/positions, lot, high-water, config hash 복원; 불일치 시 신규 주문 fail-closed |
| S7-A13 | 두 S7 group + S1/S6/S8/S9 동시 위험 | 승인 aggregate cap·margin·correlation 정책으로 합산; cap 미설정/미검증이면 신규 주문 차단 |
| S7-A14 | 동일 dataset/manifest/run scope FAST vs DETAILED | 자연 신호, decision/risk, order state, fills, positions, PnL, trace 동등 |
| S7-A15 | contract/quote/calendar/volatility identity·freshness 누락 또는 충돌 | UNAVAILABLE/BLOCKED 및 구체 사유; 추정값/대체계약 진입 금지 |

## 6. S04 종료 판정 및 안전 경계

- 정적 분석 결과 구현·검증 gap이 남아 S7 Runtime E2E를 PASS로 선언할 수 없다.
- S04 판정: PSB_UNVERIFIED. 이는 S7 코드가 전혀 없다는 뜻이 아니라 일부 단위/plumbing 구현과 전체 group lifecycle/E2E 증명을 구분한 판정이다.
- S05 구현 전 U16/U17/U18/U19를 임의 결정하지 않는다. 미확정 정책은 fail-closed 유지.
- S04에서 source/config/test/data 변경, pytest 실행, stage/commit/push 없음. 기존 dirty/untracked 파일 보존.
- KIS/REAL_VTS/Live/실계좌/주문·잔고·증거금 API 호출 없음. 운영 RiskConfig, .env, 권한, 스케줄러, 수집기 변경 없음.
- git diff --check 통과(기존 LF/CRLF 경고만). Local/remote HEAD 동일.
- 다음 단계는 S05이며 별도 승인 없이 자동 실행하지 않는다.
