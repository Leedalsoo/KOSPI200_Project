기준: Current Baseline v2 @E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D, 사용한 SSOT 항목 ID: CB2-01, CB2-02, CB2-03, CB2-04, CB2-05, CB2-06, CB2-09

# Q25 A5 S24 — Strategy 2 명세-코드 Gap Matrix (read-only, 2026-11-09)

## 1. 판정

**`BLOCKED_SPEC / PSB_UNVERIFIED`**

S2 Asymmetric Trap의 문서·코드·런타임 연결·테스트를 정적 대조했다. 4-leg intent 일부는 문서화되어 있으나 명세 자체가 `draft / unverified / unapproved`이고, 사용자 확인 필요 항목 S2-U16~U21이 남아 있다. 현재 구현은 명세의 주문 순서·월물 정책·체결 lifecycle·옵션 P&L·복구 요구를 충족한다고 입증되지 않았다. S2 신규 진입은 활성화 근거가 없으며 fail-closed 상태를 유지해야 한다.

- 범위: read-only static inspection only.
- 실행하지 않은 항목: pytest, Runtime/Replay, REAL_VTS, KIS API, order path, config mutation.
- 수정하지 않은 항목: source code, tests, manifest/dataset, risk config, environment, original raw data.

## 2. 기준·작업 경계

- SSOT: Current Baseline v2, local `docs/CURRENT_BASELINE.md` SHA-256 `E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D` — expected hash 일치.
- 적용 항목: CB2-01/02/03/04/05/06/09.
- 원격 대상 브랜치: `cleanup/p2-quarantine-20261026`.
- 격리 worktree branch: `q25-a5-s22-s5-group-close-20261109`.
- local HEAD / remote target SHA: `5549e318b38554861b9c52f9b180d1fa969424ba` / 동일.
- 원본 작업폴더 dirty 항목: 224건 유지.
- 원격 `AGENTS.md` §1~§14 확인. §3 안전 경계, §9 Git 보호, §14 SSOT gate를 적용했다.

## 3. 기준 명세·문서 무결성

| 자료 | 현재 파일/문서 상태 | SHA-256 또는 비고 |
|---|---|---|
| S2 spec | `strategy_2_asymmetric_trap_spec_v0.4.md`; 본문 제목은 v0.3, 본문 상태 draft/unverified/unapproved | `9DC2264D31120DFBAA0B6987A5C8B97F67497F00093C641D72CBD6FFFA324B85` |
| Decision matrix delta | 파일명 v0.5; 본문 제목 v0.4, draft/unverified/unapproved | `78767A0597530E5E5554AF0656862EB247CE57F7485DEF278361F73F57A248A7` |
| Traceability delta | 파일명 v0.2; 본문 제목 v0.1, draft/unverified/unapproved | `41E8B6DF055794FCD6A29E2F5932A995CAE72D0CF3CF9837F69CF73BD7DA09F5` |
| Scenario plan delta | 파일명 v0.2; 본문 제목 v0.1, draft/unverified/unapproved | `22C2325B7123615BCE9E7E65704752A2B3831526D4D6C9D1D3CBE28F3BB6795B` |
| Notion No.1237-1 | v0.3 문서 작성·검토 이력, 명시적으로 unapproved; 현재 파일 v0.4와 버전/hash 동기화 증거 없음 | 과거 v0.3 spec hash `63B6662FFFD36A2AB1E00810AC4CB4B35D44276690377CC2448345E87434304B` |

**문서 무결성 gap:** 파일명과 내부 버전 표기가 서로 다르며 Notion No.1237-1은 v0.3 이력에 머문다. 최신 S2 승인 명세로 취급할 수 없다. 버전·본문·승인 상태를 정합화하기 전 구현 기준으로 사용하지 않는다.

## 4. 명세-코드 gap matrix

| ID | 영역 | 명세/확인 의도 | 현재 코드 증거 | 판정 |
|---|---|---|---|---|
| G01 | 명세 권한·버전 | S2 상세 명세와 delta가 승인된 단일 버전이어야 함 | spec v0.4 파일의 본문 제목 v0.3, draft/unverified/unapproved. Notion No.1237-1은 v0.3 | **BLOCKED_SPEC** |
| G02 | 4-leg 구조·순서 | inner PUT BUY → inner CALL BUY → outer PUT SELL → outer CALL SELL | `core/oms/multi_leg_plan.py:32-54`는 short PUT SELL → short CALL SELL → long PUT BUY → long CALL BUY 순서. `Track2ExecutionPlanAdapter`는 전략/신호/group 식별과 leg 수 4를 검사하지만 leg별 side/strike/order sequence는 검증하지 않음 | **BLOCKED_SPEC** — 순서 불일치 |
| G03 | Signal→Plan 의미 | 전략 의도와 최종 4-leg plan이 동일하게 추적되어야 함 | `core/strategy/track2_asymmetric_trap.py`는 `TRAP_PLAN` 단일 PUT SELL proposal 생성. `automated_virtual_runtime_factory.py:520-546` resolver가 이를 4-leg plan으로 재구성하지만 proposal/plan 의미·leg 순서 계약 테스트 없음 | **BLOCKED_SPEC / UNVERIFIED** |
| G04 | Fill 기반 lifecycle | 실제 fill/position이 확인되기 전 ACTIVE 또는 cycle consumed 처리 금지 | `track2_asymmetric_trap.py`의 `evaluate()`는 proposal 생성 전에 `_trap_active=True`, entry fields 및 `_daily_entry_count`를 갱신. 실제 4-leg fill 이후 활성화하는 상태 전이 증거 없음 | **BLOCKED_SPEC** |
| G05 | 월물·세션 정책 | 월물만, 월물 시작 후 첫 3일 진입, 일일 15:00 cutoff, 월물당 1회, 동일 만기 재진입 금지, 만기일 15:10 close | `Track2OptionContractSource.nearest_expiry()`는 모든 identity expiry 중 가장 가까운 날짜를 선택하며 monthly series 필터가 보이지 않음. 전략은 `MAX_DAILY_ENTRIES=2`, 15분 cooldown을 유지; 월물 cycle/15:10 terminal close 입증 없음 | **BLOCKED_SPEC** |
| G06 | Contract/strike resolution | 네 레그 각각 실제 상장된 일반 KOSPI200 옵션, exact expiry, multiplier, strike identity | `track2_option_contract_source.py:31-84`는 nearest expiry와 공통 ATM PUT/CALL만 선택. 전략은 ATM offset으로 네 strike를 계산하고 source가 네 offset 계약 모두의 listing/identity를 검증한다는 증거 없음. multiplier는 ATM pair의 positive/equal만 검사 | **BLOCKED_INPUT / SPEC** |
| G07 | Analytics provenance/freshness | BBW, volume Z, OBI, basis, POC, IV, active/base vol에 source/as-of/received time, unit, identity, freshness 필요 | `track2_analytics_provider.py:25-31`은 `instrument_identity=None`, provenance source `standard-runtime.track2`. `Track2OptionIVSource.get_iv()`는 Decimal만 반환; IV observation time을 consumer에 연결하는 증거 없음. `Track2MarketMetrics`에는 timestamp 필드 없음 | **BLOCKED_INPUT / UNVERIFIED** |
| G08 | Feature 산식·경계 | threshold, 단위, window, sample sufficiency와 stale/missing 처리 확정 | `core/analytics/track2.py`의 BBW는 window 최솟값 여부 boolean, volume Z는 표준편차 0일 때 99/0 특례. `KISTrack2MarketMetricsSource`는 price window 20/volume delta/return 평균을 사용. 승인 산식·단위·기간의 증거 없음 | **PROVISIONAL / BLOCKED_SPEC** |
| G09 | Entry config/risk gate | versioned config, premium/max-loss/margin/fees/slippage 및 account aggregate risk를 첫 주문 전 검증 | 전략 생성자 기본값 `runtime_config_verified=False`, `risk_limits_available=False`; `evaluate()`와 `build_execution_plan()`은 gate false면 차단. config version/hash·수치 한도 연결 증거 없음. 공통 `admit_multi_leg_intents()`는 leg별 RiskGate 심사이며 S2 group budget/max-loss reservation 검증은 별도 미입증 | **BLOCKED** |
| G10 | Order price/quote gate | 각 leg별 limit basis, tick rounding, max quote age/spread, 4-leg quote coverage | `build_asymmetric_trap()` 결과는 `UNRESOLVED_LIMIT_PRICE`이면서 `limit_offset_ticks=1`을 반환. per-leg pricing/tick/spread 설정 승인·검증 증거 없음. S2-U21 unresolved | **BLOCKED_SPEC** |
| G11 | Partial/reject/cancel race | 이전 leg fully filled/reconciled 전 다음 leg 금지; partial/reject/cancel-race 복구는 승인된 policy만 | S2 전용 per-leg lifecycle/recovery 테스트 미발견. S2-U16과 U20 unresolved. 현재 strategy state는 proposal 시점에 active로 변함 | **BLOCKED_SPEC / NOT_RUN** |
| G12 | Option-group P&L/exit | actual option fills/marks/multiplier/fees/slippage 기반 group P&L; stop/trailing trigger | `evaluate_trap()`은 `return ()`로 종료해 stop/trailing signal을 내지 않음. underlying proxy를 사용하지 않는 fail-closed는 확인되나 실제 option P&L exit path는 미구현/미검증. S2-U18 unresolved | **BLOCKED_INPUT / NOT_RUN** |
| G13 | Expiry/terminal close | 만기일 15:10 이후 모든 실제 open lots 청산, flat reconciliation 전 reset 금지 | resolver는 `TRAP_CLOSE`의 open-lot close plan을 만들 수 있으나 S2 자연 만기 신호·calendar gate·per-leg terminal close Runtime 증거 없음 | **PSB_UNVERIFIED** |
| G14 | Restart/durable recovery | orders/fills/positions/config 복원 후 reconciliation, authoritative flat 확인 | S2 lifecycle persistence/restore contract 및 cold-start test 없음. S2-U19 unresolved | **BLOCKED_INPUT / NOT_RUN** |
| G15 | Test/acceptance traceability | F01–F29 및 시나리오를 exact test/log/dataset/config로 추적 | S2 전용 테스트 파일 2개(총 4 assertions 수준의 간단한 fail-closed/structure checks). S2 natural-signal Runtime/4-leg order/fill/cancel/exit/restart/FAST-DETAILED 테스트 없음. scenario plan의 S2-V03 cases는 NOT_RUN/BLOCKED | **PSB_UNVERIFIED** |

## 5. 전용 테스트에서 확인된 범위

- `tests/core/test_track2_spec_alignment.py`: short-switch timeout 경로가 신호를 내지 않는 점, 구조가 `STRUCTURE_READY_NOT_PRICED`/`UNRESOLVED_LIMIT_PRICE`임, config/risk gate 기본 차단만 확인.
- `tests/core/test_track2_option_pnl_fail_closed.py`: underlying 가격을 옵션 group P&L로 사용하지 않는 fail-closed만 확인.
- `tests/application/composition/test_fresh11_caller_edge_matrix_e2e.py` 및 `test_s1_validation_only_runtime_input.py`는 S2 runtime acceptance/4-leg lifecycle 증거로 간주하지 않았다.
- pytest 미실행. 위는 소스·테스트 정적 확인 결과이며 실행 PASS가 아니다.

## 6. 미결 정책·증거 항목

| ID | 미결 항목 | 현 판정 |
|---|---|---|
| S2-U16 | 부분체결/거절/cancel-race 시 repair vs flatten 우선순위 | 사용자 결정·증거 필요; 자동 진행 금지 |
| S2-U17 | ATM 동률, listed strike/tick rounding, exact expiry/monthly series, active/base vol boundary | authoritative source 및 rule 미확정 |
| S2-U18 | option mark side, net-cost denominator, fees/slippage, stop/trailing 공식 | 실데이터 검증·정책 미확정 |
| S2-U19 | restart durable persistence 및 authoritative flat/position source | contract·restore 증거 미확정 |
| S2-U20 | zero-fill timeout 후 cancel-confirm이면 다음 leg 진행 또는 월물 cycle 중단 | 지시 경계 모호; 자동 다음 leg 금지 |
| S2-U21 | per-leg limit price basis, tick rounding, quote max age/max spread | versioned config·REAL_VTS evidence 미확정 |

## 7. 후속 단계 진입 조건

1. S2 명세의 파일명/본문 버전/Notion 기록을 단일 버전으로 정합화하고 사용자 승인 상태를 명시한다.
2. U16–U21의 정책 결정 또는 authoritative evidence를 확보한다. unresolved 항목은 PROVISIONAL/null로 유지하고 entry 차단한다.
3. 월물 exact expiry와 4개 listed contract identity/quote/freshness를 한 번에 입증할 수 있는 source contract를 확정한다.
4. group-level premium/max-loss/margin/fees/slippage/account exposure gate와 config version/hash를 정의한다.
5. 승인 명세 이후 S25 scenario design/generation을 수행한다. 이번 S24에서는 시나리오 생성·테스트 실행·코드 변경을 하지 않았다.

## 8. 안전·무결성 확인

- source/test/spec/config/manifest/raw data 변경 없음.
- pytest, Runtime, Replay, REAL_VTS, KIS API, Live/account API 및 실제 주문 미실행.
- commit/push 미실행. 이 단계는 read-only gap matrix이며 다음 단계 S25는 별도 승인 대기.
- 원본 작업폴더 dirty 224건 보존.
- Graphify query/path로 S2 전략→plan 경계를 조사했으며 graph update는 하지 않았다.

## 9. 주요 파일 SHA-256

- `core/strategy/track2_asymmetric_trap.py`: `D8134495E154E06759BB620BA60F45A15B477D8DDFCAD73AD07927439DFC5B39`
- `application/composition/automated_virtual_runtime_factory.py`: `F6B9D868660CF6B78D0616A9E0AAADA987964FFF09B47983CC77823410F2D467`
- `application/composition/track2_execution_plan_adapter.py`: `3C3886E22B41AA1803AC164D189D2D968E83C7DD42300BC897DE183F5A901E11`
- `application/composition/track2_analytics_provider.py`: `4FC81C5F50175662979D8FF52DA1265A86E626722F7093AC293E12F8F453F18E`
- `application/composition/track2_option_contract_source.py`: `9806C6D9F9CBAD695EEB022074D678942DC4F6D20D2C3744BBAB4D337CCEAE50`
- `application/composition/standard_runtime_input_provider.py`: `E7C71EB7C1019C3833596901A4E977872A84A00A772E67A4B19DE0D6F22B5C94`
- `core/oms/multi_leg_plan.py`: `B3D150A1226995011D6A3FFC8F4CF1C8438F3C0DFE687426EFB0613B47407A50`
- `core/analytics/track2.py`: `44020317079B7D343764DF2E47F62418198E723C11652271AF4FCF7EA94DD1E4`
- `infrastructure/kis/track2_market_metrics_source.py`: `45E7D2581AE013516989C57467E580A430BCA5295F8CD46B70ED3ABBA14AF281`
- `infrastructure/kis/track2_option_iv_source.py`: `5D92F390DB674D0242CFBB289AEBF8A726900FA3FD4B90025403055FA88820AE`
- `infrastructure/kis/track2_market_observation_sink.py`: `E421FADCB64075C3A9C03D7BA2C767F2F4B786C9D4C820B4CE3EAEC5D57A25B0`
- `core/risk/multi_leg_risk.py`: `A2F9F920B8AA2A00BFC9190405CFA997C3E05A37D95F3F3C3646ACC3DEC8170F`
- `tests/core/test_track2_spec_alignment.py`: `437E0143DD28EDDAEA3137810D82AB4A728703803EEE79F0B505A1BB369B0E92`
- `tests/core/test_track2_option_pnl_fail_closed.py`: `D83CF00B44C2CE0EA4EB30FB9F9B954953AF1207298FB06A95BD5AF6F2419B3C`