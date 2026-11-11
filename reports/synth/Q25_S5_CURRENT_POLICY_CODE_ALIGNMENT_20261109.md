# Q25 S5 최신 정책 코드 정렬 및 validation-only 입력 검증

- 실행일: 2026-11-09
- Worktree: `_worktrees/Q25_S5_POLICY_20261109`
- 기준 브랜치: `cleanup/p2-quarantine-20261026`
- 기준 HEAD: `22b7449f5c597816365e39e90162f99b4f3f053a`
- 판정: **PLUMBING_ONLY — S5 신규 진입 BLOCKED**

## 1. 적용한 최신 기준

- Decision Log No.1168의 OPTION BUY 2-only 진입안은 현재 `폐기됨`; 신규 진입 기준으로 사용하지 않는다.
- No.1167의 Strategy 5 진단 payload는 기존 Risk/OMS/주문 흐름을 변경하지 않는 additive evidence로 유지한다.
- No.1151/No.1152의 기존 Virtual terminal 결과에서 S5 terminal close가 `GROUP_MAX_MARGIN_UTILIZATION_EXCEEDED`로 거절된 사례가 있다. 이번 작업은 이 Risk/close 정책을 임의 변경하지 않았다.
- No.1469에 따라 유효한 KIS master anchor가 있는 계약에 한해 DERIVED_SCENARIO quote/depth를 validation-only로 보완한다. synthetic 입력은 Production/REAL_VTS authoritative input으로 승격하지 않는다.
- No.1171의 KIS-only runtime data 원칙을 유지한다. KIS multiplier가 없으면 KRX 또는 상수로 대체하지 않는다.

## 2. 코드 변경

1. `core/strategy/track5_gap_divergence.py`
   - No.1168 retired 상태에 맞춰 신규 S5 진입을 fail-closed 처리.
   - `evaluate_gap` 및 OPTION BUY execution plan에서 현재 승인된 대체 정책이 없으면 거절.
   - 이미 열린 포지션의 기존 OPTION/FUTURES close lifecycle은 유지.
   - close proposal은 실제 pending-close state, 방향, contract identity와 일치해야 한다.
2. `application/composition/track5_option_contract_source.py`
   - exact expiry, standard KIS option identity, ATM tie, two-sided quote, depth, source timestamp 및 freshness 검증.
   - KIS master의 contract multiplier가 없으면 `None`으로 유지. 임의 승수 보충 금지.
   - S15b validation-only manifest와 KIS master hash에 연결된 두 contract anchor만 synthetic orderbook 입력을 허용.
   - validation-only manifest의 `freshness_max_age_seconds=600`만 validation source에 적용. Production source에는 기본 freshness 허용치를 만들지 않음.
3. `environments/high_speed/validation_only_s15b_option_adapter.py`
   - manifest-bound S15b anchor identity view 추가.
   - synthetic orderbook의 `source_timestamp`를 `OptionOrderBookSnapshot.observed_at`에 보존.
4. `contracts/option_orderbook_source.py`, `infrastructure/kis/historical_observation_sources.py`
   - orderbook source timestamp 필드를 보존하도록 additive 확장.
5. `application/composition/standard_runtime_input_provider.py`
   - S5 contract selection에 runtime `as_of`와 source별 허용 freshness를 전달.
   - validation-only manifest가 없는 Production source는 freshness 정책 부재로 fail-closed.

전략 manifest, Risk 설정, resolver, OMS/Virtual execution lifecycle 및 Production predicate는 변경하지 않았다.

## 3. No.1469 synthetic data 검증

- 대상 KIS anchor: `B01611885`, `B01611887` (CALL 2개).
- 선택 검증: `B01611885` / CALL / strike 885.00.
- synthetic bid/ask: 42.93 / 43.37.
- synthetic source timestamp: 2026-11-06 10:00:00+09:00.
- provenance: `SYNTHETIC:DERIVED_SCENARIO`.
- `validation_only=true`; `contract_multiplier=None` 유지.
- PUT anchor는 없으므로 PUT 계약/가격/depth를 생성하지 않고 `UNAVAILABLE`로 유지.
- 세 개의 no-anchor 계약도 manifest 기준대로 UNAVAILABLE.

### 검증 자산 SHA-256

| 자산 | SHA-256 |
|---|---|
| S15b orderbook manifest | `b959d50c442f703b57ba946b6ed86c636d11630bf84c282593c10ac9103a68e3` |
| S15b orderbook events | `09c775b51dcd791a6ab5c9b79b0ed9e99851dc9ace98d4d43b2a06663cbe8797` |
| S15b quote manifest | `81f70193b4c783f5333c8ece9640a9db216361a9ea3702db470d251a77e77976` |
| S15b quote events | `81d961331e1e0ef370e61494fd3595bb5c8b08d05291809e06b527741ac7aa8c` |
| target KIS master | `96912b73fcf0fa549cb67cd03299b13afcbaaf229d5c03fdafefa1b5646aaf9e` |

검증 자산은 isolated worktree의 ignored `data/derived_scenario`에 복사해 사용했으며 원본 작업폴더 및 raw data는 변경하지 않았다.

## 4. 검증 결과

- 변경 파일 py_compile: PASS
- S5 + S15b + provider/runtime 연관 집중 테스트: **72 passed**
- 전체 pytest: **473 passed / 29 failed / 1 skipped**
- 전체 실패 29건은 R4/S7/S8 검증에서 요구하는 별도 ignored synthetic dataset/manifest가 현재 isolated worktree에 없는 기존 데이터 의존 경로다. S5 집중 테스트 실패는 없다.
- `git diff --check`: PASS
- Graphify update/query: 갱신 및 조회 확인. 단, 기존 `application/composition/virtual_composition_root.py:54` syntax warning 1건은 별도 미해결로 남음.

## 5. 실행 경계 및 남은 제한

- KIS API, REAL_VTS, Live, 실계좌, 외부 주문 API 호출 없음.
- synthetic quote/depth는 validation-only이며 실제 유동성/체결 가능성 증거가 아니다.
- KIS master multiplier 미확인 상태를 보충하지 않았으므로 실제 손익/증거금 계산 및 S5 실행 PASS는 아니다.
- S5 신규 진입은 계속 BLOCKED. 기존 open-position close 경로와 Risk/OMS 정책은 보존했다.
- No.1152의 terminal close margin rejection 원인/정책은 이번 변경 범위 밖이며 수정하지 않았다.
- 전략 manifest/Risk 설정은 변경하지 않았다.
- 원본 작업폴더 HEAD `b060fa57d3801e8227e88c8e54df8d2f9ffe7407`, dirty item count 224 유지.
- 원격 target branch는 기준 HEAD `22b7449f5c597816365e39e90162f99b4f3f053a`와 일치 확인.

## 6. 다음 기준

S5의 새로운 진입·헤지·반전 정책은 폐기된 BUY2안이나 미승인 초안을 재사용하지 않는다. 신규 정책이 승인되기 전까지 신규 진입은 계속 차단하고, No.1469 기반 validation-only data plumbing과 기존 포지션 close lifecycle만 유지한다.
