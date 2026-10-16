# S1–S9 KIS Runtime Caller-Chain Trace v0.1

- Date: 2026-10-15 KST
- Status: Read-only source trace; **NOT an approved implementation specification**
- Branch/HEAD: `Project200` / `3179d80c0f0d7ba0a74120740e23132e80b1aa7b`
- No runtime code, tests, Manifest, or Git history changed.

## 1. Confirmed Virtual runtime composition

1. `application/composition/runtime_composition_factory.py::create_virtual_runtime_controller` builds `VirtualCompositionDependencies`.
2. `application/composition/virtual_composition_root.py` creates the authoritative KIS Option Master if none is injected, then creates the Virtual environment builder/factory.
3. `application/composition/concrete_virtual_environment_builder.py` creates `VirtualMarketSimulatorRuntime`, subscribes its ticks to the Virtual broker, and returns a Virtual bundle.
4. `application/composition/automated_virtual_runtime_factory.py::attach_standard_automated_loop` creates `StandardRuntimeInputProvider` using `bootstrap.bundle.market`, constructs strategy-specific providers/resolvers, then calls `bootstrap.bundle.market.subscribe(loop.on_tick)`.
5. `AutomatedVirtualTradingLoop.on_tick` derives `MarketState` from the incoming VMS tick and creates single-order commands using tick prices. This is the Virtual path, not evidence that the saved KIS raw WebSocket frames are feeding the same runtime.
6. The factory injects a caller-supplied `historical_observation_option_source` into Track1 delta, option order-book, and Track2 IV inputs when present. The factory code inspected does not itself instantiate that source from the current raw KIS collector or subscribe the option adapter to the raw WebSocket stream. The full source-to-source wiring remains **NOT_PROVEN**.

## 2. Source injection actually visible in the factory

| Input | Factory wiring observed | Proof boundary |
|---|---|---|
| Option contract/expiry identity | KIS Option Master bundle and `KisOptionMasterExpirySource`; strategy-specific contract sources for S2/S5/S6/S7/S8 | Master identity injection is visible; it does not prove a quote exists or is fresh. |
| S1 option delta | `historical_observation_option_source` passed as `track1_option_delta_source` | If absent, the source is absent. Collector-to-source injection and source timestamp lineage are not proven here. |
| S2 option IV | `historical_observation_option_source` or default `KISTrack2OptionIVSource(option_master)` | Default source's `update_observation` requires a `KisIndexOptionMarketObservation`; the inspected factory does not show a raw WS adapter/subscription feeding it. |
| S2 basis/metrics/volume | Constructs `KISBasisSource`, `KISTrack2MarketMetricsSource`, `KISVolumeProfileSource` and `KISTrack2MarketObservationSink` in non-synthetic mode; assigns the sink to the loop | The inspected `AutomatedVirtualTradingLoop.on_tick` path does not invoke this sink. An active KIS futures observation → sink → strategy update path is not proven. |
| S3 futures identity/input | `KISTrack3RuntimeInputSource` by default and KIS futures master identity source; synthetic source replaces it in synthetic mode | Identity/input object construction is visible; source observation timing and source-to-signal provenance are not carried to admission in the observed path. |
| S4 Greeks | Caller-supplied `track4_greeks_provider` | The factory does not construct a KIS provider here; actual source and lifecycle are caller-dependent and not proven from this file alone. |
| S5 daily reference | `KISKOSPI200DailySource(KISAuthManager.from_env(is_vts=True))` in non-synthetic mode | KIS TR source is constructed; no source timestamp/freshness verdict is attached to the final plan/admission in this path. |
| S6 volatility | `KISTrack6ATMVolatilitySource` receives the selected Track2 IV source | Depends on a populated IV source; actual population and source-time semantics remain unproven. |
| S7/S8 option contracts | KIS Option Master contract sources | Contract identity/selection injection is visible; current executable quote and per-leg source freshness are not proven. |
| S9 ATM IV/event | History-backed source/materializer is only constructed when the history path is supplied | Actual event/IV source availability and authoritative current short-PUT position are not proven by the current-day market-data partition. |

## 3. Timestamp construction risk in the inspected source

- `contracts/kis_index_option_market_ws_adapter.py` stores option `observed_hour` as the time-only string from H0IOCNT0/H0IOASP0.
- `infrastructure/kis/track2_option_iv_source.py::_observed_at(raw, session_date)` combines that time-only string with a caller-supplied `session_date` to create a naive datetime. Official date association, timezone and event-time semantics have not been proven. This is an audit finding only; no code change was made.
- `infrastructure/kis/historical_observation_sources.py::HistoricalObservationOptionSource` indexes observations using `observation.observed_at or observation.collected_at`. Because the KIS REST normalizer returns `observed_at=None`, this replay source may order records by collection time rather than verified source event time. That can support deterministic replay ordering but is not proof of live source-age freshness.
- REST normalizer sets `MarketObservation.observed_at=None` and `raw_reference=None`; collector records request/receive timestamps and raw payload hash. Absolute source-time semantics remain unresolved.

## 4. Final admission and multi-leg boundary

- Single-order route: `AutomatedVirtualTradingLoop.on_tick` → `route_from_runtime_authoritative_sources` → `RiskGate.admit_order` → approval-token check → `StandardOrderRouter.register_and_route` → Virtual broker.
- `route_from_runtime_authoritative_sources` has no required typed KIS freshness/provenance verdict parameter. `StandardOrderRouter` checks command, approval token and broker adapter, but no source-freshness contract.
- Multi-leg route in `AutomatedVirtualTradingLoop.on_tick` calls `self.multi_leg_executor(multi_leg_plan)` directly; any existing group-risk preflight is not evidence of source timestamp/freshness enforcement. The equivalent freshness check at the multi-leg boundary is **NOT_PROVEN**.
- The inspected path updates the Virtual execution FSM from Virtual broker reports. This does not prove reconciliation against actual KIS account/order/fill/cancel/position data.
- No observed route provides proof that every S1–S9 source-derived input carries raw hash/reference, source timestamp, receive timestamp, environment/capability and a mandatory freshness verdict to final admission.

## 5. Result and next gate

- Virtual registry/resolver and some source-port injection: **PARTIAL / STATIC PATH EVIDENCE**.
- Saved KIS raw → active runtime provider → S1–S9 signal/plan: **NOT_PROVEN end-to-end**.
- Single-order and multi-leg freshness enforcement: **BLOCKED / NOT_PROVEN**.
- H0IOCNT0 saved frames vs official VTS capability note: **CONFLICT UNRESOLVED**; no retries.
- Next permitted action: prepare the exact candidate file/diff map and FRESH-01–14 assertions from these concrete gaps. Do not implement until timestamp semantics and exact scope are resolved and the user explicitly approves implementation.


## 6. Official KIS capability check

The official KIS Open API sample at https://github.com/koreainvestment/open-trading-api/blob/main/examples_user/domestic_futureoption/domestic_futureoption_functions_ws.py states:
- H0IOCNT0 index-option realtime conclusion is live-account-only and not supported in simulated trading; it includes `bsop_hour`, option price/volume, Greeks and IV-related fields (lines 2984–3005).
- H0IOASP0 index-option realtime quote is live-account-only and not supported in simulated trading; it includes `bsop_hour`, option bid/ask levels and quantities (lines 3170–3184).

Therefore, the 796 H0IOCNT0 records in the VTS-labeled raw file are conflicting historical evidence, not authorization or proof of VTS capability. The option WS source must be classified `BLOCKED_SOURCE_CAPABILITY` for VTS until KIS supplies an explicit updated written statement. No retries were made.
