# Q25 A2-1 — Strategy 6 SYN-EVT 생성 범위 제안

- 작성일: 2026-11-02 KST
- 상태: 범위 승인됨 / 데이터 생성 별도 승인 필요
- 데이터 출처: DERIVED_SCENARIO only; validation-only; production_runtime_eligible=false
- 기존 카탈로그: `reports/synth/SYN_EVT_CATALOGUE_20261029.json` (22 cases; seed 20261029; config hash `ec71dbe6ff44c50158425ce7ddb1bbf882871736214ccd680cc4f1135238ef4a`)
- 기존 S6 E2E 증거: `reports/synth/Q25_A2_1_S6_E2E_20261031.json`; `BLOCKED_NO_NATURAL_SIGNAL`, fast/detailed 비교 필드는 일치하지만 signals=0, Freshness sensitivity NOT_RUN.

## 케이스 범위

기존 22-case 카탈로그에서 Strategy 6에 적용되는 입력/가드 케이스를 재사용하되, 카탈로그에 포함된다는 사실만으로 S6 신호 생성이 보장된다고 간주하지 않는다.

| 케이스 | 기대 결과 / 검증점 |
|---|---|
| `volatility_1_3x` | 1.3× 변동성 구간 태깅; 임계값 튜닝 금지 |
| `missing_quote`, `delayed_stale_quote`, `zero_invalid_quote` | fail-closed; 가격 대체 금지 |
| `orderbook_gap`, `wide_spread`, `insufficient_depth` | 필수 호가/깊이 부족 시 진입 차단 |
| `underlying_gap` | 기초자산 가격 누락의 provenance 보존 |
| `identity_conflict`, `unknown_multiplier` | 계약 identity/승수 불명확 시 차단 |
| `limit_wait_cancel_no_price_reach`, `limit_price_reached_insufficient_volume`, `one_order_at_a_time` | 가격 도달과 실제 체결 구분, 순차 주문 제약 유지 |
| `synthetic_input_rejected_real_vts_live` | DERIVED_SCENARIO가 REAL_VTS/Live 경로로 승격되지 않음 |
| `data_quality_recovery`, `duplicate_event`, `crash_rebound` | 새 유효 관측 복구, 중복/시간순서 및 급락-반등 chronology 검증 |

S6 lifecycle 확장 제안(현재 22-case catalog에 모두 존재하지 않음): (1) 장 시작 전 입력과 11:00 진입 cutoff, (2) 5번째→6번째 행사가 후보 선택, (3) 10분 미체결 대기 후 취소/당일 재시도 없음, (4) 한쪽 매수 후 반대편 체결을 순서대로 관찰, (5) 보험료 2× 후 10% drawdown exit 조건, (6) 15:10 강제 종료, (7) exit 후 신규 진입/재시도 금지, (8) Freshness k={1,2,3,6} 비교(기본 k=2). 케이스는 실제 StrategyHub Strategy 6 코드가 합성 입력으로 자연 신호를 발생시키는지 검증하기 위한 것이며 신호를 하드코딩/주입하지 않는다.

## 해상도·용량 추정 (계획값, 미확정)

- 권장 초기 해상도: 이벤트 기반 + 1분 경계 tick. 10분 대기 및 15:10 exit의 경계 전후를 명시적으로 기록한다. 전략이 요구하는 더 높은 빈도의 실제 입력 계약이 확인되면 변경안을 제시하고 승인받는다.
- 08:45–15:10 구간은 최대 386 분 경계/시나리오다. 1개 underlying + 최대 6개 strike 후보를 보수적으로 계산하면 386×7=2,702 rows/시나리오. 8개 lifecycle 시나리오 상한은 약 21,616 rows이며, 경계 이벤트 20% 여유를 더해 약 26,000 rows로 계획한다.
- 저장 용량은 현재 실제 레코드 평균 크기/압축률을 확인하지 않았으므로 확정값이 아니다. 0.5–1.0 KiB/row 가정 시 약 13–26 MiB JSONL, 압축 시 별도 측정 필요. 실행시간은 replay runner 단독 벤치마크로 StrategyHub/Risk/OMS 실행시간을 대체할 수 없으므로 미확정이다.
- 데이터 생성 전에는 케이스별 row count/byte count/seed/config hash/expected signal/expected invariant를 manifest에 고정한다. 실행시간은 별도 승인 후 측정한다.

## 경로·파일·백업·롤백

- 출력 격리 후보: `data/derived_scenario/q25_a2_1_strategy6/` (현재 생성하지 않음)
- manifest/report 후보: `reports/synth/Q25_A2_1_S6_SYN_EVT_MANIFEST_20261102.json` 및 케이스별 결과 JSON
- 백업: 생성 전 대상 경로 존재 여부·파일 목록·SHA-256 manifest 기록. 기존 파일/데이터 덮어쓰기 금지.
- 롤백: 이 승인 실행에서 새로 생성한 파일만 별도 quarantine으로 이동; 기존 `data/derived_scenario/**`와 REAL_VTS 데이터는 수정/삭제하지 않음.
- 제외: `.env`, token/credentials, `data/kis_market_data_restart/**`, Graphify cache, 약 825 MB 기존 `data/derived_scenario` 데이터 전체를 Git에 포함하지 않음.

## 승인 게이트

범위 승인 완료. 실제 데이터 생성·생성기 실행·대상 경로 쓰기는 별도 명시 승인 전까지 금지. Strategy 6 natural signal E2E와 fast/detailed 일치 및 Freshness 민감도 통과 전에는 PSB_PASS를 선언하지 않는다.