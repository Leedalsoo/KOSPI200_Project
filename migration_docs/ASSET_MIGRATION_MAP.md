## option_program

- decision → core/decision

- market_analysis → core/sensor 또는 core/domain 분석

- sensor → core/sensor

- signal → core/signal

- strategy → core/strategy

- risk_control → core/risk

- orders/oms_fsm → core/oms

- orders/order_router → core order intent와 environment execution으로 분해

- runtime/program_runtime → application/runtime_controller + core/runtime으로 분해

- market_data → contracts + environment implementation으로 분해

- broker/kis_auth, real_broker_adapter → infrastructure/external_api + paper/live

- interface/* → interfaces 또는 application notification contract

- control/* → Control Tower 요구사항 Reference

## VMS

- market/engine/scenario/replay → environments/virtual

- accelerated clock/replay → environments/high_speed로 재사용 가능

## VSSF

- broker/exchange/execution → environments/virtual

- account/position → Account Contract 구현

- ledger/pnl/margin → virtual environment state

- reconciliation/recovery → infrastructure safety/recovery contract와 연결

## shared / infra

- Canonical DTO → contracts 또는 core/domain

- calendar/option master → domain input contract + infrastructure provider

- WAL → infrastructure/persistence

- telemetry → infrastructure/telemetry

- time_service → contracts/clock 구현

## UI

- web_interface → interfaces/control_tower

- 구 control panel → 기능 요구사항 Reference로만 사용