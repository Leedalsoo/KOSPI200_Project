Current TradingSystem directly creates VMS, VSSF, Broker, OptionProgramRuntime, WAL and UI.

## Target

Control Tower UI

→ Runtime Controller

→ Environment Hub

→ Environment Bundle

→ Standard Contracts

→ Standard Option Core

## Split

- application/bootstrap.py: composition root only

- application/runtime_controller/: lifecycle and use-case orchestration

- application/environment_hub/: registry/factory

- environments/*: bundle assembly

- infrastructure/persistence/: WAL

- interfaces/control_tower/: UI server/websocket

No new main entrypoint may directly instantiate a specific VMS/VSSF/KIS implementation.