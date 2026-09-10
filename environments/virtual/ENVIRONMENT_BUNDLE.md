## Ownership

- Market: synthetic VMS-derived source

- Clock: Virtual clock contract implementation

- Broker: VSSF-derived virtual broker

- Account/Position: virtual state

- Execution: virtual execution policy

- Reconciliation/Recovery: virtual environment responsibility

## Isolation

Virtual implementation may use synthetic data, but that data must never satisfy Paper/Live external-data evidence.

## Feature preservation

The baseline's stress scenarios, market simulation, VSSF margin/PnL/ledger, reconciliation and recovery are migration targets. They are not replaced with arbitrary simplified business rules.