"""High-Speed Replay -> real Virtual Runtime -> Strategy -> Decision -> Risk -> Virtual Execution."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from decimal import Decimal

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from environments.high_speed.replay_runner import HighSpeedReplayRunner
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources, build_synthetic_option_master
from contracts.strategy_runtime_status import StrategyRuntimeStatus


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


class HighSpeedVirtualRuntimeReplayRunner:
    """Feed high-speed replay events through the existing Virtual Runtime boundary."""

    def __init__(self, dataset: str | Path, *, run_id: str | None = None, strategy_keys=None):
        self.dataset = Path(dataset)
        self.run_id = run_id or f"HS-{uuid4()}"
        self.strategy_keys = tuple(strategy_keys) if strategy_keys else None

    def run(self, *, start: str | None = None, end: str | None = None,
            speed: float = float("inf"), max_events: int | None = None) -> HighSpeedVirtualReplayReport:
        synthetic_sources = SyntheticRuntimeSources()
        option_master = build_synthetic_option_master(self.dataset)
        bootstrap = create_virtual_runtime_bootstrap(option_master=option_master)
        loop = attach_standard_automated_loop(
            bootstrap,
            strategy_keys=self.strategy_keys,
            run_id=self.run_id,
            synthetic_runtime_sources=synthetic_sources,
            track4_greeks_provider=synthetic_sources,
        )
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

        def mark_positions() -> None:
            account_source = vssf_runtime.account
            for symbol in tuple(account_source.positions):
                identity = option_master.get_contract_identity(symbol)
                if identity is None or identity.option_type is None or identity.strike is None:
                    continue
                expiry = str(identity.expiry).replace("-", "")[:8]
                key = (str(identity.option_type).upper(), float(identity.strike), expiry)
                quote = bootstrap.bundle.market.option_quotes.get(key)
                if quote is not None:
                    account_source.update_tick_price(quote["last"], instrument_id=symbol)

        def publish(tick) -> None:
            spot = float(tick.underlying_price)
            base_last = float(tick.last_price)
            # DERIVED_SCENARIO quote materialization follows the authoritative synthetic
            # Option Master strike/expiry set so Strategy-selected legs always have a
            # corresponding scenario quote. This does not alter REAL_VTS evidence.
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
                bootstrap.bundle.market.register_replay_option_quote(
                    symbol=identity.shrn_iscd or tick.symbol, option_type=option_type,
                    strike=strike, expiry=current_expiry, bid=max(0.01, mid - 0.02),
                    ask=mid + 0.02, last=mid, timestamp=tick.timestamp,
                    contract_multiplier=float(identity.contract_multiplier or tick.contract_multiplier),
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
            mark_positions()

        report = HighSpeedReplayRunner(self.dataset).run(
            start=start, end=end, speed=speed, on_event=publish, max_events=max_events,
        )
        return HighSpeedVirtualReplayReport(
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
        )
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/synthetic_market_data/1y_5min_v1")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--speed", type=float, default=float("inf"))
    parser.add_argument("--max-events", type=int)
    args = parser.parse_args()
    result = HighSpeedVirtualRuntimeReplayRunner(args.dataset).run(
        start=args.start, end=args.end, speed=args.speed, max_events=args.max_events,
    )
    print(f"DATASET={result.dataset}")
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
