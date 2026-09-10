Paper Trading means the actual broker's VTS/paper system, not the existing VSSF virtual broker.

The environment owns KIS Paper credentials, endpoint, market-data adapter, broker/execution adapter, account/position snapshots and reconciliation.

Synthetic VMS/VSSF data must never be silently substituted for a failed Paper connection. Real API evidence remains a separate verification gate.