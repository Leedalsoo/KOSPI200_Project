from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from contracts.analytics import AnalyticsMetric, AnalyticsSnapshot, AnalyticsStatus
from core.domain.market_models import MarketState
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.orchestrator import StrategyOrchestrator
from core.strategy.standard_registry import build_standard_strategy_registry, STANDARD_STRATEGY_KEYS
from core.strategy.track1_tail_defense import Track1Input
from core.strategy.track3_statistical_arbitrage import Track3MarketInput
from core.strategy.track4_gamma_scalping import Track4MarketInput
from core.strategy.track6_daily_tail_insurance import Track6ExecutionInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7ExecutionInput
from environments.virtual.market.scenario_engine import ScenarioEngine

SCENARIOS = (
    "CALM", "HIGH_VOLATILITY", "UP_TREND", "DOWN_TREND", "SIDEWAYS",
    "SHARP_UP", "SHARP_DOWN", "VOL_EXPANSION", "VOL_CONTRACTION",
    "SHOCK_UP", "SHOCK_DOWN",
)

def _value(key: str, scenario: str, price: Decimal, active_vol: Decimal, base_vol: Decimal):
    if key == "price.last":
        return price
    if key == "volatility.active":
        return active_vol
    if key == "volatility.base":
        return base_vol
    if key == "volatility.bbw":
        return Decimal("0.03") if active_vol > base_vol else Decimal("0.01")
    if key == "volume.z_score":
        return Decimal("4.0") if scenario in {"HIGH_VOLATILITY","VOL_EXPANSION","SHOCK_UP","SHOCK_DOWN"} else Decimal("0")
    if key == "microstructure.obi":
        return Decimal("0.7")
    if key == "futures.basis":
        return Decimal("1.0")
    if key == "volume_profile.poc":
        return Decimal("1100")
    if key in {"options.call_iv", "options.atm_iv"}:
        return Decimal("35") if scenario in {"VOL_EXPANSION","SHOCK_UP","SHOCK_DOWN"} else Decimal("20")
    if key == "options.put_iv":
        return Decimal("25") if scenario in {"SHARP_UP","SHOCK_UP"} else Decimal("40") if scenario in {"SHARP_DOWN","SHOCK_DOWN"} else Decimal("22")
    if key == "spread.z_score":
        return Decimal("3.0")
    if key == "spread.std":
        return Decimal("1.0")
    if key == "volatility.ratio":
        return active_vol / base_vol
    if key == "microstructure.spread":
        return Decimal("0.5")
    if key == "price.change_rate":
        return Decimal("0.03") if scenario in {"SHARP_UP","SHARP_DOWN","SHOCK_UP","SHOCK_DOWN"} else Decimal("0.01")
    if key == "cost.fees":
        return Decimal("0")
    if key == "portfolio.options_pnl":
        return Decimal("0")
    if key == "options.skew":
        return Decimal("5") if scenario in {"VOL_EXPANSION","SHOCK_UP","SHOCK_DOWN"} else Decimal("0")
    if key.startswith("trend.ma_"):
        return Decimal("1102")
    if key == "levels.support":
        return Decimal("1080")
    if key == "levels.resistance":
        return Decimal("1120")
    if key == "calendar.is_new_week_start":
        return True
    if key == "calendar.is_expiry_day":
        return False
    if key == "calendar.is_week_end":
        return False
    if key == "execution.order_timeout":
        return False
    if key == "price.open":
        return price
    if key == "price.previous_close":
        return Decimal("1100")
    if key == "price.gap":
        return abs(price - Decimal("1100"))
    if key == "volatility.expected_move":
        return Decimal("15")
    if key == "stats.z_score":
        return Decimal("2.0") if scenario in {"SHARP_UP","SHARP_DOWN","SHOCK_UP","SHOCK_DOWN"} else Decimal("0")
    if key == "regime.market":
        return "HIGH_VOL" if scenario in {"HIGH_VOLATILITY","VOL_EXPANSION","SHOCK_UP","SHOCK_DOWN"} else "NORMAL"
    if key == "options.iv_skew":
        return Decimal("5") if scenario in {"VOL_EXPANSION","SHOCK_UP","SHOCK_DOWN"} else Decimal("1")
    if key == "options.iv_spike":
        return Decimal("5") if scenario in {"SHOCK_UP","SHOCK_DOWN"} else Decimal("0")
    if key == "options.iv_crush":
        return Decimal("0")
    if key == "options.dte":
        return Decimal("30")
    if key in {"options.call_strike", "options.atm_call_strike"}:
        return price + Decimal("10")
    if key in {"options.put_strike", "options.atm_put_strike"}:
        return price - Decimal("10")
    if key in {"options.call_contract_multiplier", "options.put_contract_multiplier", "options.contract_multiplier"}:
        return Decimal("250000")
    if key == "options.moneyness":
        return {"call_distance": Decimal("5"), "put_distance": Decimal("5")}
    if key == "market.current_regime":
        return "HIGH_VOL" if scenario in {"HIGH_VOLATILITY","VOL_EXPANSION","SHOCK_UP","SHOCK_DOWN"} else "NORMAL"
    if key == "market.stable":
        return scenario not in {"SHOCK_UP","SHOCK_DOWN"}
    if key.startswith("portfolio.") and key.endswith("active_sell_qty"):
        return 4
    if key == "portfolio.active_sell_qty":
        return 4
    if key == "portfolio.insurance_qty":
        return 0
    if key == "portfolio.target_qty":
        return 2
    if key == "portfolio.existing_qty":
        return 0
    if key == "portfolio.equity":
        return Decimal("1000000")
    if key in {"portfolio.current_pnl", "portfolio.net_pnl"}:
        return Decimal("0")
    if key == "portfolio.total_fees":
        return Decimal("0")
    if key == "portfolio.margin_ratio":
        return Decimal("0.2")
    if key == "portfolio.event_budget":
        return Decimal("1000000")
    if key == "portfolio.estimated_event_cost":
        return Decimal("100")
    if key == "portfolio.premium_spent":
        return Decimal("100000")
    if key == "events.upcoming":
        return scenario in {"SHOCK_UP","SHOCK_DOWN"}
    if key == "risk.guard_active":
        return False
    if key in {"portfolio.budget", "budget"}:
        return Decimal("1000000")
    if key == "market.gap_pct":
        return Decimal("0.025") if scenario in {"SHARP_UP","SHOCK_UP"} else Decimal("-0.025") if scenario in {"SHARP_DOWN","SHOCK_DOWN"} else Decimal("0")
    if key == "market.expected_move":
        return Decimal("15")
    if key == "market.z_score":
        return Decimal("2.5")
    if key == "market.open":
        return price
    return Decimal("0")

def make_context(strategy_id: str, scenario: str, seq: int) -> StrategyContext:
    engine = ScenarioEngine(seed=100 + seq)
    engine.set_scenario(scenario)
    adj = engine.next_adjustment(seq, 1)
    base = Decimal("1100")
    price = base + Decimal(str(adj.drift * 10 + adj.shock_delta))
    active_vol = Decimal(str(max(0.1, adj.volatility_multiplier)))
    base_vol = Decimal("1")
    now = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)

    registry = build_standard_strategy_registry()
    strategy = registry.get(strategy_id, dict(STANDARD_STRATEGY_KEYS)[strategy_id])
    requirements = strategy.feature_requirements() if hasattr(strategy, "feature_requirements") else ()
    metrics = {}
    for req in requirements:
        value = _value(req.metric_key, scenario, price, active_vol, base_vol)
        metrics[req.metric_key] = AnalyticsMetric(
            metric_key=req.metric_key, value=value, status=AnalyticsStatus.AVAILABLE,
            unit="synthetic", as_of=now, calculation_version="scenario-matrix-1",
            provenance=("SCENARIO_SYNTHETIC", scenario),
        )
    analytics = AnalyticsSnapshot(
        run_id=f"SCENARIO-{scenario}-{seq}-{strategy_id}",
        instrument_identity=None, as_of=now, timeframe="tick", window=1,
        analytics_version="scenario-matrix-1", metrics=metrics,
    )
    tick = SimpleNamespace(instrument_id="KOSPI200", observed_at=now, price=price)
    market = MarketState(as_of=now, ticks={"KOSPI200": tick}, quality={})
    common = CommonStrategyInput(
        as_of=now, current_price=price, active_vol=active_vol, base_vol=base_vol,
        budget=Decimal("1000000"), current_pnl=Decimal("0"), total_fees=Decimal("0"),
        time_str="10:00:00", date_str="2026-09-28",
    )
    payload = None
    if strategy_id == "TRACK1_TAIL_DEFENSE":
        payload = Track1Input(momentum_confirmed=True, days_to_expiry=20, current_time=now,
                              active_vol=float(active_vol), base_vol=float(base_vol),
                              short_option_net_delta=Decimal("0.5"))
    elif strategy_id == "Strategy_3_StatArb":
        payload = Track3MarketInput(spread_history=(2.5, 2.7, 2.9, 3.0, 3.2), active_vol=float(active_vol),
                                    base_vol=float(base_vol), price_change_rate=0.02, bid_ask_spread=0.5,
                                    gap_pct=float(_value("market.gap_pct", scenario, price, active_vol, base_vol)),
                                    is_gap=scenario in {"SHARP_UP","SHARP_DOWN","SHOCK_UP","SHOCK_DOWN"},
                                    time_str="10:00:00", market_stable=True, spread_normalizing=False,
                                    allow_size_up=True, current_pnl=0, total_fees=0, premium_spent=100000,
                                    current_price=float(price), contract_multiplier=250000, regime="HIGH_VOL" if active_vol > 2 else "NORMAL",
                                    date_str="2026-09-28")
    elif strategy_id == "track4_gamma_scalping":
        payload = Track4MarketInput(now, price, active_vol, base_vol, "10:00:00",
                                    Decimal("0.5"), Decimal("0.1"), Decimal("0"),
                                    Decimal("1000000"), (price-Decimal("2"), price, price+Decimal("2")),
                                    Decimal("100000"), Decimal("0"), Decimal("0"), Decimal("0"))
    elif strategy_id == "track6_daily_tail_insurance":
        payload = Track6ExecutionInput(strategy_id, "2026-09-28", "10:00:00",
                                       listed_put_strike=price-Decimal("10"), listed_call_strike=price+Decimal("10"),
                                       contract_multiplier=Decimal("250000"))
    elif strategy_id == "track7_volatility_skew_weekly_insurance":
        payload = Track7ExecutionInput(strategy_id, "202610", price-Decimal("10"), price+Decimal("10"), Decimal("250000"))
    return StrategyContext(market_state=market, strategy_id=strategy_id,
                           input=StrategyInput(common=common, payload=payload), analytics=analytics)

def test_11_scenarios_x_9_strategies_matrix_executes():
    registry = build_standard_strategy_registry()
    orchestrator = StrategyOrchestrator(registry, STANDARD_STRATEGY_KEYS)
    from application.composition.runtime_strategy_result_collection_adapter import RuntimeStrategyResultCollectionAdapter
    from application.composition.runtime_strategy_to_decision_adapter import RuntimeStrategyToDecisionAdapter
    from contracts.types import OptionInstrumentIdentity
    from core.decision.decision_arbiter import DecisionArbiter

    report = []
    for scenario_index, scenario in enumerate(SCENARIOS, start=1):
        contexts = {
            strategy_id: make_context(strategy_id, scenario, scenario_index)
            for strategy_id, _ in STANDARD_STRATEGY_KEYS
        }
        result = orchestrator.run(contexts)
        executable_result = type(
            "ExecutableResult",
            (),
            {"signals": tuple(
                signal for signal in result.signals
                if getattr(signal, "execution_proposal", None) is not None
            )},
        )()
        evaluations = RuntimeStrategyResultCollectionAdapter().collect(
            tick_sequence=scenario_index,
            context=contexts,
            result=executable_result,
        )
        def identity_provider(evaluation, market_tick=None):
            proposal = evaluation.result.execution_proposal
            if proposal is None or str(proposal.asset_type) != "OPTION":
                return None
            return OptionInstrumentIdentity(
                instrument_id=f"SYN-{scenario_index}-{evaluation.local_sequence}",
                symbol="KOSPI200",
                expiry="202610",
                option_type=proposal.option_type,
                strike=proposal.strike,
                contract_multiplier=Decimal("250000"),
                identity_source="SCENARIO_SYNTHETIC_OPTION_MASTER",
            )
        decision = RuntimeStrategyToDecisionAdapter(DecisionArbiter()).arbitrate(
            evaluations,
            price=1100.0,
            timestamp=f"2026-09-28T10:00:{scenario_index:02d}+00:00",
            account={"available_cash": 100000000},
            instrument_identity_provider=identity_provider,
        )
        report.append({
            "scenario": scenario,
            "signals": len(result.signals),
            "failures": len(result.failures),
            "decision_candidates": len(decision.canonical_signals),
            "decision_approved": len(decision.arbitration.approved_signals),
            "strategies_with_signals": sorted({s.strategy_id for s in result.signals}),
        })
        orchestrator.reset()

    assert len(report) == 11
    assert all(row["failures"] == 0 for row in report), report
    assert any(row["signals"] > 0 for row in report), report
    print("\nSCENARIO_MATRIX_REPORT")
    for row in report:
        print(row)
