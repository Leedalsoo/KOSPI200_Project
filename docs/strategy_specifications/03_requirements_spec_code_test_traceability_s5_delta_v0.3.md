# S5 추적성 갱신 초안 v0.3

- 상태: draft / unverified / unapproved
- 작성일: 2026-10-12
- 대상 기준: `strategy_5_gap_divergence_spec_v0.3.md`
- 기존 `03_requirements_spec_code_test_traceability_v0.2.md` 보존. 본 파일은 S5 delta이며 전체 추적표를 대체하지 않는다.

| Requirement | 명세 위치 | 코드/경로 조사 | 검증 증거 요구 | 현재 상태 |
|---|---|---|---|---|
| S5-R01 목적/갭 방향 진입 | S5 v0.3 §1, F01/F05 | track5_gap_divergence.py 기존 mean-reversion/z-score 구조 | official open/previous close, gap boundary, CALL/PUT direction | 불일치/미검증 |
| S5-R02 설정 fail-closed | §2, F28 | authoritative config load/enforcement path 확인 미완료 | null/status/invalid/hash mismatch가 신규 진입 차단 | 미구현 증거 없음 |
| S5-R03 advance/reversal | §2–§5, F11/F19 | 기존 underlying proxy trailing과 목표 규칙 불일치 | advance boundary, gap×ratio, reversal_min_pt 후보 비교 | 미검증 |
| S5-R04 pre-advance hedge | §1/§5, F12/F16 | 기존 mini futures 5-leg 존재 | 반대 옵션 1계약, partial/reject/cancel-race | 불일치/미검증 |
| S5-R05 re-reversal | §5, F21/F23 | 기존 futures close state는 목표 옵션 hedge와 다름 | hedge close, original option exposure/P&L reconciliation | 미검증 |
| S5-R06 whipsaw stop | §1/§5, F06/F14 | 기존 구현과 직접 매핑 증거 미확인 | 1회/2회 경계, 당일 신규 진입 금지, flatten verification | 미구현 증거 없음 |
| S5-R07 session end | §2/§5, F03/F20 | 기존 30 evaluations ≠ elapsed session minutes | 29:59/30:00/30:01, 3 action candidates | BLOCKED/null |
| S5-R08 multi-leg execution | §5, F07/F14/F15/F17 | execution/position paths not fully inspected | all-leg/partial/one-leg/reject/unfilled/cancel-race | 미검증 |
| S5-R09 P&L/cost/risk | §3/§4, F12/F22/F26 | existing proxy not actual option P&L | premium × multiplier × qty + fees/slippage; account aggregate | BLOCKED |
| S5-R10 provenance/config logging | §2/§5, F24/F28 | end-to-end logging not verified | run/group/leg/order/execution/position + version/hash | 미검증 |
| S5-R11 restart/reconciliation | §5, F25/F27 | restart persistence not confirmed | restart with open order/fill/position mismatch | 미검증 |
| S5-R12 S1/S9 interaction | §7 I01–I05, F26 | account aggregate risk not verified | duplicate-free premium/margin/stress aggregation | BLOCKED |
| S5-R13 REAL_VTS tuning/holdout | §3, F29 | no new REAL_VTS run permitted in this task | separated tuning/validation periods and evidence provenance | 계획만 작성 |
| S5-R14 approval gate | §8 | user approval not granted | approval version and approved scope match | 미승인 |

## Acceptance gate
- 각 요구사항이 명세 → 구현 경로 → 테스트 → 실제 증거에 연결되기 전 PASS 금지.
- 이번 작업에서는 테스트를 실행하지 않는다.
- 이 추적표는 검증 계획이며 코드가 요구사항을 만족한다고 판정하지 않는다.

## 정정 메모 — resolver/test 정적 조사 보완 (2026-10-12)
- `application/composition/automated_virtual_runtime_factory.py`에서 `resolve_track5`를 확인했다(함수 시작 line 445, registry 등록 약 line 497). 현재 경로는 Futures exit/terminal exit/option exit purpose를 명시한다.
- `tests/strategy/test_strategy5.py`의 정적 assertion은 option 1 + mini futures 5, Futures-first close, Futures quantity 5, evaluation-call timeout을 포함한다. 이는 과거 구현 테스트이며 신규 S5 의도 검증이 아니다.
- 이 보완은 조사 문서만 수정한다. 코드와 테스트는 수정/실행하지 않았다.


## S5-U namespace decision amendment (2026-10-12)
- User decision: preserve S1 U-ID values; namespace S5-specific new items as S5-U16 through S5-U20. This appendix controls references in this S5 delta document.
- Documentation-only resolution; no code, test, Git, or Live order action is authorized.
