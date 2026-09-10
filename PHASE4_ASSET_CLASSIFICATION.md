Reference: Exp_Detail_1 HEAD 51c57c1f88035523db9491fa56bbc52bcad9b20f

<!-- Notion table block -->
| Baseline Asset | Target | Decision |
| option_program/strategy | core/strategy | REFACTOR |
| option_program/signal | core/signal | REFACTOR |
| option_program/decision | core/decision | MOVE/REFACTOR |
| option_program/risk_control | core/risk | REFACTOR |
| option_program/orders/oms_fsm.py | core/oms | MOVE |
| option_program/orders/order_router.py | core order intent + environment execution | SPLIT |
| option_program/runtime/program_runtime.py | application + core/runtime | SPLIT |
| option_program/market_analysis | core/sensor/domain | REFACTOR |
| option_program/sensor/analyzer, feature_contract | core/sensor | MOVE/REFACTOR |
| recorder/report/replay feedback | support/observability + tests/replay | SPLIT |
| option_program/market_data | contracts + environment adapters | SPLIT |
| option_program/broker/kis_auth.py | infrastructure/external_api/kis | MOVE |
| option_program/broker/real_broker_adapter.py | environments/paper + environments/live | SPLIT |
| VMS | environments/virtual | REFACTOR |
| VSSF | environments/virtual | REFACTOR |
| infra/wal_store.py | infrastructure/persistence | MOVE |
| infra/telemetry*.py | infrastructure/telemetry | MOVE |
| infra/time_service.py | contracts/clock implementation | REFACTOR |
| shared/contracts/option_master.py | core/domain + infrastructure source adapter | SPLIT |
| shared/calendar | contracts/calendar + infrastructure source adapter | SPLIT |
| web_interface | interfaces/control_tower | REFACTOR |
| main.py | application entrypoint | REBUILD |
| .agents archive / Simple_Insert.py | legacy quarantine | EXCLUDE |

[Child Page] [No. 546] Live production caller 부재 상태에서 Control Tower executable 경계 재검증 및 caller 생성 보류 확정
## 처리내용
    - 직전 [No. 545]의 다음 단계에 따라 현재 OptionProject의 Live production caller 및 executable 경계를 재검토했다.
    - application/composition/live_runtime_production_factory.py와 관련 integration test가 존재하며 production assembly, bootstrap recovery, lifecycle graph, dependency identity 및 fail-closed 계약을 검증하는 상태임을 확인했다.
    - 실제 HTTP/UI server process 또는 concrete production entrypoint는 확인되지 않았다.
    - 따라서 Reference main.py의 monolithic caller를 복원하거나, 실제 근거 없이 HTTP/WebSocket server·background thread·multi-loop 구조를 생성하지 않는다.
    - 현재 single-loop async Control Tower 및 coordinator-owned adapter 경계를 유지한다.
    - 이번 단계에서는 OptionProject 소스 수정이 불필요하다고 판정했다.
## 검증 판정
PASS — 실제 production caller가 없는 상태에서 synthetic executable 구조를 추가하지 않고 현재 Target Architecture의 assembly/lifecycle 경계를 유지한다.
## 다음 단계
    - 실제 caller가 추가되거나 발견되면 먼저 event-loop/thread ownership을 확정한다.
    - 이후 caller → production factory → LiveRuntimeLifecycleCoordinator → Control Tower 호출 계약을 고정하고 targeted integration test를 추가한다.
    - caller가 계속 부재하면 현재 Control Tower/Live lifecycle의 executable 경계 검증을 계속하며 synthetic server/process는 생성하지 않는다.
### 다음 Process 위치
    - 다음 번호: [No. 547]
    - 위치: 현재 Process 하위 동일 레벨