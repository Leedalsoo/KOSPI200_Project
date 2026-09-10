## Core

OrderIntent creation only.

## Environment

OrderIntent → BrokerOrderCommand translation.

Broker handles submit/cancel/query.

ExecutionProvider supplies fills/status.

Account/Position providers supply read snapshots.

## Lifecycle states

CREATED

→ INITIALIZED

→ CONNECTED

→ READY

→ RUNNING

→ STOPPING

→ STOPPED

→ SHUTTING_DOWN

→ SHUTDOWN

Failure states are explicit.

## EnvironmentStatus

- environment_type

- lifecycle_state

- connection_state

- safety_state

- data_health

- execution_health

- warning list

Live additionally exposes:

- trading_enabled

- approval state

- kill_switch state

Control Tower consumes status only; internal objects remain hidden.