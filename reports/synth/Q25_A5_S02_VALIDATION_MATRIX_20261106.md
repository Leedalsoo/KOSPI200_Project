# Q25 A5 S02 — S6 4조합 VALIDATION_MATRIX

- 판정: **PSB_UNVERIFIED**
- 범위: validation-only Synthetic / Virtual Runtime
- 실행 조합: first_rank {5, 6} × timeout_split {per_order, shared_elapsed}; 각 조합 FAST/DETAILED paired run
- 입력 이벤트: 조합별 43,232
- Dataset SHA-256: `b7603e34bcfa03510246c3c68b7e09c59a5e89ff7ecb3baa42f7220c6bb4bb13`
- Manifest SHA-256: `9b9ce6871794344b142d179e5001be68a4ec721ff2e6bd15a696809972e5341e`
- Validation risk profile SHA-256: `b0c697dfc3b77f60628b73c9f1b21c5d95b576a60a10f3be9daeda85524017f2`
- Matrix report: `reports/synth/Q25_A4_S6_RUNTIME_MATRIX_RANK6_RETRY_20261106.json`
- Matrix report SHA-256: `708ed3d7c1dcf4d31b8d6b4b7b07aa3a32d7cb7f03eaef3243b5583eee886490`

## 결과

| first_rank | timeout_split | FAST/DETAILED 동등 | 두 후보(rank 5·6) 가용 | 실제 선택 rank | Flat 확인 | 체결/거부 | 판정 |
|---:|---|---|---|---:|---|---|---|
| 5 | per_order | 일치 | 아니오 — [5]만 | 5 | 예 | 4 / 0 | PSB_UNVERIFIED |
| 5 | shared_elapsed | 일치 | 아니오 — [5]만 | 5 | 예 | 4 / 0 | PSB_UNVERIFIED |
| 6 | per_order | 일치 | 아니오 — [5]만 | 5 | 예 | 4 / 0 | PSB_UNVERIFIED |
| 6 | shared_elapsed | 일치 | 아니오 — [5]만 | 5 | 예 | 4 / 0 | PSB_UNVERIFIED |

모든 조합에서 43,232 events, 3 signals, 4 fills, 0 rejected, 최종 PUT/CALL open quantity 0을 확인했다. FAST/DETAILED 비교 필드(events, signals, approvals, routes, fills, rejects, execution IDs, multi-leg decisions, strategy status, PnL fields)는 모두 일치했다.

## 판정 근거 및 미해결 항목

- 8개 FAST/DETAILED state stream을 `Track6ValidationStateStore.load_latest()`로 재검증했다. 모든 hash chain이 유효하고 최종 상태는 `FLAT_CONFIRMED`다.
- Manifest는 rank 6 계약을 `SYNTHETIC_ONLY`로 추가했지만 `identity_source_status=BLOCKED_IDENTITY_OWNER_UNRESOLVED`다. Runtime state에는 모든 조합에서 `available_candidate_ranks=[5]`만 기록됐다.
- first_rank=6 조합도 rank 6을 선택하지 못하고 rank 5로 fallback했다. 따라서 rank 5/6 동시 후보 탐색과 지정 rank 선택을 검증했다고 볼 수 없다.
- 이 결과는 합성 검증 범위에만 해당하며 운영 기본값을 결정하지 않는다. `first_rank` 및 `timeout_split` 운영 기본값은 계속 null/fail-closed다.
- 관련 focused regression: **48 passed** (Track6 lifecycle, contract source, Virtual bridge cancel, validation state store, validation-only execution/gates, restart budget reconciliation).

## 안전 및 변경

- KIS/REAL_VTS/Live/실계좌/주문·계좌 API 호출 없음.
- 운영 RiskConfig, `.env`, 권한, 스케줄러, 수집기 변경 없음.
- 기존 dirty/untracked 파일 보존. 제품 코드 변경·stage·commit·push 없음.
- 기존 보고서 및 상태 파일을 덮어쓰지 않고 별도 retry run ID와 신규 보고서 경로 사용.
