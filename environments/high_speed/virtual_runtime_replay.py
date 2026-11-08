"""High-Speed Replay -> real Virtual Runtime -> Strategy -> Decision -> Risk -> Virtual Execution."""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
from decimal import Decimal

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources, build_synthetic_option_master
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.validation_only_track6_execution import Track6SyntheticExecutionGate
from environments.high_speed.validation_only_track7_execution import S7ValidationOnlyRuntimeAdapter
from contracts.strategy_runtime_status import StrategyRuntimeStatus
from core.strategy.track6_order_lifecycle import Track6LifecycleConfig
from contracts.clock import ClockProvider
from environments.high_speed.replay_trace import ReplayExecutionObserver, ReplayLogMode, ReplayTraceController


@dataclass(frozen=True)
class HighSpeedVirtualReplayReport:
    dataset: str
    run_id: str
    events: int
    signals: int
    approved: int
    routed: int
    filled: int
    rejected: int
    execution_ids: tuple[str, ...]
    elapsed_seconds: float
    events_per_second: float
    exhausted: bool
    pnl_status: str
    multi_leg_decisions: int
    strategy_signal_counts: tuple[tuple[str, int], ...]
    strategy_status: tuple[StrategyRuntimeStatus, ...]
    realized_pnl: float
    unrealized_pnl: float
    net_pnl: float
    trace_status: str = "DISABLED_FAST_MODE"
    execution_observer_summary: dict[str, object] | None = None


def _publish_contract_scoped_replay_quote(tick, *, option_master, market, order_book) -> None:
    """Publish only the quote carried by this exact synthetic option-contract tick."""
    from math import isfinite
    from decimal import Decimal
    from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry

    synthetic_id = getattr(tick, "synthetic_contract_id", None)
    instrument_id = getattr(tick, "instrument_id", None)
    if not isinstance(synthetic_id, str) or not synthetic_id.startswith("SYNTHETIC_CONTRACT:"):
        raise ValueError("DERIVED_SCENARIO_SYNTHETIC_CONTRACT_ID_REQUIRED")
    if instrument_id != synthetic_id:
        raise ValueError("DERIVED_SCENARIO_INSTRUMENT_ID_MISMATCH")
    identity = option_master.get_contract_identity(synthetic_id)
    if identity is None:
        raise ValueError("DERIVED_SCENARIO_OPTION_CONTRACT_IDENTITY_REQUIRED")
    if getattr(identity, "stnd_iscd", None) is not None:
        raise ValueError("DERIVED_SCENARIO_STANDARD_ID_PROMOTION_FORBIDDEN")
    if getattr(identity, "shrn_iscd", None) != synthetic_id:
        raise ValueError("DERIVED_SCENARIO_CONTRACT_IDENTITY_MISMATCH")

    try:
        tick_expiry = require_exact_option_expiry(tick.expiry)
        identity_expiry = require_exact_option_expiry(identity.expiry)
    except (CanonicalOptionExpiryError, TypeError, ValueError) as exc:
        raise ValueError("DERIVED_SCENARIO_EXACT_EXPIRY_REQUIRED") from exc
    if tick_expiry != identity_expiry:
        raise ValueError("DERIVED_SCENARIO_EXPIRY_IDENTITY_MISMATCH")
    if str(tick.option_type).upper() != str(identity.option_type).upper():
        raise ValueError("DERIVED_SCENARIO_OPTION_TYPE_IDENTITY_MISMATCH")
    if Decimal(str(tick.strike_price)) != Decimal(str(identity.strike)):
        raise ValueError("DERIVED_SCENARIO_STRIKE_IDENTITY_MISMATCH")

    try:
        bid, ask, last = float(tick.bid_price), float(tick.ask_price), float(tick.last_price)
        multiplier = float(identity.contract_multiplier)
        tick_multiplier = float(tick.contract_multiplier)
    except (TypeError, ValueError) as exc:
        raise ValueError("DERIVED_SCENARIO_CONTRACT_QUOTE_INVALID") from exc
    # A zero bid is an intentional one-sided-quote scenario in the synthetic
    # dataset. Preserve it as unavailable bid liquidity; reject negative/non-finite
    # prices and require a positive ask/last/multiplier.
    if not all(isfinite(value) for value in (bid, ask, last, multiplier, tick_multiplier)):
        raise ValueError("DERIVED_SCENARIO_CONTRACT_QUOTE_INVALID")
    if bid < 0 or not all(value > 0 for value in (ask, last, multiplier, tick_multiplier)):
        raise ValueError("DERIVED_SCENARIO_CONTRACT_QUOTE_INVALID")
    if ask <= bid:
        raise ValueError("DERIVED_SCENARIO_CONTRACT_BID_ASK_INVALID")
    if tick_multiplier != multiplier:
        raise ValueError("DERIVED_SCENARIO_MULTIPLIER_IDENTITY_MISMATCH")

    option_type = str(identity.option_type).upper()
    strike = float(identity.strike)
    market.register_replay_option_quote(
        symbol=synthetic_id,
        option_type=option_type,
        strike=strike,
        expiry=tick_expiry,
        bid=bid,
        ask=ask,
        last=last,
        timestamp=tick.timestamp,
        contract_multiplier=multiplier,
        source="SYNTHETIC:DERIVED_SCENARIO",
    )
    # Never route this validation-only identity through a Standard instrument ID.
    order_book.update_bid_ask(bid, ask, instrument_id=synthetic_id)


class HighSpeedVirtualRuntimeReplayRunner:
    """Feed high-speed replay events through the existing Virtual Runtime boundary."""

    def __init__(self, dataset: str | Path, *, run_id: str | None = None, strategy_keys=None,
                 track3_runtime_input_source=None, initial_capital: float = 250_000_000.0, track5_opening_gap_points: float = 0.0,
                 validation_only_synthetic: bool = False,
                 validation_only_synthetic_manifest: str | Path | None = None,
                 validation_only_s8_risk_profile: str | Path | None = None,
                  validation_only_s9_contract_profile: str | Path | None = None,
                  validation_only_s9_risk_profile: str | Path | None = None,
                  validation_only_s9_restart_snapshot_path: str | Path | None = None,
                  validation_only_s7_risk_profile: str | Path | None = None,
                 validation_only_track6_signal_mode: bool = False,
                 validation_only_track6_execution_mode: bool = False,
                 validation_only_track6_lifecycle_config: Track6LifecycleConfig | None = None,
                 validation_only_track6_risk_profile: str | Path | None = None,
                 clock: ClockProvider | None = None,
                 log_mode: ReplayLogMode | str = ReplayLogMode.FAST, trace_output: str | Path | None = None):
        self.dataset = Path(dataset)
        self.validation_only_synthetic = bool(validation_only_synthetic)
        self.validation_only_synthetic_manifest = validation_only_synthetic_manifest
        self.validation_only_s8_risk_profile = validation_only_s8_risk_profile
        self.validation_only_s9_contract_profile = validation_only_s9_contract_profile
        self.validation_only_s9_risk_profile = validation_only_s9_risk_profile
        self.validation_only_s9_restart_snapshot_path = validation_only_s9_restart_snapshot_path
        self.s9_restart_restore_status = None
        if (self.validation_only_s9_contract_profile is None) != (self.validation_only_s9_risk_profile is None):
            raise ValueError("S9_VALIDATION_CONTRACT_AND_RISK_PROFILES_REQUIRED_TOGETHER")
        if self.validation_only_s9_risk_profile is not None:
            if not self.validation_only_synthetic or self.validation_only_synthetic_manifest is None:
                raise ValueError("S9_VALIDATION_PROFILES_REQUIRE_SYNTHETIC_MANIFEST")
            selected_ids = {key[0] if isinstance(key, tuple) else str(key) for key in (strategy_keys or ())}
            if selected_ids != {"track9_event_overnight_insurance"}:
                raise ValueError("S9_VALIDATION_RUN_MUST_SELECT_ONLY_STRATEGY9")
            if self.validation_only_s8_risk_profile is not None or validation_only_track6_execution_mode:
                raise ValueError("S9_VALIDATION_CANNOT_SHARE_OTHER_STRATEGY_GATES")
        if self.validation_only_s9_restart_snapshot_path is not None and self.validation_only_s9_risk_profile is None:
            raise ValueError("S9_RESTART_REQUIRES_VALIDATION_ONLY_S9_RUNTIME")
        self.validation_only_s7_risk_profile = validation_only_s7_risk_profile
        if self.validation_only_s7_risk_profile is not None and (not self.validation_only_synthetic or self.validation_only_synthetic_manifest is None):
            raise ValueError("S7_VALIDATION_RISK_PROFILE_REQUIRES_SYNTHETIC_MANIFEST")
        if self.validation_only_s8_risk_profile is not None and (not self.validation_only_synthetic or self.validation_only_synthetic_manifest is None):
            raise ValueError("S8_VALIDATION_RISK_PROFILE_REQUIRES_SYNTHETIC_MANIFEST")
        if self.validation_only_synthetic_manifest is not None and not self.validation_only_synthetic:
            raise ValueError("SYNTHETIC_MANIFEST_REQUIRES_VALIDATION_ONLY_MODE")
        self.validation_only_track6_signal_mode = bool(validation_only_track6_signal_mode)
        self.validation_only_track6_execution_mode = bool(validation_only_track6_execution_mode)
        self.validation_only_track6_lifecycle_config = validation_only_track6_lifecycle_config
        self.validation_only_track6_risk_profile = validation_only_track6_risk_profile
        if self.validation_only_track6_risk_profile is not None and not self.validation_only_track6_execution_mode:
            raise ValueError("TRACK6_RISK_PROFILE_REQUIRES_VALIDATION_ONLY_EXECUTION_MODE")
        if self.validation_only_track6_lifecycle_config is not None and not self.validation_only_track6_execution_mode:
            raise ValueError("TRACK6_LIFECYCLE_MATRIX_REQUIRES_VALIDATION_ONLY_EXECUTION_MODE")
        if self.validation_only_track6_execution_mode and (not self.validation_only_synthetic or self.validation_only_track6_signal_mode or self.validation_only_synthetic_manifest is None):
            raise ValueError("TRACK6_SYNTHETIC_EXECUTION_REQUIRES_EXPLICIT_SYNTHETIC_MANIFEST")
        if self.validation_only_track6_signal_mode and not self.validation_only_synthetic:
            raise ValueError("TRACK6_SIGNAL_OBSERVATION_REQUIRES_SYNTHETIC_VALIDATION_MODE")
        self.run_id = run_id or f"HS-{uuid4()}"
        self.strategy_keys = tuple(strategy_keys) if strategy_keys else None
        self.track3_runtime_input_source = track3_runtime_input_source
        self.initial_capital = float(initial_capital)
        self.track5_opening_gap_points = float(track5_opening_gap_points)
        self.clock = clock
        self.trace = ReplayTraceController(log_mode, output_path=trace_output)
        self.track6_synthetic_execution_gate = None
        self.s8_validation_runtime_adapter = None
        self.s9_validation_runtime_adapter = None
        self.s9_runtime_snapshot = None
        self.s9_runtime_provider = None
        self.s9_strategy = None
        self.s7_validation_runtime_adapter = None

    def run(self, *, start: str | None = None, end: str | None = None,
            speed: float = float("inf"), max_events: int | None = None) -> HighSpeedVirtualReplayReport:
        self.trace.emit(
            "replay_started", run_id=self.run_id,
            payload={"dataset": self.dataset.name, "log_mode": self.trace.mode.value,
                     "strategy_keys": list(self.strategy_keys) if self.strategy_keys else None,
                     "validation_only_synthetic": self.validation_only_synthetic,
                     "validation_only_track6_execution_mode": self.validation_only_track6_execution_mode},
        )
        # P5 requires an explicit validation-only mode. Legacy replay keeps its existing
        # input contract and is never silently reinterpreted as a synthetic-ID dataset.
        synthetic_adapter = (
            SyntheticReplayAdapter(
                self.dataset,
                manifest_path=self.validation_only_synthetic_manifest,
            )
            if self.validation_only_synthetic
            else None
        )
        validation_calendar = None
        if self.validation_only_synthetic_manifest is not None:
            from environments.high_speed.validation_only_trading_calendar import (
                load_validation_only_trading_calendar,
            )
            validation_calendar = load_validation_only_trading_calendar(
                self.validation_only_synthetic_manifest, self.dataset
            )
        synthetic_quote_batches: dict[str, tuple[Any, ...]] = {}
        if synthetic_adapter is not None:
            from collections import defaultdict
            quote_batches = defaultdict(list)
            for dataset_file in sorted(self.dataset.glob("*.jsonl")):
                with dataset_file.open(encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        adapted_record = synthetic_adapter.adapt_record(json.loads(line))
                        quote_tick = SimpleNamespace(**adapted_record["tick"])
                        quote_batches[str(quote_tick.timestamp)].append(quote_tick)
            synthetic_quote_batches = {key: tuple(value) for key, value in quote_batches.items()}
        synthetic_sources = SyntheticRuntimeSources(
            track5_opening_gap_points=self.track5_opening_gap_points,
            clock=self.clock,
            calendar=validation_calendar,
        )
        if self.validation_only_s7_risk_profile is not None:
            selected_ids = {key[0] if isinstance(key, tuple) else str(key) for key in (self.strategy_keys or ())}
            if selected_ids != {"track7_volatility_skew_weekly_insurance"}:
                raise ValueError("S7_VALIDATION_RUN_MUST_SELECT_ONLY_STRATEGY7")
            self.s7_validation_runtime_adapter = S7ValidationOnlyRuntimeAdapter(
                dataset=self.dataset, manifest_path=self.validation_only_synthetic_manifest,
                risk_profile_path=self.validation_only_s7_risk_profile,
            )
            self.s7_validation_runtime_adapter.bind_run_id(self.run_id)
        if self.validation_only_s8_risk_profile is not None:
            selected_ids = {key[0] if isinstance(key, tuple) else str(key) for key in (self.strategy_keys or ())}
            if selected_ids != {"track8_macro_regime_monthly_strangle"}:
                raise ValueError("S8_VALIDATION_RUN_MUST_SELECT_ONLY_STRATEGY8")
            from environments.high_speed.validation_only_s8_runtime_adapter import S8ValidationOnlyRuntimeAdapter
            self.s8_validation_runtime_adapter = S8ValidationOnlyRuntimeAdapter(dataset=self.dataset, manifest_path=self.validation_only_synthetic_manifest, risk_profile_path=self.validation_only_s8_risk_profile)
            self.s8_validation_runtime_adapter.bind_run_id(self.run_id)
        if self.validation_only_s9_risk_profile is not None:
            from application.composition.track9_validation_only_runtime_adapter import Track9ValidationOnlyRuntimeAdapter
            self.s9_validation_runtime_adapter = Track9ValidationOnlyRuntimeAdapter(
                dataset=self.dataset,
                manifest_path=self.validation_only_synthetic_manifest,
                contract_profile_path=self.validation_only_s9_contract_profile,
                risk_profile_path=self.validation_only_s9_risk_profile,
            )
            self.s9_validation_runtime_adapter.bind_run_id(self.run_id)
            self.initial_capital = float(self.s9_validation_runtime_adapter.evidence.initial_capital_krw)
        if self.validation_only_track6_execution_mode:
            from environments.high_speed.validation_only_track6_execution import Track6SyntheticExecutionGate
            self.track6_synthetic_execution_gate = Track6SyntheticExecutionGate(
                dataset=self.dataset, manifest_path=self.validation_only_synthetic_manifest,
                risk_profile_path=(self.validation_only_track6_risk_profile
                                   or Track6SyntheticExecutionGate.__init__.__defaults__[1]),
            )
            self.track6_synthetic_execution_gate.bind_run_id(self.run_id)
            self.initial_capital = float(self.track6_synthetic_execution_gate.evidence.configured_capital_krw)
        if synthetic_adapter is None:
            option_master = build_synthetic_option_master(self.dataset)
        else:
            option_master = build_synthetic_option_master(
                self.dataset, validation_only_adapter=synthetic_adapter
            )
        bootstrap = create_virtual_runtime_bootstrap(
            option_master=option_master, initial_capital=self.initial_capital,
            strategy_keys=self.strategy_keys or (),
        )
        # create_virtual_runtime_bootstrap already creates the UI/runtime loop.
        # High-Speed replay needs a second composition with DERIVED_SCENARIO
        # sources, so detach the bootstrap loop before attaching the replay loop.
        existing_loop = getattr(bootstrap, "automated_loop", None)
        if existing_loop is not None:
            bootstrap.bundle.market.unsubscribe(existing_loop.on_tick)
        loop = attach_standard_automated_loop(
            bootstrap,
            strategy_keys=self.strategy_keys,
            run_id=self.run_id,
            track3_runtime_input_source=self.track3_runtime_input_source,
            synthetic_runtime_sources=synthetic_sources,
            track4_greeks_provider=synthetic_sources,
            validation_only_track6_signal_mode=self.validation_only_track6_signal_mode,
            validation_only_track6_execution_gate=self.track6_synthetic_execution_gate,
            validation_only_s8_runtime_adapter=self.s8_validation_runtime_adapter,
            validation_only_s9_runtime_adapter=self.s9_validation_runtime_adapter,
            validation_only_s7_runtime_adapter=self.s7_validation_runtime_adapter,
            validation_only_track6_lifecycle_config=self.validation_only_track6_lifecycle_config,
        )
        self.s9_runtime_provider = getattr(loop, "standard_runtime_input_provider", None)
        self.s9_strategy = getattr(loop, "s9_strategy", None)
        # High-speed replay replaces the bootstrap loop; rebind the broker read model
        # to the bridge actually executing this replay instead of the detached bridge.
        replay_bridge = getattr(loop, "multi_leg_bridge", None)
        if replay_bridge is None:
            raise RuntimeError("HIGH_SPEED_REPLAY_MULTI_LEG_BRIDGE_REQUIRED")
        if self.validation_only_s9_restart_snapshot_path is not None:
            from environments.high_speed.validation_only_s9_restart import restore_restart_snapshot
            vssf_for_restore = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
            self.s9_restart_restore_status = restore_restart_snapshot(
                self.validation_only_s9_restart_snapshot_path, run_id=self.run_id,
                adapter=self.s9_validation_runtime_adapter,
                vssf_runtime=vssf_for_restore, replay_bridge=replay_bridge,
            )
        bootstrap.bundle.broker_api.attach_group_read_model(
            snapshot_reader=replay_bridge.position_groups.snapshot,
            reports_reader=replay_bridge.group_reports,
            group_ids_reader=lambda: tuple(replay_bridge.position_groups.all().keys()),
        )
        observer = None
        if self.trace.mode is ReplayLogMode.DETAILED:
            observer = ReplayExecutionObserver(self.trace, run_id=self.run_id)
            try:
                observer.attach(loop.broker_adapter, adapter_name="single_leg")
                observer.attach(replay_bridge.ack, adapter_name="multi_leg")
            except Exception:
                observer.detach()
                raise
        totals = {"events": 0, "signals": 0, "approved": 0, "routed": 0, "filled": 0, "rejected": 0}
        execution_ids: list[str] = []
        multi_leg_decisions = 0
        strategy_signal_counts: dict[str, int] = {}
        strategy_status: dict[str, StrategyRuntimeStatus] = {}

        original_arbitrate = loop.strategy_to_decision.arbitrate
        def capture_arbitrate(*args, **kwargs):
            nonlocal multi_leg_decisions
            result = original_arbitrate(*args, **kwargs)
            multi_leg_decisions += len(result.multi_leg_decisions)
            for canonical in result.canonical_signals:
                strategy_signal_counts[canonical.track_id] = strategy_signal_counts.get(canonical.track_id, 0) + 1
            return result
        loop.strategy_to_decision.arbitrate = capture_arbitrate

        vssf_runtime = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime

        def mark_positions(spot: float) -> None:
            account_source = vssf_runtime.account
            for symbol in tuple(account_source.positions):
                if str(symbol).endswith("_FUTURES"):
                    account_source.update_tick_price(
                        float(spot), instrument_id=symbol
                    )
                    continue
                identity = option_master.get_contract_identity(symbol)
                if identity is None or identity.option_type is None or identity.strike is None:
                    continue
                expiry = str(identity.expiry).replace("-", "")[:8]
                if str(symbol).startswith("SYNTHETIC_CONTRACT:"):
                    quote = bootstrap.bundle.market.option_quotes_by_instrument_id.get(symbol)
                    if (not isinstance(quote, dict)
                            or quote.get("source") != "SYNTHETIC:DERIVED_SCENARIO"
                            or str(quote.get("instrument_id", "")) != str(symbol)
                            or str(quote.get("option_type", "")).upper() != str(identity.option_type).upper()
                            or str(quote.get("expiry", "")).replace("-", "")[:8] != expiry):
                        continue
                else:
                    key = (str(identity.option_type).upper(), float(identity.strike), expiry)
                    quote = bootstrap.bundle.market.option_quotes.get(key)
                if quote is not None:
                    account_source.update_tick_price(quote["last"], instrument_id=symbol)

        def publish(tick) -> None:
            if observer is not None:
                observer.event_sequence = totals["events"]
            # Prime every contract quote sharing this exact event timestamp before
            # strategy evaluation. This creates one coherent synthetic snapshot
            # without advancing the analytics clock or mixing different timestamps.
            if self.validation_only_synthetic:
                for quote_tick in synthetic_quote_batches.get(str(tick.timestamp), ()):
                    synthetic_sources.prime_option_quote(quote_tick)
                    _publish_contract_scoped_replay_quote(
                        quote_tick, option_master=bootstrap.bundle.option_master,
                        market=bootstrap.bundle.market, order_book=vssf_runtime.order_book,
                    )
            synthetic_sources.set_tick(tick)
            spot = float(tick.underlying_price)
            if not self.validation_only_synthetic:
                # Preserve the legacy non-synthetic replay contract. The P5
                # DERIVED_SCENARIO path above must never infer other contracts'
                # quotes from this row's option premium.
                base_last = float(tick.last_price)
                current_expiry = str(tick.expiry).replace("-", "")[:8]
                identities = tuple(
                    identity
                    for identity in bootstrap.bundle.option_master.list_contract_identities()
                    if str(identity.expiry).replace("-", "")[:8] == current_expiry
                )
                if not identities:
                    raise ValueError("DERIVED_SCENARIO_OPTION_MASTER_EXPIRY_REQUIRED")
                grid_center = round(spot / 2.5) * 2.5
                requested_identities = list(identities)
                for offset in range(-10, 11):
                    strike = grid_center + offset * 2.5
                    for option_type in ("CALL", "PUT"):
                        identity = bootstrap.bundle.option_master.find_contract_identity(
                            current_expiry, option_type, Decimal(str(strike))
                        )
                        if identity is not None:
                            requested_identities.append(identity)
                seen_keys: set[tuple[str, float]] = set()
                for identity in requested_identities:
                    strike = float(identity.strike)
                    option_type = str(identity.option_type).upper()
                    key = (option_type, strike)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    intrinsic = max(0.0, spot - strike) if option_type == "CALL" else max(0.0, strike - spot)
                    mid = max(0.01, base_last * 0.35 + intrinsic * 0.10)
                    bid = max(0.01, mid - 0.02)
                    ask = mid + 0.02
                    symbol = identity.shrn_iscd or tick.symbol
                    bootstrap.bundle.market.register_replay_option_quote(
                        symbol=symbol, option_type=option_type,
                        strike=strike, expiry=current_expiry, bid=bid,
                        ask=ask, last=mid, timestamp=tick.timestamp,
                        contract_multiplier=float(identity.contract_multiplier or tick.contract_multiplier),
                    )
                    for instrument_key in tuple(dict.fromkeys(
                        value for value in (identity.stnd_iscd, identity.shrn_iscd, symbol) if value
                    )):
                        vssf_runtime.order_book.update_bid_ask(
                            bid, ask, instrument_id=instrument_key
                        )
            bootstrap.bundle.market.publish_replay_tick(tick)
            result = loop.last_result
            if result is None:
                raise RuntimeError("HIGH_SPEED_RUNTIME_RESULT_REQUIRED")
            for key in ("signals", "approved", "routed", "filled", "rejected"):
                totals[key] += getattr(result, key)
            totals["events"] += 1
            execution_ids.extend(result.execution_ids)
            for status in loop.last_strategy_status:
                previous = strategy_status.get(status.strategy_id, StrategyRuntimeStatus(status.strategy_id))
                strategy_status[status.strategy_id] = StrategyRuntimeStatus(
                    strategy_id=status.strategy_id,
                    reaction_signals=previous.reaction_signals + status.reaction_signals,
                    execution_signals=previous.execution_signals + status.execution_signals,
                    non_execution_signals=previous.non_execution_signals + status.non_execution_signals,
                    unavailable=previous.unavailable + status.unavailable,
                    runtime_failures=previous.runtime_failures + status.runtime_failures,
                    decision_rejected=previous.decision_rejected + status.decision_rejected,
                    risk_rejected=previous.risk_rejected + status.risk_rejected,
                    approved=previous.approved + status.approved,
                    routed=previous.routed + status.routed,
                    filled_quantity=previous.filled_quantity + status.filled_quantity,
                )
            mark_positions(spot)
            if self.validation_only_s8_risk_profile is not None or self.validation_only_s9_risk_profile is not None:
                replay_bridge.refresh_position_group_marks()
            self.trace.emit(
                "market_event", run_id=self.run_id, event_sequence=totals["events"] - 1,
                timestamp=tick.timestamp,
                payload={
                    "seq_id": getattr(tick, "seq_id", None),
                    "instrument_id": getattr(tick, "instrument_id", None),
                    "symbol": getattr(tick, "symbol", None),
                    "underlying_price": spot,
                    "signals": getattr(result, "signals", 0),
                    "approved": getattr(result, "approved", 0),
                    "routed": getattr(result, "routed", 0),
                    "filled": getattr(result, "filled", 0),
                    "rejected": getattr(result, "rejected", 0),
                    "execution_ids": list(getattr(result, "execution_ids", ())),
                    "cumulative_counts": dict(totals),
                    "cumulative_strategy_signal_counts": dict(sorted(strategy_signal_counts.items())),
                    "realized_pnl": float(vssf_runtime.account.realized_pnl),
                    "unrealized_pnl": float(vssf_runtime.account.unrealized_pnl),
                    "net_pnl": float(vssf_runtime.account.realized_pnl + vssf_runtime.account.unrealized_pnl),
                    "order_records_status": (observer.summary()["order_records_status"] if observer is not None else "NOT_CAPTURED_FAST_MODE"),
                    "fill_records_status": (observer.summary()["fill_records_status"] if observer is not None else "AGGREGATE_ONLY"),
                    "execution_observer": (observer.summary() if observer is not None else {"status": "DISABLED_FAST_MODE"}),
                },
            )

        try:
            report = HighSpeedReplayRunner(
                self.dataset, synthetic_adapter=synthetic_adapter, clock=self.clock
            ).run(
                start=start, end=end, speed=speed, on_event=publish, max_events=max_events,
            )
        finally:
            if observer is not None:
                observer.detach()
        final_report = HighSpeedVirtualReplayReport(
            dataset=report.dataset,
            run_id=self.run_id,
            events=totals["events"],
            signals=totals["signals"],
            approved=totals["approved"],
            routed=totals["routed"],
            filled=totals["filled"],
            rejected=totals["rejected"],
            execution_ids=tuple(execution_ids),
            elapsed_seconds=report.elapsed_seconds,
            events_per_second=report.events_per_second,
            exhausted=report.exhausted,
            pnl_status="VSSF_ACCOUNT_PNL_CONNECTED",
            multi_leg_decisions=multi_leg_decisions,
            strategy_signal_counts=tuple(sorted(strategy_signal_counts.items())),
            strategy_status=tuple(sorted(strategy_status.values(), key=lambda item: item.strategy_id)),
            realized_pnl=float(vssf_runtime.account.realized_pnl),
            unrealized_pnl=float(vssf_runtime.account.unrealized_pnl),
            net_pnl=float(vssf_runtime.account.realized_pnl + vssf_runtime.account.unrealized_pnl),
            trace_status=self.trace.status,
            execution_observer_summary=(observer.summary() if observer is not None else {"status": "DISABLED_FAST_MODE"}),
        )
        self.trace.emit(
            "replay_finished", run_id=self.run_id,
            payload={
                "events": final_report.events, "signals": final_report.signals,
                "approved": final_report.approved, "routed": final_report.routed,
                "filled": final_report.filled, "rejected": final_report.rejected,
                "execution_ids": list(final_report.execution_ids),
                "realized_pnl": final_report.realized_pnl,
                "unrealized_pnl": final_report.unrealized_pnl, "net_pnl": final_report.net_pnl,
                "exhausted": final_report.exhausted,
                "execution_observer": (observer.summary() if observer is not None else {"status": "DISABLED_FAST_MODE"}),
            },
        )
        final_report = replace(
            final_report,
            trace_status=self.trace.status,
            execution_observer_summary=(observer.summary() if observer is not None else {"status": "DISABLED_FAST_MODE"}),
        )
        if self.s9_validation_runtime_adapter is not None:
            self.s9_runtime_snapshot = {
                "open_lots": tuple(replay_bridge.position_lot_store.open_lots()),
                "position_groups": replay_bridge.position_groups.all(),
                "position_group_snapshots": {
                    key: replay_bridge.position_groups.snapshot(key)
                    for key in replay_bridge.position_groups.all()
                    if replay_bridge.position_groups.snapshot(key) is not None
                },
                "execution_reports": tuple(vssf_runtime.execution_engine.reports),
                "fee_records": tuple(replay_bridge.fee_ledger.snapshot(run_id=self.run_id)),
                "risk_audit_records": tuple(self.s9_validation_runtime_adapter.risk_audit_records),
                "strategy_state": getattr(getattr(self.s9_strategy, "state", None), "state", None),
                "strategy_exit_reason": getattr(getattr(self.s9_strategy, "state", None), "exit_reason", None),
                "realized_pnl": vssf_runtime.account.realized_pnl,
                "unrealized_pnl": vssf_runtime.account.unrealized_pnl,
                "net_pnl": vssf_runtime.account.realized_pnl + vssf_runtime.account.unrealized_pnl,
                "account_positions": {key: dict(value) for key, value in vssf_runtime.account.positions.items()},
                "account_balance": vssf_runtime.account.balance,
                "account_free_margin": vssf_runtime.account.free_margin,
                "account_used_margin": vssf_runtime.account.used_margin,
                "ledger_transactions": list(vssf_runtime.account.ledger_engine.transactions),
                "execution_sequence": int(vssf_runtime.execution_engine._seq),
                "restart_restore_status": self.s9_restart_restore_status,
            }
        return final_report

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/synthetic_market_data/1y_5min_v1")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--speed", type=float, default=float("inf"))
    parser.add_argument("--max-events", type=int)
    parser.add_argument("--log-mode", choices=[mode.value for mode in ReplayLogMode], default=ReplayLogMode.FAST.value)
    parser.add_argument("--trace-output", help="New JSONL path required for --log-mode detailed; existing files are never overwritten.")
    parser.add_argument(
        "--validation-only-synthetic", action="store_true",
        help="Enable the fail-closed P5 DERIVED_SCENARIO identity adapter; never for REAL_VTS/Live.",
    )
    parser.add_argument("--validation-only-synthetic-manifest", help="Explicit external manifest for a validation-only synthetic dataset.")
    parser.add_argument("--validation-only-s8-risk-profile", help="Manifest-bound validation-only S8 risk profile; requires Strategy 8 only.")
    parser.add_argument("--validation-only-s9-contract-profile", help="Synthetic S9 contract profile; validation-only and S9-only.")
    parser.add_argument("--validation-only-s9-risk-profile", help="Manifest-bound synthetic S9 Virtual risk profile; validation-only and S9-only.")
    parser.add_argument("--validation-only-track6-execution-mode", action="store_true", help="Enable isolated Strategy 6 synthetic entry lifecycle validation; never Live/KIS.")
    args = parser.parse_args()
    result = HighSpeedVirtualRuntimeReplayRunner(
        args.dataset, validation_only_synthetic=args.validation_only_synthetic,
        validation_only_synthetic_manifest=args.validation_only_synthetic_manifest,
        validation_only_s8_risk_profile=args.validation_only_s8_risk_profile,
        validation_only_s9_contract_profile=args.validation_only_s9_contract_profile,
        validation_only_s9_risk_profile=args.validation_only_s9_risk_profile,
        validation_only_track6_execution_mode=args.validation_only_track6_execution_mode,
        strategy_keys=(("track6_daily_tail_insurance", "1.0"),) if args.validation_only_track6_execution_mode else None,
        log_mode=args.log_mode, trace_output=args.trace_output,
    ).run(
        start=args.start, end=args.end, speed=args.speed, max_events=args.max_events,
    )
    print(f"DATASET={result.dataset}")
    print(f"LOG_MODE={args.log_mode}")
    print(f"TRACE_STATUS={result.trace_status}")
    print(f"EXECUTION_OBSERVER={result.execution_observer_summary}")
    if args.log_mode == ReplayLogMode.DETAILED.value:
        print(f"TRACE_OUTPUT={args.trace_output}")
    print(f"RUN_ID={result.run_id}")
    print(f"EVENTS={result.events}")
    print(f"SIGNALS={result.signals}")
    print(f"APPROVED={result.approved}")
    print(f"ROUTED={result.routed}")
    print(f"FILLED={result.filled}")
    print(f"REJECTED={result.rejected}")
    print(f"EXHAUSTED={result.exhausted}")
    print(f"EVENTS_PER_SECOND={result.events_per_second:.2f}")
    print(f"PNL_STATUS={result.pnl_status}")
    print(f"MULTI_LEG_DECISIONS={result.multi_leg_decisions}")
    print(f"STRATEGY_SIGNAL_COUNTS={dict(result.strategy_signal_counts)}")
    for status in result.strategy_status:
        print(f"STRATEGY_STATUS={status}")
    print(f"REALIZED_PNL={result.realized_pnl:.2f}")
    print(f"UNREALIZED_PNL={result.unrealized_pnl:.2f}")
    print(f"NET_PNL={result.net_pnl:.2f}")


if __name__ == "__main__":
    main()