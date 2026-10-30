# REAL_VTS 관측치 ↔ Synthetic 데이터 현실성 비교

- 기준일: 2026-10-28
- 상태: PARTIAL / BLOCKED_FOR_FULL_MEASUREMENT
- 목적: 합성 데이터가 구현 공백 탐지에 적합한지 비교한다. 전략 수익성이나 실거래 성능을 증명하지 않는다.
- 실데이터 archive 복사·이동·수정은 수행하지 않았다.

## 1. 비교표

| 항목 | REAL_VTS 현재 증거 | Synthetic P5 현재 증거 | 비교 판정 |
|---|---|---|---|
| 데이터 기간 | 여러 날짜 partition 존재. 2026-10-14, 15, 16, 20–23, 26–27의 WS raw-manifest hash match 기록 있음 | 6 scenario × 53,550 rows, 62 trading days each | 기간/레코드 수만으로 동등성 판단 불가 |
| 시간 해상도 | 원본은 REST/WS 혼합. 전체 timestamp 간격 분포 미측정 | 5-minute resolution | 1초/고빈도 이벤트를 재현한다고 볼 근거 없음 |
| 옵션 quote | canonical 표본에 last는 있으나 bid/ask 및 5단계 depth가 모두 0인 사례; observed_at null 사례 | synthetic quote/depth fields available by dataset design, per-record provenance required | REAL_VTS 전체 zero-rate 미측정. Synthetic 필드 존재가 현실성 PASS를 뜻하지 않음 |
| Underlying | 표본에서 bid/ask 급변 및 일부 volume=0 사례, 원인 미확인 | coherent index/futures/mini relationship is a generator requirement; measured parity report absent | basis/volume correlation 비교 미완료 |
| WebSocket continuity | 2026-10-19 WS raw 부재; other dates have raw files; full per-TR gaps unmeasured | deterministic scenario sequences, 5-minute interval | 실제 프레임 연속성 재현 여부 미확정 |
| ACK/subscription | 2026-10-27 active_count 27 / cap 41, ack_status NOT_USED | no broker ACK simulation evidence established | ACK semantics must remain explicitly unavailable, not inferred |
| Duplicates / latency | full counts and distributions not measured | deterministic seed/version intended; actual event timing comparison absent | not comparable yet |
| IV surface / arbitrage | no full surface check measured | high-gamma/skew/term structure and no-arbitrage checks are spec requirements; validation evidence not included here | not comparable yet |
| Expiry/calendar | authoritative KIS master/observed evidence not established for all cases | synthetic expiry policy exists for validation-only data; synthetic IDs are not production Standard IDs | validation-only; never promote synthetic identity |
| Session start/end | authoritative session boundaries not confirmed | generator session boundary is assumption until verified | assumed, production-ineligible |
| Data integrity | 9 dates WS raw JSONL hashes match corresponding manifests; 2026-10-14 has 3 auxiliary metadata mismatches | P5 manifest status PASS_WITH_LIMITATION; 6 datasets have synthetic provenance | neither result proves market realism; REAL_VTS partition integrity remains partially blocked |

## 2. Synthetic P5 dataset evidence

- Dataset names:
  - `p5_run_20261026_trend_up_seed20261026`
  - `p5_run_20261026_trend_down_seed20261026`
  - `p5_run_20261026_mean_revert_seed20261026`
  - `p5_run_20261026_high_volatility_seed20261026`
  - `p5_run_20261026_low_volatility_seed20261026`
  - `p5_run_20261026_shock_seed20261026`
- Each: 53,550 rows, 62 trading days, 63 output files, 5-minute resolution.
- Aggregate: 321,300 rows, approximately 825 MB.
- Manifest status: `PASS_WITH_LIMITATION`.
- Identity: `BLOCKED_IDENTITY_OWNER_UNRESOLVED`.
- `production_runtime_eligible=false`, `validation_only=true`.
- These figures describe dataset structure, not calibrated correspondence to REAL_VTS distributions.

## 3. Required metrics still missing

The following values must remain `UNMEASURED` or `assumed: true` until calculated from existing, eligible dates:
1. Per date × TR × instrument frame counts and inter-arrival distribution.
2. Gaps, duplicates, out-of-order events, delayed/stale observations and latency p50/p95/max, separating source time from received/collected time.
3. Null/zero bid, ask, depth price, depth quantity and volume percentages.
4. Option contract coverage by strike/type/expiry and missing-contract windows.
5. Underlying/futures/mini basis distribution and synchronized-observation coverage.
6. IV skew/term structure, high-gamma event coverage and no-arbitrage validation.
7. Session start/end and expiry-calendar checks against authoritative KIS master or direct observations.
8. Manifest mismatch cause and whether the parent manifest is expected to be updated after auxiliary metadata writes.

No estimates are substituted for these metrics.

## 4. Restrictions / interpretation

- REAL_VTS and SYNTHETIC data remain separate; do not copy raw data into synthetic folders or vice versa.
- Do not use synthetic returns to tune strategy parameters or claim profitability.
- Preserve order-book gaps, limit-order wait/cancel behavior, sequential one-order-at-a-time constraints, and exact high-speed/detail equivalence requirements.
- The synthetic option master and synthetic contract IDs are validation-only; `production_runtime_eligible=false`.
- This report does not grant approval to implement generator v0.2. R3 must first produce the specification and wait for user approval before implementation.

## 5. Next execution

1. Verify these three report files by direct read and, if permitted, compute file hashes without accessing today's raw data.
2. Create a Notion R2 result/blocker record and update the official queue only after the required Notion write succeeds.
3. R2 cannot be marked fully complete until the saved artifacts are verified and the Notion record/queue are confirmed.
4. Stop after R2 and request `승인 R2` before starting R3 specification work.
