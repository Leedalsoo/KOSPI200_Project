# A6 C08 — Legacy Test/Comment Review and Full Pytest (2026-11-09)

기준: Current Baseline v2 @`E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D`; 검토 기준: 프로젝트 범위·안전 경계·전략별 상태·데이터 provenance/검증 원칙.

## 실행 환경 및 전체 결과

- 격리 worktree: `C:\Users\white\AppData\Local\Temp\Project200_A6_C01_20261109`
- HEAD before C08: `b2b4ee3b5f2eb9b0693770bc8ac071905f54fea3`
- Python `3.14.6`, pytest `9.1.1`, tracked Python test files `95`.
- Full command: `py -m pytest -q -p no:cacheprovider --tb=short`
- Result: **473 passed / 29 failed / 1 skipped**, 14.58s (503 collected).
- Failure classification: all 29 failures are missing validation-only synthetic dataset/manifest inputs in the isolated worktree; no strategy-logic assertion failure was established by this run.
  - R4 lifecycle: 7 failures (`p5_run_20261026_trend_up_seed20261026` replay manifest absent).
  - S7 lifecycle/adapter: 6 failures (`q25_s05_3_s7_concurrent` manifest/input absent).
  - S8 adapter: 11 failures (`q25_s8_v3/strategy8_monthly/normal` manifest/input absent).
  - S7/S8 calendar-generated datasets: 3 failures (generated manifests absent).
  - S7/S8 synthetic asset manifest checks: 2 failures (manifest inputs absent).
  - Error signatures: 12 `SYNTHETIC_REPLAY_MANIFEST_REQUIRED`; 17 `FileNotFoundError` for `data/derived_scenario/**/manifest.json`.
- These data paths are ignored/external synthetic validation assets, not same-day raw KIS/WS/REST inputs. No raw market dataset was modified or used as a test input. Missing assets were not fabricated or copied.

## Old policy/test review

- `tests/application/composition/test_fresh11_caller_edge_matrix_e2e.py`: its title and test names described an `S1-S9` caller-edge matrix, which could be mistaken for the active strategy scope. Updated only the docstring, test identifiers, and a clarifying comment: S3/S4 resolver registrations remain for compatibility but are excluded from active Q25 scope. The registered-ID fail-closed assertions and resolver checks remain unchanged.
- Targeted regression after this text-only alignment: **29 passed** (`test_fresh11_caller_edge_matrix_e2e.py` plus `test_track9_s1_put_insurance_gate.py`), 0.18s.
- Retained `test_track9_s1_put_insurance_gate.py` as a valid retirement guard against legacy S1-linked overnight-pair signals; it does not replace the approved independent S9 v0.3 implementation.
- Retained S5 retired BUY2-entry guards, S8 No.1169 retired minimum-budget guards, and REAL_VTS provenance-rejection tests. These assert fail-closed/retirement boundaries, not current permission to use those old policies.
- `tests/scripts/test_synthetic_3m_p5.py` remains an isolated legacy generator/validator regression suite; it is not treated as a current 3-month automated E2E or scheduler requirement.

## Change and safety accounting

- Changed one test file only; no strategy/application logic, fixtures, raw data, runtime/operating config, scheduler, collector, or Decision Log changes.
- Full pytest changed only line endings in `reports/synth/Q25_A5_S15B_OPTION_QUOTE_SUPPLEMENT_20261109.json.sha256`; restored that file to its pre-test HEAD bytes and verified `git diff --exit-code` clean.
- `git diff --check` passed. No full pytest rerun after the text-only naming/comment edit; the directly affected test file and S9 retirement guard were rerun successfully (29 passed).
- No KIS/REAL_VTS/Live/account/order API calls. No push. Original dirty workfolder untouched.

## C08 conclusion

`BLOCKED_INPUT` for a clean full-suite pass: 29 tests require ignored synthetic validation datasets/manifests unavailable in this isolated worktree. Preserve the failures as evidence; do not repair or synthesize assets in C08. The remaining 473 tests passed and 1 was skipped. Any fixture/manifest recovery or failure remediation belongs to a separately approved follow-up stage.