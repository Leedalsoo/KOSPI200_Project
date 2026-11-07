from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from contracts.market_data_freshness import FreshnessStatus
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle
from environments.high_speed.synthetic_replay_adapter import SyntheticReplayAdapter
from environments.high_speed.validation_only_s8_runtime_adapter import S8ValidationOnlyRuntimeAdapter


ROOT = Path(__file__).resolve().parents[3]


def _adapter(regime: str = "normal"):
    folder = ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly" / regime
    return S8ValidationOnlyRuntimeAdapter(
        dataset=folder,
        manifest_path=folder / "manifest.json",
        risk_profile_path=ROOT / "config/validation_only/q25_s8_v3" / regime / "risk_profile.json",
    )


@pytest.mark.parametrize("regime", ["high_vol", "normal"])
def test_s8_v3_scenarios_have_isolated_contract_identity_and_manifest(regime):
    folder = ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly" / regime
    adapter = SyntheticReplayAdapter(folder, manifest_path=folder / "manifest.json")
    rows = [json.loads(line) for line in (folder / "20261104.jsonl").read_text(encoding="utf-8").splitlines()]
    keys = [(row["tick"]["timestamp"], row["tick"]["instrument_id"]) for row in rows]
    assert len(rows) == 216
    assert len(keys) == len(set(keys))
    assert all(row["scenario_metadata"]["regime"] == regime.upper() for row in rows)
    tick = adapter.adapt_record(rows[0])["tick"]
    assert tick["validation_only"] is True
    assert tick["scenario_id"] == adapter.manifest["scenario_id"]
    assert tick["dte_trading_days"] == rows[0]["scenario_metadata"]["dte_trading_days"]
    assert tick["instrument_id"].startswith(adapter.manifest["validation_identity_namespace"])


def test_s8_validation_adapter_enables_only_instance_local_readiness():
    adapter = _adapter()
    strategy = Track8MacroRegimeMonthlyStrangle()
    assert strategy.runtime_config_verified is False
    assert strategy.risk_limits_available is False
    adapter.apply_to_strategy(strategy, synthetic_sources=SimpleNamespace(source_name="SYNTHETIC:test"))
    assert strategy.runtime_config_verified is True
    assert strategy.risk_limits_available is True
    assert strategy.DTE_ENTRY == 10
    assert Track8MacroRegimeMonthlyStrangle().runtime_config_verified is False
    assert Track8MacroRegimeMonthlyStrangle().risk_limits_available is False


def test_s8_validation_adapter_requires_manifest_bound_risk_profile(tmp_path):
    profile_path = ROOT / "config/validation_only/q25_s8_v3/normal/risk_profile.json"
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    payload["profiles"]["track8_monthly_strangle"]["dataset_manifest"] = "data/old/manifest.json"
    bad = tmp_path / "risk_profile.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    folder = ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly/normal"
    with pytest.raises(ValueError, match="RISK_MANIFEST_MISMATCH"):
        S8ValidationOnlyRuntimeAdapter(
            dataset=folder, manifest_path=folder / "manifest.json", risk_profile_path=bad
        )


def test_s8_validation_risk_gate_accumulates_call_put_pair_and_deduplicates_retry():
    adapter = _adapter()
    plan = SimpleNamespace(
        strategy_id="track8_macro_regime_monthly_strangle",
        purpose="MONTHLY_STRANGLE_ENTRY_CALL",
        group_id="S8-GROUP-1",
    )

    def prepared(leg_id: str, price: str):
        identity = SimpleNamespace(
            instrument_id=f"SYNTHETIC_CONTRACT:S8V3:NORMAL:20261119:{leg_id.upper()}:500",
            option_type=leg_id.upper(), identity_source="OPTION_MASTER",
            contract_multiplier="250000",
        )
        leg = SimpleNamespace(leg_id=leg_id, side="BUY", quantity=1)
        return [(leg, identity, "client", object(), object(), "4.50", price)]

    adapter.bind_run_id("S8-RISK-TEST")
    adapter.validate_group(plan, prepared("call", "5.00"))
    # A retry updates the same leg reservation; it does not count as a second leg.
    adapter.validate_group(plan, prepared("call", "5.00"))
    assert sum(adapter._reserved["S8-GROUP-1"].values()) == 1_250_000
    audit = adapter.risk_audit_records[-1]
    assert audit["run_id"] == "S8-RISK-TEST"
    assert audit["scenario_id"] == adapter.evidence.scenario_id
    assert audit["computed_gross_premium_krw"] == "1250000.00"
    assert audit["operational_reference_overage_krw"] == "1000000.00"
    assert audit["validation_budget_overage_krw"] == "0"
    plan = SimpleNamespace(
        strategy_id="track8_macro_regime_monthly_strangle",
        purpose="MONTHLY_STRANGLE_ENTRY_PUT",
        group_id="S8-GROUP-1",
    )
    with pytest.raises(ValueError, match="PREMIUM_LIMIT_EXCEEDED"):
        adapter.validate_group(plan, prepared("put", "5.00"))


def test_s8_validation_freshness_requires_current_manifest_bound_quote():
    adapter = _adapter()
    folder = ROOT / "data/derived_scenario/q25_s8_v3/strategy8_monthly/normal"
    replay_adapter = SyntheticReplayAdapter(folder, manifest_path=folder / "manifest.json")
    row = json.loads((folder / "20261104.jsonl").read_text(encoding="utf-8").splitlines()[0])
    tick = replay_adapter.adapt_record(row)["tick"]
    instrument_id = tick["instrument_id"]
    identity = SimpleNamespace(
        instrument_id=instrument_id, option_type=tick["option_type"],
        strike=tick["strike_price"], expiry=tick["expiry"],
        contract_multiplier=tick["contract_multiplier"], identity_source="OPTION_MASTER",
    )
    command = SimpleNamespace(instrument_id=instrument_id, broker_symbol=instrument_id)
    plan = SimpleNamespace(strategy_id="track8_macro_regime_monthly_strangle")
    market = SimpleNamespace(option_quotes={
        (tick["option_type"], float(tick["strike_price"]), tick["expiry"]): {
            "bid": tick["bid_price"], "ask": tick["ask_price"],
            "last": tick["last_price"], "timestamp": tick["timestamp"],
            "contract_multiplier": tick["contract_multiplier"],
        }
    })
    master = SimpleNamespace(get_contract_identity=lambda _symbol: SimpleNamespace(
        shrn_iscd=instrument_id, option_type=tick["option_type"],
        strike=tick["strike_price"], expiry=tick["expiry"],
        contract_multiplier=tick["contract_multiplier"],
    ))
    sources = SimpleNamespace(_tick=SimpleNamespace(timestamp=tick["timestamp"]))
    verdict = adapter.freshness_verdict(
        plan=plan, identity=identity, command=command,
        option_master=master, market=market, synthetic_sources=sources,
    )
    assert verdict.status is FreshnessStatus.FRESH
    assert verdict.environment == "SYNTHETIC_VALIDATION_ONLY"
    assert verdict.evidence_sha256
    sources._tick = SimpleNamespace(timestamp="2026-11-04T10:00:00+09:00")
    stale = adapter.freshness_verdict(
        plan=plan, identity=identity, command=command,
        option_master=master, market=market, synthetic_sources=sources,
    )
    assert stale.status is FreshnessStatus.STALE


def test_s8_validation_waits_for_both_pair_quotes_at_the_same_replay_instant():
    adapter = _adapter()
    timestamp = "2026-11-04T10:00:00+09:00"
    call = SimpleNamespace(option_type="CALL", strike="515", contract_multiplier="250000")
    put = SimpleNamespace(option_type="PUT", strike="485", contract_multiplier="250000")
    selection = SimpleNamespace(expiry="20261119", call=call, put=put)
    quote = {"bid": 1.0, "ask": 1.1, "last": 1.05, "timestamp": timestamp, "contract_multiplier": 250000}
    market = SimpleNamespace(option_quotes={("PUT", 485.0, "20261119"): quote})
    tick = SimpleNamespace(timestamp=timestamp)
    assert adapter.pair_quotes_ready(selection, market=market, tick=tick) is False
    market.option_quotes[("CALL", 515.0, "20261119")] = dict(quote)
    assert adapter.pair_quotes_ready(selection, market=market, tick=tick) is True
    market.option_quotes[("PUT", 485.0, "20261119")] = dict(quote, timestamp="2026-11-04T09:59:00+09:00")
    assert adapter.pair_quotes_ready(selection, market=market, tick=tick) is False


def test_s8_validation_risk_gate_allows_identity_checked_reduce_only_close():
    adapter = _adapter()
    plan = SimpleNamespace(
        strategy_id="track8_macro_regime_monthly_strangle",
        purpose="MONTHLY_STRANGLE_CLOSE_CALL",
        group_id="S8-CLOSE-1",
    )
    identity = SimpleNamespace(
        instrument_id="SYNTHETIC_CONTRACT:S8V3:NORMAL:20261119:CALL:515",
        option_type="CALL", strike=515, expiry="20261119", contract_multiplier=250000,
    )
    leg = SimpleNamespace(leg_id="call", side="SELL", quantity=1, strike=515)
    adapter.validate_group(plan, [(leg, identity, "client", object(), object(), "1.00", "1.10")])


def test_s8_validation_risk_gate_allows_identity_checked_two_leg_expiry_close():
    adapter = _adapter()
    plan = SimpleNamespace(
        strategy_id="track8_macro_regime_monthly_strangle",
        purpose="MONTHLY_STRANGLE_CLOSE",
        group_id="S8-EXPIRY-CLOSE-1",
    )
    prepared = []
    for leg_id, strike in (("put", 485), ("call", 515)):
        identity = SimpleNamespace(
            instrument_id=f"SYNTHETIC_CONTRACT:S8V3:NORMAL:20261119:{leg_id.upper()}:{strike}",
            option_type=leg_id.upper(), strike=strike,
            expiry="20261119", contract_multiplier=250000,
        )
        leg = SimpleNamespace(leg_id=leg_id, side="SELL", quantity=1, strike=strike)
        prepared.append((leg, identity, f"client-{leg_id}", object(), object(), "1.00", "1.10"))
    adapter.validate_group(plan, prepared)


def test_s8_validation_option_marks_require_exact_manifest_bound_current_quotes():
    from decimal import Decimal

    adapter = _adapter()
    timestamp = "2026-11-05T09:10:00+09:00"
    call_id = "SYNTHETIC_CONTRACT:S8A5S09:STOP:20261119:CALL:515"
    put_id = "SYNTHETIC_CONTRACT:S8A5S09:STOP:20261119:PUT:485"
    call = SimpleNamespace(
        shrn_iscd=call_id, option_type="CALL", strike=515,
        expiry="20261119", contract_multiplier=250000,
    )
    put = SimpleNamespace(
        shrn_iscd=put_id, option_type="PUT", strike=485,
        expiry="20261119", contract_multiplier=250000,
    )
    selection = SimpleNamespace(expiry="20261119", call=call, put=put)

    def quote(instrument_id, option_type, strike, last):
        return {
            "instrument_id": instrument_id, "option_type": option_type,
            "strike": strike, "expiry": "20261119",
            "contract_multiplier": 250000, "bid": last - 0.02,
            "ask": last + 0.02, "last": last, "timestamp": timestamp,
            "source": "SYNTHETIC:DERIVED_SCENARIO",
        }

    market = SimpleNamespace(option_quotes_by_instrument_id={
        call_id: quote(call_id, "CALL", 515, 0.40),
        put_id: quote(put_id, "PUT", 485, 1.00),
    })
    tick = SimpleNamespace(timestamp=timestamp)
    assert adapter.option_mark_prices(selection, market=market, tick=tick) == {
        "call": Decimal("0.4"), "put": Decimal("1.0"),
    }
    market.option_quotes_by_instrument_id[call_id]["timestamp"] = "2026-11-05T09:09:00+09:00"
    assert adapter.option_mark_prices(selection, market=market, tick=tick) is None


def test_s8_validation_expiry_pair_close_rejects_identity_expiry_mismatch():
    adapter = _adapter()
    plan = SimpleNamespace(
        strategy_id="track8_macro_regime_monthly_strangle",
        purpose="MONTHLY_STRANGLE_CLOSE",
        group_id="S8-EXPIRY-CLOSE-IDENTITY-MISMATCH",
    )
    prepared = []
    for leg_id, strike, expiry in (
        ("put", 485, "20261119"),
        ("call", 515, "20261126"),
    ):
        instrument_expiry = "20261119"
        identity = SimpleNamespace(
            instrument_id=f"SYNTHETIC_CONTRACT:S8V3:NORMAL:{instrument_expiry}:{leg_id.upper()}:{strike}",
            option_type=leg_id.upper(), strike=strike,
            expiry=expiry, contract_multiplier=250000,
        )
        leg = SimpleNamespace(leg_id=leg_id, side="SELL", quantity=1, strike=strike)
        prepared.append((leg, identity, f"client-{leg_id}", object(), object(), "1.00", "1.10"))

    with pytest.raises(ValueError, match="S8_VALIDATION_EXPIRY_CLOSE_REDUCTION_IDENTITY_INVALID"):
        adapter.validate_group(plan, prepared)
