## Runtime

program_runtime.py is split:

- orchestration → application

- environment-neutral runtime state → core/runtime

- external synchronization → environment/contracts

## OMS

oms_fsm.py → core/oms state machine.

order_router.py is not migrated intact:

- order intent validation/state → core

- broker translation/send → environment execution adapter

## Risk

risk_engine.py decision logic → core/risk.

Account freshness/position snapshots enter through contracts.

## Sensor

Feature extraction/analyzer → core/sensor.

Recording/reporting/replay → support + tests.

Strategy-specific Track logic → core/strategy, not generic sensor infrastructure.