<!-- Notion table block -->
| 기존 영역 | 신규 후보 |
| Strategy/Sensor/Decision | core/strategy, core/signal, core/decision |
| Risk/Position | core/risk, core/position |
| OMS/Order | core/oms + contracts |
| Option Master/DTE | core/option |
| Program Runtime | application/runtime_controller 및 core/runtime로 분해 |
| Virtual Market | environments/virtual |
| Virtual Securities Firm | environments/virtual |
| KIS Adapter | environments/paper/live + infrastructure |
| UI | interfaces/control_tower |
| WAL/Telemetry/Config | infrastructure/support |
| Tests | tests/unit, integration, e2e, regression, safety |

세부 파일별 최종 판정은 실제 호출/의존 경로를 확인한 뒤 기록한다.