# High-Speed Replay Logging Contract v1

Status: replay-level trace and a read-only observer for actual Virtual broker submissions, canonical execution reports, and identity-bearing fills are implemented. End-to-end fast-vs-detailed semantic equivalence remains unverified.

## Purpose and non-goals

The logging mode is observation-only. It must not change input rows, event order, replay pacing policy, strategy selection, runtime decisions, risk checks, OMS/order routing, broker execution, positions, or P&L. It is not a performance report and does not validate profitability. The replay runner remains the sole driver of market events.

## Modes

- `fast` (default): no trace sink, no trace file, no trace serialization, and no execution observer hooks. Supplying `trace_output` is an error.
- `detailed`: requires an explicit new `trace_output` path. Parent directory must already exist. Existing paths are rejected and never overwritten. Output is UTF-8 JSONL. A temporary read-only observer is attached to the runner's single-leg and multi-leg Virtual broker acknowledgement adapters and detached in a `finally` path.
- Unknown modes fail closed. The CLI uses `--log-mode fast|detailed` and `--trace-output <new-path>`.

Example:

```powershell
py -m environments.high_speed.virtual_runtime_replay --dataset <dataset> --validation-only-synthetic --log-mode detailed --trace-output reports/synth/replay_trace_runA.jsonl
```

For the comparison phase, run both modes separately with the same dataset bytes, same seed/provenance, same strategy keys, same fixed run ID, same speed and event limits, and the same deterministic/injected clock assumptions. The trace output path itself must not be an input to the runtime.

## JSONL record contract

Each line has the following fields:

- `schema`: `high-speed-replay-trace-v1`
- `trace_sequence`: zero-based monotonic trace-record index
- `event_type`: `replay_started`, `market_event`, `order_command`, `execution_report`, `fill`, `execution_report_unavailable`, `fill_identity_unavailable`, or `replay_finished`
- `run_id`: explicit stable run ID for a comparison pair
- `event_sequence`: zero-based market event index for market and observer records; null otherwise
- `timestamp`: source tick timestamp for `market_event`; null when not supplied by the observer event
- `payload`: JSON object

`replay_started` records dataset label, selected strategies, logging mode, and whether validation-only synthetic mode is enabled. `market_event` records tick sequence/instrument identity, underlying price, per-event and cumulative signal/approval/routing/fill/rejection counters, execution IDs, cumulative strategy signal counts, observer status/counts, and account realized/unrealized/net P&L after the event. `replay_finished` records final counters, execution IDs, P&L, exhaustion state, and observer summary.

### Read-only order/fill observer

- The observer temporarily wraps only the existing Virtual broker acknowledgement adapters' `submit` method in detailed mode. It calls the original method once with unchanged arguments and returns the original result unchanged; it does not create, cancel, modify, retry, or reconcile orders.
- `order_command` records the actual canonical `BrokerOrderCommand` passed to the adapter. It is written after the original submit returns (or raises), so trace I/O cannot prevent that submit from being called.
- `execution_report` records the adapter's newly exposed canonical `ExecutionReport`. If no report is exposed, `execution_report_unavailable` records that fact; stale `last_report` values are not substituted after an exception.
- `fill` is emitted only when the canonical report contains a positive `filled_quantity` and a non-empty `execution_id`. A positive quantity without an execution ID emits `fill_identity_unavailable`, not a fabricated fill identity.
- Trace write errors inside this observer are contained so they do not change the broker method's return/exception. The observer summary marks `TRACE_WRITE_FAILED`; such a trace is incomplete and cannot support equivalence PASS.
- Observer hooks are detached in a `finally` block after replay. Fast mode does not attach them.

## Equivalence criteria

For the same input bytes and deterministic runtime settings, compare the fast report against detailed mode's semantic trace while excluding only non-semantic observability fields (`trace_sequence`, elapsed time, events/second, log mode, output path). Required equality: market event sequence and timestamps, strategy signal/decision outcomes, routed order identities and attributes, execution/fill identities/quantities/prices/statuses, positions, and realized/unrealized/net P&L. Any mismatch is `FAIL`; missing order/fill detail or observer write failure is `BLOCKED`; only complete equality is `PASS`.

## Safety boundaries

No KIS API, Live, account, order, modify, cancel, collector, or scheduler actions are part of this logging contract. It does not authorize strategy changes, parameter tuning, synthetic data generation, or commit/push. Synthetic and derived scenario provenance must remain explicit and separate from REAL_VTS.
