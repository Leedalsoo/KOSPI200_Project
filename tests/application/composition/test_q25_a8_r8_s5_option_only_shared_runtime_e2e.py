from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pytest

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.automated_virtual_runtime_factory import attach_standard_automated_loop
from application.strategy_hub.hub import StrategyHub
from contracts.market_data_freshness import FreshnessStatus, FreshnessVerdict
from contracts.types import ExecutionLeg, MultiLegExecutionPlan
from core.option.option_master import InMemoryOptionContractMaster, KisOptionContractIdentity
from core.strategy.contracts import Signal, SignalKind
from core.strategy.registry import StrategyRegistry
from core.strategy.standard_registry import STANDARD_STRATEGY_KEYS
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track5_gap_divergence import Track5GapDivergence
from environments.high_speed.synthetic_runtime_sources import SyntheticRuntimeSources
from environments.high_speed.virtual_runtime_replay import _publish_contract_scoped_replay_quote
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick


ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "data/derived_scenario/q25_a8_r8_s5_atm_market_calibrated_v1_20261117"
PROFILE_PATH = ROOT / "config/validation_only/q25_s5/option_only_runtime_profile.v1.json"
S5_ID = "track5_gap_divergence"
SELECTED_TIMESTAMPS = (
    "2026-10-13T10:26:29+09:00",
    "2026-10-13T10:26:38+09:00",
    "2026-10-13T10:26:49+09:00",
    "2026-10-13T10:27:11+09:00",
)


def _load_scenario():
    if not (DATASET / "manifest.json").is_file():
        pytest.skip("No.1534: source sidecar is not materialized in this checkout; reconcile the original workspace before classifying missing data")
    profile_bytes = PROFILE_PATH.read_bytes()
    profile_hash = PROFILE_PATH.with_suffix(PROFILE_PATH.suffix + ".sha256").read_text(encoding="ascii").strip()
    assert sha256(profile_bytes).hexdigest() == profile_hash
    profile = json.loads(profile_bytes.decode("utf-8"))
    manifest_bytes = (DATASET / "manifest.json").read_bytes()
    quote_bytes = (DATASET / "atm_call_put_quotes.jsonl").read_bytes()
    candidate_bytes = (DATASET / "candidate_inputs.json").read_bytes()
    assert sha256(manifest_bytes).hexdigest() == profile["source_sidecar"]["manifest_sha256"]
    assert sha256(quote_bytes).hexdigest() == profile["source_sidecar"]["quote_file_sha256"]
    assert sha256(candidate_bytes).hexdigest() == profile["source_sidecar"]["candidate_file_sha256"]

    manifest = json.loads(manifest_bytes)
    assert manifest["status"] == "SYNTHETIC_VALIDATION_ONLY_NOT_MARKET_EVIDENCE"
    assert manifest["quote_rows"] == profile["source_sidecar"]["quote_rows"]
    assert manifest["complete_call_put_pairs"] == profile["source_sidecar"]["complete_call_put_pairs"]
    assert manifest["constraints"]["execution_enabled"] is False
    assert manifest["constraints"]["order_submission_enabled"] is False
    assert manifest["constraints"]["multiplier"] is None

    quotes = [json.loads(line) for line in quote_bytes.decode("utf-8").splitlines() if line.strip()]
    candidates = json.loads(candidate_bytes)
    candidate_by_timestamp = {item["timestamp"]: item for item in candidates}
    quote_by_key = {}
    for row in quotes:
        key = (row["timestamp"], row["expiry"], str(row["strike"]), row["option_type"].upper())
        quote_by_key[key] = row

    selected = []
    for timestamp in SELECTED_TIMESTAMPS:
        candidate = candidate_by_timestamp[timestamp]
        assert candidate["expiry"] == profile["scenario"]["expiry"]
        assert candidate["atm_strike"] == profile["scenario"]["strike"]
        pair = {}
        for option_type in ("CALL", "PUT"):
            key = (timestamp, profile["scenario"]["expiry"], profile["scenario"]["strike"], option_type)
            row = quote_by_key[key]
            assert row["validation_only"] is True
            assert row["provenance"] == "DERIVED_SCENARIO"
            assert row["source"] == "SYNTHETIC:DERIVED_SCENARIO"
            assert row["future_observation_count"] == 0
            assert row["contract_multiplier"] is None
            assert row["identity_authority"] == "SYNTHETIC_ONLY_NOT_KIS_MASTER"
            pair[option_type] = row
        selected.append((candidate, pair))
    return profile, manifest, selected


def _stable_synthetic_id(profile: dict, expiry: str, option_type: str, strike: str) -> str:
    material = "|".join((profile["profile_id"], expiry, option_type.upper(), str(strike)))
    digest = sha256(material.encode("utf-8")).hexdigest()[:32]
    return profile["scenario"]["synthetic_identity_namespace"] + digest


def _build_ticks_and_master(profile: dict, selected):
    unit_scale = Decimal(profile["scenario"]["runtime_unit_scale"])
    master = InMemoryOptionContractMaster(auto_load_kis_source=False)
    quote_sets = {}
    seq = 0
    for candidate, pair in selected:
        timestamp = candidate["timestamp"]
        quote_set = []
        for option_type in ("CALL", "PUT"):
            row = pair[option_type]
            synthetic_id = _stable_synthetic_id(
                profile, row["expiry"], option_type, row["strike"]
            )
            identity = KisOptionContractIdentity(
                shrn_iscd=synthetic_id,
                stnd_iscd=None,
                expiry=row["expiry"],
                option_type=option_type,
                strike=Decimal(row["strike"]),
                info_type="SYNTHETIC",
                contract_multiplier=unit_scale,
                instrument_family="SYNTHETIC_VALIDATION_ONLY",
                product_series="TEST_ONLY",
            )
            existing = master.get_contract_identity(synthetic_id)
            if existing is None:
                master.register_contract(synthetic_id, row["expiry"])
                master.register_contract_identity(identity)
            else:
                assert existing == identity

            seq += 1
            observed_at = datetime.fromisoformat(timestamp)
            tick = ReferenceCanonicalMarketTick(
                timestamp=timestamp,
                underlying_price=float(candidate["underlying_price"]),
                underlying_symbol="2001",
                underlying_observed_hour=observed_at.strftime("%H%M%S"),
                underlying_source="KIS:H0UPCNT0",
                strike_price=float(row["strike"]),
                option_type=option_type,
                contract_multiplier=float(unit_scale),
                bid_price=float(row["bid"]),
                ask_price=float(row["ask"]),
                last_price=(float(row["bid"]) + float(row["ask"])) / 2.0,
                volume=0,
                bid_quantity=int(row["bid_quantity"]),
                ask_quantity=int(row["ask_quantity"]),
                seq_id=seq,
                expiry=row["expiry"],
                symbol=synthetic_id,
                option_observed_hour=observed_at.strftime("%H%M%S"),
                option_source="SYNTHETIC:DERIVED_SCENARIO",
                underlying_sequence=seq,
                instrument_id=synthetic_id,
                synthetic_contract_id=synthetic_id,
                source_instrument_code=str(row["source_contract_codes_crosswalk_only"][0]),
                instrument_identity_status="BLOCKED_IDENTITY_OWNER_UNRESOLVED",
                contract_class="monthly",
                contract_month=row["expiry"][:6],
                theoretical_mid_price=float(row["model_fair_value"]),
                implied_volatility=float(row["volatility"]),
                validation_only=True,
                scenario_id=profile["profile_id"],
                scenario_group_id=str(row["candidate_id"]),
                scenario_regime="NORMAL",
                dte_trading_days=int(profile["scenario"]["runtime_dte_proxy"]["value"]),
            )
            quote_set.append(tick)
        quote_sets[timestamp] = tuple(quote_set)
    assert master.total_contracts == 2  # two validation-only symbol-to-expiry entries
    assert len(master.list_contract_identities()) == 2
    return master, quote_sets


class _S5ValidationLifecycleDriver:
    """Test-only signal driver; it is not the production Track5 strategy."""

    strategy_id = S5_ID
    version = "2.0"

    def __init__(self, phases):
        self._phases = tuple(phases)
        self._phase = 0

    def feature_requirements(self):
        return ()

    def initialize(self, context):
        self._phase = 0

    def on_market_state(self, context):
        return None

    def reset(self):
        self._phase = 0

    def evaluate(self, context):
        if context.strategy_id != self.strategy_id or self._phase >= len(self._phases):
            return ()
        option_type, side, tag, strike, requested_price = self._phases[self._phase]
        self._phase += 1
        proposal = StrategyExecutionProposal(
            proposed_quantity=1,
            asset_type="OPTION",
            requested_price=Decimal(str(requested_price)),
            side=side,
            track_id=self.strategy_id,
            tag_id=tag,
            option_type=option_type,
            strike=Decimal(str(strike)),
        )
        return (
            Signal(
                strategy_id=self.strategy_id,
                direction=side,
                confidence=1.0,
                reason=f"S5_VALIDATION_ONLY_{tag}",
                kind=SignalKind.EXECUTION,
                execution_proposal=proposal,
            ),
        )


def test_s5_option_only_entry_hedge_and_independent_closes_share_virtual_runtime():
    profile, _manifest, selected = _load_scenario()
    master, quote_sets = _build_ticks_and_master(profile, selected)
    assert Track5GapDivergence.CURRENT_EXECUTION_POLICY_APPROVED is False

    first_candidate, first_pair = selected[0]
    second_candidate, second_pair = selected[1]
    third_candidate, third_pair = selected[2]
    fourth_candidate, fourth_pair = selected[3]

    call_id = _stable_synthetic_id(profile, profile["scenario"]["expiry"], "CALL", profile["scenario"]["strike"])
    put_id = _stable_synthetic_id(profile, profile["scenario"]["expiry"], "PUT", profile["scenario"]["strike"])
    phases = (
        ("CALL", "BUY", "S5_PRIMARY_ENTRY", profile["scenario"]["strike"], first_pair["CALL"]["ask"]),
        ("PUT", "BUY", "S5_HEDGE_ENTRY", profile["scenario"]["strike"], second_pair["PUT"]["ask"]),
        ("PUT", "SELL", "S5_HEDGE_EXIT", profile["scenario"]["strike"], third_pair["PUT"]["bid"]),
        ("CALL", "SELL", "S5_PRIMARY_EXIT", profile["scenario"]["strike"], fourth_pair["CALL"]["bid"]),
    )
    event_ticks = (
        quote_sets[first_candidate["timestamp"]][0],
        quote_sets[second_candidate["timestamp"]][1],
        quote_sets[third_candidate["timestamp"]][1],
        quote_sets[fourth_candidate["timestamp"]][0],
    )

    sources = SyntheticRuntimeSources()
    bootstrap = create_virtual_runtime_bootstrap(
        option_master=master,
        initial_capital=Decimal("1000000"),
        risk_guard_status_source=sources,
    )
    original_loop = bootstrap.automated_loop
    if original_loop is not None:
        bootstrap.bundle.market.unsubscribe(original_loop.on_tick)

    run_id = "Q25-A8-R8-S5-OPTION-ONLY-SHARED-RUNTIME"
    strategy_key = next(key for key in STANDARD_STRATEGY_KEYS if key[0] == S5_ID)
    loop = attach_standard_automated_loop(
        bootstrap,
        strategy_keys=(strategy_key,),
        run_id=run_id,
        synthetic_runtime_sources=sources,
        track4_greeks_provider=sources,
        risk_guard_status_source=sources,
    )
    registry = StrategyRegistry()
    registry.register(_S5ValidationLifecycleDriver(phases))
    loop.strategy_hub = StrategyHub(registry, (strategy_key,))

    def plan_resolver(evaluation, canonical):
        proposal = evaluation.result.execution_proposal
        if proposal is None:
            raise AssertionError("S5_VALIDATION_EXECUTION_PROPOSAL_REQUIRED")
        tag = str(proposal.tag_id).upper()
        if str(proposal.side).upper() == "BUY":
            if tag == "S5_PRIMARY_ENTRY":
                leg_id = "S5_PRIMARY_ENTRY"
                group_suffix = "PRIMARY"
            elif tag == "S5_HEDGE_ENTRY":
                leg_id = "S5_HEDGE_ENTRY"
                group_suffix = "HEDGE"
            else:
                raise AssertionError(f"Unexpected S5 BUY tag: {tag}")
            return MultiLegExecutionPlan(
                group_id=f"{run_id}-{group_suffix}",
                strategy_id=S5_ID,
                purpose=f"S5_VALIDATION_ONLY_{group_suffix}_ENTRY",
                legs=(
                    ExecutionLeg(
                        leg_id,
                        "BUY",
                        1,
                        str(proposal.option_type).upper(),
                        Decimal(str(proposal.strike)),
                        requested_price=Decimal(str(proposal.requested_price)),
                    ),
                ),
            )
        if tag == "S5_HEDGE_EXIT":
            return loop.multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id=S5_ID,
                purpose="S5_VALIDATION_ONLY_HEDGE_CLOSE",
                asset_type="OPTION",
                option_type="PUT",
                leg_id_prefix="S5_HEDGE_ENTRY",
            )
        if tag == "S5_PRIMARY_EXIT":
            return loop.multi_leg_bridge.build_close_plan_from_open_lots(
                strategy_id=S5_ID,
                purpose="S5_VALIDATION_ONLY_PRIMARY_CLOSE",
                asset_type="OPTION",
                option_type="CALL",
                leg_id_prefix="S5_PRIMARY_ENTRY",
            )
        raise AssertionError(f"Unexpected S5 SELL tag: {tag}")

    loop.multi_leg_plan_resolver = plan_resolver
    current_tick = {"value": event_ticks[0]}
    original_context_builder = loop.context_builder

    def validation_context_builder(tick, state):
        contexts = original_context_builder(tick, state)
        identity = master.get_contract_identity(tick.instrument_id)
        assert identity is not None
        observed_at = datetime.fromisoformat(tick.timestamp)
        verdict = FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="S5_DERIVED_SCENARIO_TEST_FIXTURE",
            policy_version="S5-VALIDATION-FIXTURE-v1",
            source="SYNTHETIC:DERIVED_SCENARIO",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=identity.shrn_iscd,
            symbol=identity.shrn_iscd,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{tick.timestamp}|{identity.shrn_iscd}|{profile['profile_id']}".encode()
            ).hexdigest(),
        )
        contexts[S5_ID] = replace(
            contexts[S5_ID], input=None, freshness_verdict=verdict
        )
        return contexts

    loop.context_builder = validation_context_builder

    def freshness_verdict(plan, leg, leg_identity, command):
        tick = current_tick["value"]
        observed_at = datetime.fromisoformat(tick.timestamp)
        return FreshnessVerdict(
            status=FreshnessStatus.FRESH,
            reason="S5_DERIVED_SCENARIO_TEST_FIXTURE",
            policy_version="S5-VALIDATION-FIXTURE-v1",
            source="SYNTHETIC:DERIVED_SCENARIO",
            tr_id="SYNTHETIC-REPLAY-TEST",
            environment="VIRTUAL_VALIDATION_ONLY",
            instrument_id=command.instrument_id,
            symbol=command.broker_symbol,
            source_instant=observed_at,
            received_at=observed_at,
            evidence_sha256=sha256(
                f"{tick.timestamp}|{command.instrument_id}|{profile['profile_id']}".encode()
            ).hexdigest(),
        )

    loop.multi_leg_bridge.freshness_verdict_provider = freshness_verdict

    expected_open_counts = (1, 2, 1, 0)
    expected_option_types = ({"CALL"}, {"CALL", "PUT"}, {"CALL"}, set())
    for index, (event_tick, phase, timestamp) in enumerate(zip(
        event_ticks, phases, SELECTED_TIMESTAMPS
    )):
        current_tick["value"] = event_tick
        sources.set_tick(event_tick)
        for quote_tick in quote_sets[timestamp]:
            _publish_contract_scoped_replay_quote(
                quote_tick,
                option_master=master,
                market=bootstrap.bundle.market,
                order_book=bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime.order_book,
            )
        bootstrap.bundle.market.publish_replay_tick(event_tick)
        result = loop.last_result
        assert result is not None
        assert result.signals == 1
        assert result.approved == 1
        assert result.routed >= 1
        assert result.filled >= 1
        assert result.rejected == 0
        assert result.execution_ids

        open_lots = tuple(
            lot for lot in loop.multi_leg_bridge.position_lot_store.open_lots()
            if lot.run_id == run_id and lot.strategy_id == S5_ID and lot.remaining_quantity > 0
        )
        assert len(open_lots) == expected_open_counts[index]
        assert {str(lot.instrument_identity.option_type).upper() for lot in open_lots} == expected_option_types[index]
        if index == 0:
            assert open_lots[0].remaining_quantity == 1
            assert open_lots[0].instrument_identity.instrument_id == call_id
        if index == 1:
            assert {lot.instrument_identity.instrument_id for lot in open_lots} == {call_id, put_id}
            assert all(lot.remaining_quantity == 1 for lot in open_lots)
        if index == 2:
            assert open_lots[0].instrument_identity.instrument_id == call_id

    assert loop.multi_leg_bridge.fee_ledger is not None
    assert loop.multi_leg_bridge.fee_ledger.total(run_id=run_id) >= Decimal("0")
    assert bootstrap.bundle.account.snapshot() is not None
    assert Track5GapDivergence.CURRENT_EXECUTION_POLICY_APPROVED is False



def test_s5_sidecar_profile_is_validation_only_and_stable_identity_is_time_invariant():
    profile, manifest, selected = _load_scenario()
    assert profile["execution_enabled"] is False
    assert profile["virtual_runtime_validation_enabled"] is True
    assert profile["order_submission_enabled"] is False
    assert profile["live_api_enabled"] is False
    assert profile["production_runtime_eligible"] is False
    assert manifest["constraints"]["multiplier"] is None
    assert profile["scenario"]["runtime_dte_proxy"]["not_used_for_s5_policy"] is True
    call_ids = {
        _stable_synthetic_id(profile, profile["scenario"]["expiry"], "CALL", profile["scenario"]["strike"])
        for _candidate, _pair in selected
    }
    put_ids = {
        _stable_synthetic_id(profile, profile["scenario"]["expiry"], "PUT", profile["scenario"]["strike"])
        for _candidate, _pair in selected
    }
    assert len(call_ids) == len(put_ids) == 1
    assert call_ids.isdisjoint(put_ids)
    assert all(identity.startswith("SYNTHETIC_CONTRACT:S5:A8R8:") for identity in call_ids | put_ids)


def test_production_track5_entry_policy_remains_disabled():
    assert Track5GapDivergence.CURRENT_EXECUTION_POLICY_APPROVED is False
