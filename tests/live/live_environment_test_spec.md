## Structural

- Live credential names are separate from Paper/VTS credentials.

- Live has no VSSF/VMS synthetic fallback.

- Live starts DISARMED.

- Live order submission requires explicit approval, limits, non-stale account/position state and an active broker connection.

## Safety

- Kill Switch blocks every new order.

- Order quantity, daily loss and position limits are mandatory.

- Duplicate client order identity cannot create a second submission.

- Timeout/retry must query broker state before any resend.

## Recovery

- Startup reads Broker Account/Position before resume.

- Broker/internal mismatch causes SAFE_STOP.

- Restart must not resend an already accepted order.

## External evidence

- Mock responses are never PASS for Live operation.

- Real credential, real Account/Position response and approved minimal-order evidence are required for EXTERNAL SYSTEM PROVEN.

- Physical execution is currently expected to remain BLOCKED without credentials/network/human approval.