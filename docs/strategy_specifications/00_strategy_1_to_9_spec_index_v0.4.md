# Strategy 1~9 신규 명세 승인 인덱스 v0.4

- 기준 시각: 2026-10-21 17:49 KST
- 상태: **사용자 승인 — 승인된 파일 해시 범위에서 구현 및 독립 오프라인 재생 허용**
- 승인 근거: 현재 대화의 직접 지시(“갱신 전략명세대로 승인”, “승인 게이트 갱신”, “전략 코드 수정·독립 재생”).
- 목적: 이전의 일괄 미승인 게이트가 입력 품질 오류 하나로 전체 검증을 막지 않도록 하되, 실제 데이터와 synthetic 데이터를 혼합하거나 미확인 값을 만들어 쓰지 않는다.
- 본 문서는 v0.2 인덱스를 삭제·변경하지 않고 후속 실행 기준으로 추가한다. 각 승인 파일은 아래 SHA-256으로 고정한다.

## 1. 승인된 명세 파일

| Strategy | 승인 파일 | SHA-256 | 적용 경계 |
|---|---|---|---|
| S1 | strategy_1_tail_defense_spec_v0.4.md | 2FDFC8E9016C4FF4B520D594AC9B40A22348A9C3224FA3FF19301BD846E20FCB | 이 파일의 최신 내용만 기준 |
| S2 | strategy_2_asymmetric_trap_spec_v0.4.md | 9DC2264D31120DFBAA0B6987A5C8B97F67497F00093C641D72CBD6FFFA324B85 | 이 파일의 최신 내용만 기준 |
| S3 | strategy_3_statistical_arbitrage_spec_v0.3.md | AE4B559D73AD41F2BEC6F433A439F981DACBA8336B5127B2B185A58C9097C210 | 이 파일의 최신 내용만 기준 |
| S4 | strategy_4_gamma_scalping_spec_v0.3.md | 3CD09EF2E203C59B06FB40FDD24CDE1DC4AD8998A3C696B7B16A1DB537352EB1 | 이 파일의 최신 내용만 기준 |
| S5 | strategy_5_gap_divergence_spec_v0.4.md | 7FAEBEFD30721B8780D966F8F9D1A6D30441D55E116421E15CF454B213B73E2A | 이 파일의 최신 내용만 기준 |
| S6 | strategy_6_daily_tail_insurance_spec_v0.4.md | 66843918114928D4B633B20DDEDB128644DE7026BE5A3C6524B8427055649CA9 | 이 파일의 최신 내용만 기준 |
| S7 | strategy_7_weekly_volatility_skew_insurance_spec_v0.3.md | 4788D1D6387182C7FFAD5DFFFCA0D0B23AAD039DCB04703E4C7D8D2641C49C69 | 이 파일의 최신 내용만 기준 |
| S8 | strategy_8_macro_regime_monthly_strangle_spec_v0.4.md | A72D82503EBB8DC2EC827FCD62CAACF0BF0AC45E2B97DAB541A37351A7C4CE95 | 이 파일의 최신 내용만 기준 |
| S9 | strategy_9_s1_put_insurance_spec_v0.5.md | 8729F2E615EC4256550DCBC3B937BBCEBD04AAE33033B5E385045B9F94524768 | 사용자 직접 지시에 따른 범위 승인만 적용; min_volume/S1 lot provenance/유동성·재시도 파라미터 미확정이므로 Runtime 구현·활성화는 BLOCKED |

## 2. 승인 게이트 규칙

1. 승인된 파일 해시와 다른 파일은 승인 범위가 아니다. 명세 내용을 바꾸려면 새 버전·변경 이유·재검증·재승인을 기록한다.
2. Strategy 1~9는 각각 독립 실행·독립 Run ID·독립 상태로 검증한다. 한 전략의 입력 결함이 다른 전략의 독립 검증을 자동 차단하지 않는다.
3. 결함은 영향받은 관측/계약/전략/시나리오 단위로 격리한다. 필수 입력이 없는 전략만 BLOCKED 처리하고, 다른 전략의 검증은 계속한다.
4. PASS는 실제 실행 증거가 있는 범위에만 부여한다. 오프라인·표본·synthetic 검증을 REAL_VTS 전체 PASS로 확대하지 않는다.
5. 미확인 필수 값은 UNAVAILABLE/BLOCKED로 유지한다. 가격·거래량·만기·승수·거래일·세션 경계·identity를 임의의 0/False/상수/추정값으로 채우지 않는다.
6. Synthetic 데이터는 data/synthetic_market_data/YYYYMMDD/ 아래 별도 저장하고 source_type=SYNTHETIC, runtime_eligible=false를 명시한다. REAL_VTS canonical/raw 파일은 수정하지 않는다.
7. Synthetic quote ladder는 quote-quality/입력 경계/오류 복구 시나리오 검증에만 사용한다. 실체결가·거래량·실행 가능 가격을 증명하지 않으며, Live/VTS 실데이터 결과로 취급하지 않는다.
8. Quote-only 이벤트는 bid/ask/order book만으로 보존할 수 있다. last_price와 volume이 필요한 전략은 해당 필드가 없을 때만 해당 전략을 BLOCKED 처리하며, 호가 중간값·호가 수량으로 대체하지 않는다.
9. KIS VTS 전용, KRX runtime fallback 금지, 단일 WebSocket 세션, 구독 41개 이하, REST 최소 1.25초 간격, Live·주문·계좌 API 금지 정책은 변경하지 않는다.
10. 장중 운영 가드 08:29~16:01에는 수집기/수집 코드를 수정·중지·재시작하지 않는다. 이 인덱스는 collector 변경을 승인하지 않는다.
11. 코드 변경은 승인된 명세에서 확정된 규칙만 구현한다. 명세 내 미결정 파라미터/authoritative evidence가 필요한 항목은 fail-closed로 둔다. 사용자 별도 승인 없이 Manifest 활성값 변경, 삭제, stage/commit/push를 하지 않는다.

## 3. 구현·검증 진행 기준

- 승인 상태: 사용자 승인 완료(승인 범위는 위 9개 파일 해시로 고정).
- 구현 상태: 별도이며 자동으로 완료 처리하지 않는다.
- 검증 상태: 전략별 독립 재생과 결과 로그를 확인한 뒤 개별 판정한다.
- 실행 결과가 NO_SIGNAL_OBSERVED이면 전략 성능 PASS가 아니다.
- 데이터 결함이 있는 synthetic scenario에서 정상적인 결과는 전략별 BLOCKED 또는 명세가 허용하는 명시적 비실행이다. synthetic 입력으로 만든 signal/order/fill은 실제 시장 결과로 표현하지 않는다.

## 4. 버전 메타데이터 이슈

일부 파일은 파일명 버전(v0.4)과 문서 내부 제목 버전(v0.3)이 다르다. 승인 대상은 위에 고정한 파일명+SHA-256의 정확한 바이트다. 이 메타데이터 불일치는 승인 범위 확인을 위해 기록하며, 본 작업에서 기존 명세 내용을 직접 수정하지 않는다. 향후 문서 버전 정리는 새 버전과 재승인을 거친다.

## 3. S9 v0.5 scope approval and implementation gate (2026-10-21)

- The prior v0.3 index row pinned the v0.4 file hash even though the file header identified itself as v0.3 draft/unapproved and the v0.4 D-4 addendum was marked DRAFT/VERIFYING/UNAPPROVED. This contradiction is resolved by the new v0.5 file; v0.4 is preserved unchanged as historical input.
- The user's direct instruction authorizes reapproval of the S9 design scope in v0.5. This is scope-only approval, not implementation approval, Runtime activation, or order permission.
- Multi-day KIS VTS order-book evidence: four raw source days (20261015, 20261016, 20261020, 20261021); `C01611880` 21,229 observations and `C01611882` 5,171 observations. Evidence: `verification/evidence/track9_multiday_quote_quality_20261021.json`, SHA-256 `C47DEDBCE4E105605F19F34BB294D8014748D610643BF280D6845DCE11003D7B`.
- Candidate research gates only: rank-4 spread <=10%, rank-3 spread <=15%, cumulative top-five depth >=4 contracts per side. These are not approved runtime configuration values.
- `min_volume`, `s1_put_link_ratio`, `third_strike_insufficient_action`, max quote age, final liquidity thresholds, retry count/interval, quantity rounding, limit price, and repricing/cancel policy remain unset. Actual S1 residual short-PUT execution/position provenance was not found in existing local evidence. Runtime and strategy implementation remain BLOCKED.
