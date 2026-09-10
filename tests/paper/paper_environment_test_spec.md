- Virtual/VMS modules are absent from Paper runtime imports.

- Standard Core runs without modification.

- Paper uses KIS VTS credentials/endpoint/account only.

- Market and Broker are separate Contract implementations.

- Execution responses normalize into CanonicalExecutionReport.

- Account/Position snapshots reject stale data for new orders.

- Reconciliation compares broker state with internal OMS state.

- Restart recovers from broker state.

- No VSSF ledger receives Paper orders.

- Real API evidence is BLOCKED until valid credentials and endpoint responses are supplied.