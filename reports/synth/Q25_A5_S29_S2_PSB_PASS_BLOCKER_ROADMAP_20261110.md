기준: Current Baseline v2 @9848792B24863A477CF10450D570C08A328776F84960A28425C62D193B3957F0, 적용 SSOT 항목 ID: CB2-01, CB2-02, CB2-03, CB2-04, CB2-05, CB2-06, CB2-09

# Q25 A5 S29 — S2 PSB PASS 차단 의존성 및 실행 경로 (2026-11-10)

## 판정

**BLOCKED_POLICY_AND_RUNTIME_DEPENDENCIES / PSB_UNVERIFIED**

S25 최신 카탈로그 생성은 PASS했으나, 이는 시나리오 문서 생성 범위뿐이다. S2 PSB PASS를 주장할 수 없다. 현재 SSOT는 S2 구현·Runtime/OMS 연결·Runtime E2E를 No.1500 명세 승인과 별개의 직접 승인 대상으로 둔다. 이번 사용자 지시는 목표(PSB PASS까지 계속 탐색)를 명시했지만, 특정 코드 파일·테스트·Runtime 작업 범위를 승인한 것은 아니므로 이번 단계는 읽기 전용 조사와 차단 경로 정리로 제한했다.

## 이번 조사 증거

- 격리 worktree: `Q25_A5_S22_S5_GROUP_CLOSE_20261109`
- 기준 HEAD: `1ea0129131370109344548827780a1e15b2ab414`
- Current Baseline v2 SHA-256: `9848792B24863A477CF10450D570C08A328776F84960A28425C62D193B3957F0`
- AGENTS.md SHA-256: `C66197D46A2E51281F54E4181D1D105E5F0F8A9CFF4086819C647B327587E5C0`
- Graphify query로 S2 Runtime progression, execution admission, group P&L 경로를 조사했다.
- `core/strategy/track2_entry_sequence.py`에는 4-leg 순서 및 이전 레그 fill 완료 확인 helper가 있으나, 주석상 U16 repair/flatten 정책은 처리하지 않는다.
- `application/composition/automated_virtual_runtime_factory.py`에는 S2 plan resolver와 adapter 주입이 있으나, helper를 Runtime order progression에 연결한 근거는 확인되지 않았다.
- `core/strategy/track2_asymmetric_trap.py:evaluate_trap()`은 authoritative option fills/marks/multiplier/fees/slippage가 연결될 때까지 빈 sequence를 반환한다.
- 기존 데이터 경로 검색에서 이 격리 worktree 안의 S2용 authoritative 4-contract master/quote evidence를 확인하지 못했다. 따라서 이 worktree만으로 KIS authoritative identity, multiplier, tradability, freshness를 입증할 수 없다.
- 테스트, Runtime, Replay, KIS API, REAL_VTS, Live, 계좌 및 주문 경로는 실행하지 않았다.

## PASS까지의 필수 Gate

### Gate 1 — 명세/정책 잔여값 확정

아래 항목은 기존 승인 정책만으로 수치를 추정할 수 없다. 각 항목은 사용자가 승인하거나 공식 근거로 결정해야 한다.

- U16: 추가 재시도 간격, 재시도 시 가격 재산정 시점.
- U17: exact monthly expiry authoritative source, 4개 listed strike 존재 확인, strike/tick rounding, volatility boundary.
- U18: stop 비율, trailing pullback 비율, MID freshness/validity.
- U19: broker position과 persisted ledger 불일치 시 조정·중단·재개·durable restore 절차.
- U21: max quote age, max spread 및 단위, fallback 산식/우선순위, tick rounding.
- 진입 feature: BBW·volume Z·OBI·basis·POC·IV·active/base volatility의 단위, window, sample sufficiency, provenance, as-of/received time, freshness.
- Group risk: premium/max-loss/stress/margin/fees/slippage/account aggregate exposure의 versioned validation-only limits.

### Gate 2 — Authoritative 입력 증거 확보

- KIS 공식 Option Master에서 4개 레그 각각의 정확한 표준옵션 identity, monthly expiry, listed strike, option type, broker symbol, multiplier, tradability를 확인해야 한다.
- 각 레그의 quote/orderbook timestamp, source/provenance, freshness 및 spread 검증 증거가 필요하다.
- 기존 worktree 검색만으로는 이 증거가 확인되지 않았다. 누락값을 synthetic 상수나 다른 상품 값으로 채우면 안 된다.
- 실제 KIS/REAL_VTS/Live/계좌 API 호출은 현재 SSOT 금지 범위다. 해당 입력은 사용자가 제공한 보존 원본/검증된 export로 확인하거나 별도 허용 범위를 정해야 한다.

### Gate 3 — Validation-only Runtime/OMS 구현 승인 및 연결

별도 범위 승인이 필요한 최소 구현 경로:

1. S2 strategy proposal → 4-leg plan → contract identity/pricing/risk preflight 연결.
2. `evaluate_track2_entry_progress`를 실제 Runtime order progression에 연결하고, 모든 선행 레그의 terminal/fill/position reconciliation 전 다음 레그를 막는다.
3. U16 repair/retry/120초 deadline 및 unknown-state fail-closed 처리.
4. repair 최종 실패 시 기체결 레그 전체 청산 정책을 validation-only 가상 실행에만 구현하고 group block을 검증한다. 실제 주문 제출은 금지한다.
5. 모든 4개 목표 수량 체결·대사 후에만 group ACTIVE로 전환한다.
6. option fills + MID marks + multiplier + fees/slippage 기반 group P&L stop/trailing 경로 연결.
7. U19 durable restart/restore 및 broker-position/ledger reconciliation 정책 구현.
8. U20 cancel-confirmed zero-fill progression과 late-fill race 방어.

### Gate 4 — 테스트/Replay 증거

- U16~U21 시나리오 전부에 대해 독립적인 positive/negative/boundary tests.
- 4-leg natural-signal validation-only Runtime E2E: proposal, preflight, sequential orders, partial fill/reject/cancel race, repair, full fill, ACTIVE, P&L exit, restart recovery, terminal close, flat reconciliation.
- 동일 dataset hash, manifest, scenario, config hash, clock/run scope로 FAST/DETAILED Replay parity.
- 실행되지 않은 시나리오를 PASS로 표시하지 않는다. Synthetic/derived evidence는 validation-only로 남긴다.

### Gate 5 — 통합 판정

- 모든 차단 시나리오가 요구된 증거로 통과하고, no-live/no-account/no-real-order 경계가 유지되어야 S2 validation-only PSB PASS를 판정할 수 있다.
- 이 결과는 Production/Live readiness를 뜻하지 않는다.

## 현재 중단 이유 및 다음 승인 경계

현재는 Gate 1의 사용자 정책 미확정과 Gate 2의 authoritative 입력 증거 부재, Gate 3의 별도 구현 범위 승인 부재가 선행 차단이다. 따라서 이 세 조건을 우회하거나 임의 기본값으로 채우지 않았다.

다음 실제 작업을 시작하려면 최소한 **S2 validation-only 코드·테스트·Runtime/OMS 연결 범위**에 대한 별도 직접 승인이 필요하다. 그 승인이 있더라도 Gate 1의 미확정 정책과 Gate 2의 입력 증거는 별도로 닫아야 한다.

## 변경/검증 경계

- 읽기 전용: AGENTS, Current Baseline, S2 spec/traceability, S24/S27/S28 보고서, Runtime source path, Graphify graph.
- 파일 수정 없음, 테스트/Runtime/Replay 실행 없음, KIS/Live/REAL_VTS/계좌/주문 API 호출 없음.
- 원본 작업폴더 dirty 224건 보존.
- 격리 worktree 기존 modified/untracked 항목 보존.
- commit/push 없음.\n