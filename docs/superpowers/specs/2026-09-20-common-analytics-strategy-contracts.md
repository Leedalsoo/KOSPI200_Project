# Common Analytics Contract + Strategy Plugin Contract

## Status
- Version: 1.0
- Scope: Strategy 1~9 shared Runtime/Analytics architecture.
- Priority: stabilize common Runtime; migrate and verify Strategy 2~9; defer Strategy 1.

## Goal
시장 원시데이터와 파생 분석을 전략 코드에서 분리하고, 동일 snapshot에서 공통 metric을 한 번만 계산한 뒤 여러 전략이 immutable 결과를 공유한다. 전략은 required feature를 선언하고 그 feature를 이용해 진입/유지/청산/reversal 판단과 execution proposal만 담당한다.

## Mandatory boundaries
1. `infrastructure/` owns external source adapters.
2. `application/` owns orchestration/materialization.
3. `contracts/` owns public DTO/ports.
4. `core/analytics/` owns environment-independent derived analytics.
5. `core/strategy/` owns strategy rules and strategy-local state only.
6. Strategy code never calls KIS, Historical Store, Broker, UI, or Scenario Store directly.
7. Identity, expiry, strike, option type, broker symbol, multiplier come only from authoritative sources.
8. Missing authoritative inputs are `UNAVAILABLE`/`BLOCKED`; no zero/false/default/synthetic fallback.

## MarketSnapshot
Immutable observation boundary containing `run_id`, `as_of`, source/provenance, authoritative instrument identity reference, last/trade, bid/ask, volume, open interest and order-book depth when supplied, plus session metadata. It contains observations, not strategy decisions and not derived indicator values.

## AnalyticsRequest
A strategy declares required metrics by stable key and parameters: metric key, timeframe/window, dependencies, freshness requirement, source/model requirement, and analytics version. Runtime unions requirements across active strategies before evaluation.

## AnalyticsSnapshot
Immutable derived view keyed by `run_id + instrument identity + as_of + timeframe/window + analytics_version`. Each metric carries value, status, unit, timestamp/as_of, calculation version, and provenance/dependency references. Statuses: `AVAILABLE`, `UNAVAILABLE`, `STALE`, `BLOCKED`.
## Single-computation rule
For one RunContext/as_of/window/version, a metric is evaluated at most once per canonical input set. The engine performs request-set union and dependency-aware batch evaluation. Results are memoized for the evaluation cycle and exposed read-only. Different timeframe/window/model/version is a distinct metric key and is not an accidental cache hit.

## Common Analytics Catalog
### Price / volume / microstructure
Last, trade, OHLC, returns, log returns, momentum, ROC, gap, VWAP, TWAP, volume, turnover, OI/OI change, mid, spread, spread ratio, depth, order-book imbalance, microprice, trade intensity, buy/sell pressure and cumulative volume/delta when authoritative input supports them.

### Technical indicators
SMA, EMA, WMA, HMA and slopes; RSI; MACD/signal/histogram; stochastic; Williams %R; CCI; ADX/DMI; Bollinger Bands/width/%B; Keltner; Donchian; ATR/TR; OBV; MFI; pivot; support/resistance; volume profile/POC/VAH/VAL.

### Volatility / statistics
Historical/realized volatility, close-to-close and range-based measures, EWMA volatility, intraday volatility, volatility ratio, rank/percentile, realized-vs-implied; rolling mean/std/variance/covariance/correlation, z-score, percentile/rank, beta, hedge ratio and explicitly required spread/cointegration metrics.

### Futures analytics
Basis, basis %, annualized basis, fair-value features when inputs are authoritative, calendar spread, roll spread and roll-yield features. Contract multiplier is referenced from contract master, never hard-coded by Strategy/Analytics.

### Options analytics
DTE, trading DTE, moneyness, log-moneyness, delta-moneyness, intrinsic/time value, IV, ATM IV, IV change/rank/percentile, smile/skew/slope, risk reversal, butterfly, term structure, calendar IV spread and surface snapshot/interpolation when chain/model inputs are complete.

### Greeks / portfolio
Delta, Gamma, Theta, Vega, Rho; net Greeks, exposure, gamma/delta exposure; selected second-order Greeks (Charm, Vanna, Vomma/Volga, Speed, Color) when model/input policy explicitly permits them. Position, PnL, fees, margin, premium attribution and insurance role come from authoritative read models.
## Options / Greeks source rule
KIS-supplied Greeks remain source-derived and are not silently replaced by model Greeks. Model-derived Greeks require explicit authoritative model inputs and version. IV/surface calculations fail closed when required forward/rate/dividend/chain inputs are unavailable. Source and derived values retain distinct provenance.

## StrategyPlugin Contract
Every strategy implements the existing Strategy lifecycle and declares `strategy_id`, `version`, required analytics feature keys, required source-status requirements, evaluation timeframe/freshness, strategy-local parameter schema and state reset/isolation requirements. Evaluation consumes `StrategyContext` plus the canonical AnalyticsSnapshot view and returns Signal/execution proposal through existing public contracts.

## Strategy responsibilities
Strategy may combine features, apply strategy thresholds/rules, maintain strategy-local finite state, decide entry/hold/exit/reversal, select an execution proposal and explain its decision. Strategy may not fetch market data, calculate shared indicators/Greeks, resolve contract identity, calculate authoritative portfolio/PnL/margin, call broker/KIS/UI, or mutate shared analytics.

## Strategy 2~9 mapping
- S2 Asymmetric Trap: BBW, volume z-score, OBI, basis, IV/skew, POC, volatility regime → trap decisions.
- S3 Statistical Arbitrage: spread statistics, z-score, correlation/beta, volatility, cost/valuation → stat-arb group decisions.
- S4 Gamma Scalping: Delta/Gamma/Theta, volatility, price range, exposure → hedge/rebalance/exit.
- S5 Gap Divergence: gap, realized volatility/std, z-score, MA/VWAP, regime → mean-reversion decisions.
- S6 Daily Tail Insurance: IV, DTE, volatility, Greeks, valuation → insurance activation/exit.
- S7 Weekly Skew Insurance: IV skew/surface/term structure, MA, DTE → weekly insurance/skew decisions.
- S8 Monthly Strangle: DTE, IV/surface, Greeks, regime, exposure/margin → monthly entry/rebuild/expiry decisions.
- S9 Event Overnight Insurance: authoritative event state, IV change, Greeks/exposure/margin → event hedge/reentry decisions.
- S1 Tail Defense: deferred; later uses the same contract after user-defined inputs/rules are revalidated.
## Verification model
Common Gate proves normalization, identity/provenance, history/window semantics, analytics correctness, freshness, fail-closed behavior, single-computation behavior, replay parity, RunContext isolation and Risk→OMS→Execution regression once. Plugin Gate proves feature declaration/availability plus strategy-specific rules, state transitions, proposal semantics and isolated lifecycle.

## Non-functional acceptance criteria
- No strategy-to-source direct calls.
- No duplicate implementation of a common metric in Strategy modules.
- No duplicate source fetch caused by multiple strategies requesting the same snapshot.
- No shared mutable AnalyticsSnapshot.
- No cross-run state leakage.
- Same canonical input + same analytics version produces deterministic values.
- Replay and Virtual use the same analytics implementation.
- Removing one strategy does not alter another strategy's input values or state.
- Existing identity/provenance and fail-closed execution boundaries remain intact.

## Migration rule
No big-bang rewrite. Introduce contracts and tests first, then migrate one strategy at a time. During migration, old strategy-specific calculations are not duplicated in the new layer; each migrated calculation has one owner. Remove obsolete paths only after focused and full regression evidence is green.

## Decision
This specification is the approved target contract for the next implementation phase. It changes architecture but does not itself modify runtime behavior. Implementation must follow TDD and the project verification procedure in AGENTS.md.