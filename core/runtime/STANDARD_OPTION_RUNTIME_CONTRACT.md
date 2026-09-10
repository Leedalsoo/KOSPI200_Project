## 목적

Reference OptionProgramRuntime의 기능을 통째로 복제하지 않고, OptionProject에 이미 이식된 Standard Core를 실제 실행 가능한 하나의 Application/Runtime 경계로 연결하기 위한 계약이다.

## 확정된 입력

- CanonicalMarketTick

- OptionContractMaster + injected TradingCalendar

- Strategy Registry/Orchestrator

- Market Condition / Sensor 계층

- Signal Processor

- Decision / Risk 계층

- Position/Execution Policy 및 OrderIntent Factory/Adapter

- Environment가 공급하는 Account / Position / Broker / Execution 의존성

## 확정된 처리 순서

```plain text
CanonicalMarketTick
  -> Option identity / expiry resolution
  -> DTE calculation using the same TradingCalendar
  -> Market condition / sensor
  -> Track 1~9 StrategyOrchestrator
  -> Standard Signal validation/debounce
  -> DecisionArbiter
  -> Risk decision/gate
  -> Position/Execution Policy
  -> OrderIntent
  -> Environment-specific Order Command adapter
  -> OMS / Broker
```

## OptionMaster 계약

1. Tick에 expiry가 있으면 authoritative value로 유지한다.

1. expiry가 없고 symbol이 있으면 OptionContractMaster에서 조회한다.

1. 조회한 expiry는 canonical tick에 반영한다.

1. DTE는 동일한 injected TradingCalendar로 계산한다.

1. 임의의 DTE fallback은 사용하지 않는다.

## 책임 분리

### Runtime/Application이 담당

- 위 Core 단계의 호출 순서와 데이터 전달

- Account/Position/Broker/Execution 의존성 연결

- execution report 전달

- runtime 상태 및 처리 metrics

- startup recovery/reconciliation 호출 경계

### RuntimeController가 담당하지 않음

- Track별 직접 분기

- Broker API 직접 호출

- VMS/VSSF 직접 조립

- Legacy Conductor의 OS lockdown/uvloop 정책

- UI/WebSocket 서버 소유

## 현재 구현 전제

StrategyOrchestrator는 Strategy lifecycle과 Signal 수집까지만 담당하며 Decision/Risk/Order 실행은 담당하지 않는다. Signal 계층 역시 Order Command를 직접 생성하지 않는다. 따라서 Runtime은 이 계층들의 실제 API를 확인한 뒤 연결해야 한다.

## 구현 보류 조건

현재 Notion에 저장된 일부 Core 문서는 실제 구현 API의 완전한 시그니처보다 설계/계약 문서가 앞서 있다. 특히 다음을 정확히 확인하기 전에는 production Runtime 구현체를 임의로 작성하지 않는다.

- Track 1~9가 StrategyContext를 실제로 어떤 형태로 받는지

- DecisionArbiter의 실제 입력/출력 타입과 호출 방식

- RiskEngine/RiskGate의 실제 입력/출력 타입

- OrderIntent Factory/Adapter의 실제 연결 타입

- Execution Report → OMS FSM 상태 전이의 실제 API

- Environment Bundle의 Broker/Account/Execution 실제 제공 객체

이 확인 없이 Reference의 긴 process_tick()을 복사하면 현재 Standard Core의 책임 분리와 충돌하거나 기존 전략 기능을 누락할 위험이 있다.

## 검증 원칙

- Reference Exp_Detail_1은 읽기 전용이다.

- 실제 terminal pytest PASS를 실행하지 못한 경우 PASS로 기록하지 않는다.

- KIS HTTP 및 실제 Broker E2E는 별도 검증 대상이다.

## Runtime identity ownership 보완 — No.338

- CanonicalMarketTick.source_sequence가 존재하면 Standard Runtime의 authoritative tick_sequence source로 사용한다.

- VMS projection adapter는 Reference tick.seq_id를 source_sequence으로 lossless 전달하는 것이 이미 확인됐다.

- 동일 tick 내 Strategy evaluation ordinal은 실제 Runtime loop가 소유하는 local_sequence으로 명시한다.

- RuntimeExecutionContext(tick_sequence, local_sequence)가 signal/client order identity를 단일 규칙으로 파생한다.

- source_sequence 누락 또는 0 이하를 tick counter fallback으로 보완하지 않으며 fail-closed 한다.

- 아직 Standard process_tick() 구현체는 생성하지 않는다. 실제 Strategy evaluation loop가 materialize되기 전에는 context contract까지만 확정한다.

## Runtime signal collection ownership 확인 — No.339

- StrategyOrchestrator.run()은 _strategy_keys/selected의 결정적 순서대로 strategy를 실행하고, 각 evaluate()의 produced를 그대로 signals.extend(tuple(produced))로 수집한다.

- 따라서 Orchestrator 반환 StrategyRunResult.signals의 순서는 현재 구현상 실제 evaluation/collection 순서를 보존한다.

- 단, Orchestrator는 tick sequence를 소유하지 않고 Runtime 독립 컴포넌트이므로 local_sequence ID 생성 owner로 승격하지 않는다.

- authoritative owner는 tick을 보유한 Runtime 실행경계이며, StrategyOrchestrator는 Runtime이 enumerate할 수 있는 결정적 signal collection order를 제공한다.

- 실제 production Runtime tick loop가 아직 없으므로 local_sequence counter를 Orchestrator 내부 상태로 추가하지 않는다.

## Runtime input-source audit — No.340

- Virtual 경로의 CanonicalMarketTick authoritative source는 실제 VMS ReferenceCanonicalMarketTick이며 VMSMarketTickProjectionAdapter가 seq_id -> source_sequence을 lossless 전달한다.

- 그러나 Track4 StrategyContext에는 CanonicalMarketTick만으로 계산할 수 없는 active_vol, base_vol, current_delta, current_pnl, premium_spent, accumulated_gamma_profit, theta_decay_cost, current_equity, OHLC history가 필요하다.

- 현재 OptionProject에는 이 Track4 typed payload를 실제 Runtime authoritative source에서 조립하는 production provider/factory가 materialize되어 있지 않다. 기존 integration_fixtures.py는 테스트 fixture이므로 Runtime source로 승격하지 않는다.

- 따라서 실제 Virtual tick source만으로 Track4 process_tick()을 조립하면 typed payload를 synthetic하게 채워야 하므로 production loop 구현을 계속 보류한다.

- 다음 이식 대상은 synthetic payload factory가 아니라 Reference program_runtime.py process_tick()의 실제 market/position/greeks/pnl/history input acquisition 책임을 최소 source-provider 단위로 분리하는 것이다.

## Runtime input owner matrix — No.341

Reference Exp_Detail_1/option_program/runtime/program_runtime.py process_tick()를 실제 branch 기준으로 재대조했다.

<!-- Notion table block -->
| 입력 | Reference 획득 방식 | OptionProject authoritative owner | 판정 |
| current_price / timestamp / sequence | CanonicalMarketTick 직접 | VMS → VMSMarketTickProjectionAdapter | READY |
| active_vol / base_vol | MarketConditionAnalyzer.analyze(tick) | MarketConditionSensor의 tick history | READY |
| OHLC history / ATR | Reference price_history 기반 | MarketConditionSensor 내부 price history는 존재하나 Track4 read model 노출 없음 | ADAPTER SEAM NEEDED |
| current_equity / current_pnl | Reference Track4 현재 process_tick에서는 직접 공급하지 않음 | VSSF Account/PnL authoritative state + read-only AccountSnapshot projection | PARTIAL |
| current_delta / current_gamma | Reference Track4 현재 process_tick에서는 직접 공급하지 않음 | OptionProject에 authoritative Greeks provider 없음 | BLOCKED |
| premium_spent / accumulated_gamma_profit / theta_decay_cost | Reference Track4 현재 process_tick에서는 직접 공급하지 않음 | 전략/position attribution authoritative owner 없음 | BLOCKED |

확정 원칙:

- Reference의 기존 process_tick은 일부 Track4 확장 입력을 실제로 acquisition하지 않고 Basecamp 중심 최소 호출만 수행한다.

- Standard Track4는 Reference 기능 보존 과정에서 Delta Hedge, Theta Guard, Profit Trailing까지 명시적으로 typed input으로 확장되어 있으므로 Reference의 생략/기본값을 Standard Runtime synthetic fallback으로 복원하지 않는다.

- Market/volatility/history와 Account/PnL은 기존 authoritative source에서 read-only provider로 연결 가능하다.

- Greeks 및 strategy attribution metrics는 현재 authoritative owner가 없으므로 별도 Provider Port/Adapter seam 없이는 production Track4 payload를 완성할 수 없다.

- 따라서 다음 구현 단위는 process_tick() 자체가 아니라 source별 read-only provider contract이며, missing source는 fail-closed 한다.

## Track4 Runtime Provider Port — No.342

No.341의 다음 단계에 따라 기존 자산을 전수 대조했다.

확인된 read-only source:

- MarketConditionSensor: current_price, active_vol, base_vol

- VSSFAccountSnapshotAdapter + AccountProvider: Account/PnL projection

미연결/부재 source:

- Sensor 내부 가격 이력은 private state이며 Track4 OHLC read model contract 없음

- authoritative current_delta/current_gamma 없음

- premium_spent/accumulated_gamma_profit/theta_decay_cost attribution source 없음

따라서 contracts/track4_runtime_input_provider.py에 source별 ownership을 표현하는 최소 read-only Provider Port를 추가했다.

Track4RuntimeInputReadiness:

- market

- history

- account_pnl

- greeks

- attribution

다섯 source가 모두 authoritative하게 연결될 때만 is_complete=True이다. incomplete 상태에서는 Runtime이 synthetic payload/default를 생성하지 않는다.

## Track4 Account/PnL partial projection — No.343

- Track4VSSFAccountProjectionProvider를 추가했다.

- 기존 AccountProvider.snapshot()의 authoritative cash를 current_equity로, realized_pnl + unrealized_pnl을 current_pnl로 read-only projection한다.

- market/history/greeks/attribution은 연결하지 않았으며 호출 시 명시적으로 fail-closed 한다.

- 따라서 account_pnl만 READY이고 전체 readiness.is_complete는 계속 false다.

- MarketConditionSensor 내부 price history는 private state뿐이므로 기존 read-only OHLC projection seam은 발견하지 못했다.

## Runtime identity / execution seam audit — No.387

- VMS ReferenceCanonicalMarketTick.seq_id → CanonicalMarketTick.source_sequence is lossless through VMSMarketTickProjectionAdapter.

- RuntimeExecutionContext.tick_sequence consumes source_sequence directly; no legacy seq_id fallback is permitted.

- local_sequence remains owned by the production Runtime loop. StrategyOrchestrator.run() preserves deterministic signal collection order but does not own the counter.

- CanonicalStrategySignal.instrument_id is preserved unchanged by DecisionArbiter and validated at canonical transport; missing authoritative identity fails closed.

- Risk ALLOW/REDUCE/DENY remains authoritative for executable quantity. requested_price/order_type/order_purpose are supplied by Position/Execution Policy, never inferred by Risk or transport.

- Production process_tick() insertion remains deferred until Runtime-owned local ordinal, Track4 source completeness, and OrderIntentFactory invocation seams are all verified.

## Minimal process_tick boundary — No.392

- core/runtime/standard_option_runtime.py를 추가하여 Standard Runtime의 최소 process_tick() 경계를 materialize했다.

- Runtime은 source_sequence가 없는 tick에 counter fallback을 만들지 않고 즉시 fail-closed한다.

- tick timestamp가 존재하면 호출 observed_at과 일치해야 Strategy seam으로 전달한다.

- Runtime은 validated tick을 주입된 Strategy seam에 lossless 전달하며, Strategy seam이 Runtime-owned evaluation ordinal과 typed Track4 materialization을 담당한다.

- 이 단계는 Decision/Risk/OMS execution을 연결하지 않는다.

- instrument_id authoritative 공급 BLOCKED와 Profit Trailing attribution BLOCKED는 그대로 유지한다.

- 임시 Python workspace에서 최소 Runtime 경계 테스트 5 passed를 확인했다. 이는 추출한 최소 경계 검증이며 전체 OptionProject import graph 통합 PASS를 의미하지 않는다.

## Standard Runtime → Track4 seam integration boundary — No.393

- StandardOptionRuntime.process_tick()과 Track4 Runtime Strategy seam의 호출 경계를 별도 integration test로 연결했다.

- authoritative tick은 동일 객체와 동일 observed_at으로 seam에 lossless 전달된다.

- source_sequence 누락/비양수와 timestamp mismatch는 Track4 seam 진입 전에 Runtime에서 fail-closed한다.

- 이번 통합은 Runtime→Strategy seam 경계까지만 검증한다. Track4 materializer/orchestrator 내부와 Decision/Risk/OMS는 기존 별도 계약 범위를 유지한다.

- 임시 Python workspace에서 추출 최소 경계 테스트 3건 3 passed 확인.

- 실제 전체 OptionProject import graph/E2E PASS로 해석하지 않는다.