# FRESH-63 — FRESH-61 전체 2,072건 Virtual Market replay

- 실행일: 2026-11-19
- Report SHA-256: `2283295ae82c691f04342e42050502b799707aa61e17864fb4f0a226351ca8ef`
- FRESH-61 manifest SHA-256: `ef4808d3fd6d730d7c070e30196c8558ccecd5a2654adb93ccb2547e6250b53c`

## 전체 원본 sidecar

| 날짜 | 행 수 | SHA-256 |
| 20261012 | 686 | `56235743ca2688b0c3cebd525393e31369e6d85f5a1318aa8551010847a5dcf4` |
| 20261013 | 1386 | `23c78507448742701bfbb3a006e476bb5e2155595cebfdc2713ba811ed9d6737` |

## 입력 품질 / 보존 결과

- 총 2,072 rows, timestamp groups 1,596, unique contract identities 77.
- Event-time reversal 0, collected_at reversal 0, same-timestamp underlying mismatch 0, invalid quote 0.
- 중복 contract+timestamp: 183 groups / 299 extra rows. 동일 가격 그룹 49, 가격 상이 그룹 134.
- 2,072개 source_observation_id 및 (trading_date, source_line_number) 고유성 유지. 동일 timestamp 중복은 삭제하지 않고 원본 이벤트로 보존.

## Virtual Market 재생

- HighSpeedReplayRunner → SyntheticReplayAdapter → Synthetic Option Master → contract-scoped Virtual Market quote → VSSF OrderBook.
- Replay ticks 2,072, synthetic identities 77, Virtual Market quote keys 77, VSSF OrderBook books 77.
- 마지막 event: 2026-10-13T15:33:30+09:00. 주문 명령 0, pending order 0, 최종 포지션 없음.
- Strategy loop은 구독 해제 상태로 replay했으므로 이 단계에서 전략 신호/주문 실행은 하지 않았다.

## 검증 결과 및 한계

- FRESH-63 단독 1개 + FRESH-62 4-leg Virtual Runtime + 데이터 계보/시간/계약 교차검증 회귀: **151 passed / 0 failed / 0 skipped**.
- FRESH-62에서 test-only 4-leg 진입/청산 Virtual Execution Bridge를 별도 검증했다. FRESH-63은 전체 입력의 Virtual Market quote projection 범위다.
- 합성 계약 ID/승수는 validation-only. 실계좌 KIS identity, broker account, fee/tax/margin, profitability, Live readiness 증거가 아니다.
- 원본 Raw/Canonical/Accepted Runtime, Project200, master, Live/REAL_VTS 및 실제 주문은 변경/호출하지 않았다.
