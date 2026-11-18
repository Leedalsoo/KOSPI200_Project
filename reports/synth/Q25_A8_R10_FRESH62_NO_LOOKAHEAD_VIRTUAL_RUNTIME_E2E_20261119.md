# FRESH-62 — FRESH-61 교정 데이터 Virtual Runtime E2E

- 실행일: 2026-11-19
- 입력: 2026-10-13 10:55:46 KST, 동일 시각 옵션 4종목
- FRESH-61 sidecar SHA-256: `23c78507448742701bfbb3a006e476bb5e2155595cebfdc2713ba811ed9d6737`
- 결과 보고서 SHA-256: `ca8803cb82941029201695d8a46da05eb692b1113b5da765b0999c67ccb05d9b`

## 검증 경로

SyntheticReplayAdapter → Synthetic Option Master → Virtual Market → Risk/OMS → VirtualMultiLegExecutionBridge → VSSF Virtual Execution → PositionLot/CloseEvent/Fee Ledger

실제 StrategyHub 신호가 아닌 테스트 전용 결정론 주문 계획으로 공통 실행 경로를 검증했다.

## 입력 계약

| KIS source code | Right | Strike | Expiry | Underlying | Bid | Ask |
|---|---:|---:|---|---:|---:|---:|
| C01611950 | PUT | 950.0 | 20261112 | 935.68 | 58.65 | 60.25 |
| B01611930 | CALL | 930.0 | 20261112 | 935.68 | 56.3 | 59.55 |
| B01611927 | CALL | 927.5 | 20261112 | 935.68 | 56.9 | 61.55 |
| C01611937 | PUT | 937.5 | 20261112 | 935.68 | 50.8 | 55.15 |

## 결과

- Replay input 4/4, synthetic identities 4개.
- 진입: 4 routed / 4 filled / 0 rejected.
- 청산: 4 routed / 4 filled / 0 rejected.
- PositionLot history 4, close events 4, close execution ID 고유 4개.
- 최종 open PositionLot 0, VSSF account positions `{}`, pending bridge legs 0.
- Fee Ledger records 8. VSSF 수수료 0은 연결 확인용이며 실제 수수료 기준이 아니다.
- 회귀 테스트: **150 passed, 0 failed, 0 skipped**. compileall 및 `git diff --check` PASS.

## 제한

- 주문 계획은 테스트 전용이며 자연 StrategyHub 신호나 S2 운영 정책 E2E가 아니다.
- 계약 ID와 승수는 검증 전용 synthetic fixture다. VSSF는 실제 KIS 계좌가 아니다.
- 실제 수수료·세금·증거금·슬리피지·수익성·Live readiness를 검증하지 않았다.
- 원본 Raw/Canonical/Accepted Runtime, Project200, master 및 Live 설정은 변경하지 않았다.
