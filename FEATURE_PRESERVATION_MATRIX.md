<!-- Notion table block -->
| 기능 | Reference 위치 | 목표 위치 | 처리 |
| Canonical Tick/Order/Execution | shared/contracts | contracts | REFACTOR |
| Strategy/Sensor/Signal/Decision | option_program | core | REFACTOR |
| Risk | option_program/risk_control | core/risk | REFACTOR |
| OMS/FSM | option_program/orders | core/oms | REFACTOR |
| Option/DTE/Master | option_program | core/option + infrastructure | REFACTOR |
| Virtual Market | virtual_market_simulator | environments/virtual | REFACTOR |
| Virtual Firm | virtual_securities_firm | environments/virtual | REFACTOR |
| KIS Broker | option_program/broker | environments/paper/live + infrastructure | REFACTOR |
| WAL/Recovery | infra + runtime | infrastructure | KEEP/REFACTOR |
| Telemetry | infra | infrastructure/monitoring | KEEP/REFACTOR |
| Web UI | web_interface | interfaces/control_tower | REBUILD using requirements |
| Integrated TradingSystem | main.py | application/runtime_controller | REBUILD |

판정 원칙: 기존 기능을 최대한 유지하되 기존 조립 구조는 유지하지 않는다.