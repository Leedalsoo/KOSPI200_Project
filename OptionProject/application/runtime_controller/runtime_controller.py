# 구현 예정: Architecture와 Standard Contract 확정 후 실제 코드 작성.
# 현재 Controller는 Environment lifecycle을 조립/관리하는 경계이며, StrategyOrchestrator의 Signal에 Runtime sequence를 직접 주입하는 책임은 확인되지 않았다. 따라서 RuntimeSignalContext를 Controller 내부 상태에서 임의 생성하지 않는다.
# Canonical signal 변환을 실제 실행 흐름에 연결할 때에는 Controller가 실제 tick의 authoritative seq_id와 현재 Strategy 평가 단위의 local sequence를 가지고 있는지 먼저 확인해야 한다. 확인되지 않은 경우 Adapter 호출만 추가하고 signal_id를 합성해서는 안 된다.
# Track4 통합의 최소 입력은 Signal(execution_proposal) + Controller가 실제 공급하는 RuntimeSignalContext이며, 이 둘이 모두 존재할 때만 DecisionArbiter에 전달한다.
# Controller 현재 책임은 Environment lifecycle 조립/시작/정지이며, Strategy 평가 결과의 Runtime sequence를 생성·보관하는 구현은 확인되지 않았다. 따라서 RuntimeSignalContext를 Controller API에 억지로 추가하지 않는다. 실제 Reference의 signal_id는 program_runtime.py의 tick sequence와 strategy/local sequence 조합에서 생성되므로, 향후 Standard Runtime 실행 루프에서 동일한 authoritative sequence가 존재하는 지점이 확인될 때 그 지점에서 Context를 생성해 Adapter에 전달한다.
