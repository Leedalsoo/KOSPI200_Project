기준: Current Baseline v2 @E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D, 사용한 SSOT 항목 ID: CB2-01, CB2-02, CB2-03, CB2-04, CB2-05, CB2-06, CB2-09

# Q25 A5 S26 — Strategy 2 validation-only code controls (2026-11-09)

## 판정

**IMPLEMENTED_FAIL_CLOSED / PSB_UNVERIFIED**

S26의 제한된 코드·단위검증 범위를 구현했다. S2 명세는 draft/unverified/unapproved이며, Runtime E2E·자연신호·주문 경로 검증은 수행하지 않았다. Production/REAL_VTS/Live 승인으로 해석하지 않는다.

## 변경 파일

- `core/oms/multi_leg_plan.py`: S2 4-leg plan을 inner PUT BUY → inner CALL BUY → outer PUT SELL → outer CALL SELL 순서로 변경.
- `application/composition/track2_execution_plan_adapter.py`: 4-leg count뿐 아니라 S2 leg ID/side/type/order를 검증하도록 연결.
- `core/strategy/track2_entry_sequence.py`: 선행 레그가 전량 체결·대사된 경우에만 다음 레그를 READY로 판정. partial/working/cancel-race/unknown/reject/불충분 증거 및 out-of-sequence leg evidence는 BLOCKED. 주문 전송·repair·flatten·retry는 수행하지 않음.
- `core/risk/track2_validation_profile.py` 및 `config/validation_only/track2/risk_profile.v1.json`: 운영 risk config와 분리된 validation-only profile. 모든 capital/premium/max-loss/margin/fee/slippage/model limit은 null, execution/order/live/REAL_VTS flags는 false.
- `tests/core/test_track2_validation_only_controls.py`, `tests/application/composition/test_track2_execution_plan_adapter.py`: 순서·부분체결 차단·reject 차단·프로파일 비실행, 숫자 한도 주입 및 Live/REAL_VTS 활성화 거부 테스트.

## 검증

- Focused pytest: **14 passed** (`tests/core/test_track2_spec_alignment.py`, `tests/core/test_track2_option_pnl_fail_closed.py`, `tests/core/test_track2_validation_only_controls.py`, `tests/application/composition/test_track2_execution_plan_adapter.py`).
- `py_compile`: PASS.
- `git diff --check`: PASS.
- Graphify update: **7,569 nodes / 21,310 edges / 381 communities**.
- Graphify 경고: `application/composition/virtual_composition_root.py` line 54 syntax extraction issue(11 symbols partially extracted); 30 files no-symbol. S26 tests/code compile에는 영향이 관찰되지 않았으나 그래프 추출 한계로 기록.

## 미해결 및 안전 경계

- S2-U16~U21은 모두 UNRESOLVED_PROVISIONAL. 특히 partial-fill 후 repair vs flatten 우선순위는 결정하지 않았으며, 이 구현은 다음 레그 진입을 차단할 뿐 hedge/repair/flatten을 실행하지 않는다.
- Runtime multi-leg submission이 이 helper를 호출해 실제 주문을 순차 제출하는 wiring은 미완료. S26 결과는 plan validation과 pure progression gate의 단위 수준이며 Runtime E2E가 아니다.
- S2 strategy의 pre-fill state mutation, authoritative 4-leg contract identity, margin/max-loss/group budget enforcement, P&L/fees/pricing, durable restart는 미해결.
- pytest 전체 실행, Runtime/Replay, REAL_VTS, KIS Live, 실계좌·주문·계좌·잔고·증거금 API는 미실행.
- 운영 `config/risk/option-hedge-risk.v1.json`, `.env`, scheduler, collector, 원본 raw data 및 기존 dataset/manifest는 변경하지 않음.
- 격리 worktree만 수정. 원본 작업폴더 dirty 상태 보존. 원격 push 금지 유지.

## 적용 기준 및 입력

- Current Baseline v2 SHA-256: `E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D`.
- S2 gap matrix: No.1486, `BLOCKED_SPEC / PSB_UNVERIFIED`.
- S25 scenario catalog: No.1487, catalog generation only.
- S2-U16~U21 정책 미결 상태를 유지함.
