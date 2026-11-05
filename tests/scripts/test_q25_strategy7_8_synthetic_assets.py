import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/derived_scenario/q25_strategy7_8"
PROFILE = ROOT / "config/validation_only/q25_strategy7_8_risk_profiles.v1.json"

def load_manifest(name):
    folder = BASE / name
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    raw = (folder / "20261103.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["dataset_sha256"]
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    assert len(rows) == manifest["rows"]
    return manifest, rows

def test_strategy7_two_weekly_groups_have_valid_two_sided_quotes():
    manifest, rows = load_manifest("strategy7_weekly")
    assert manifest["validation_only"] and not manifest["runtime_eligible"]
    assert set(manifest["groups"]) == {"S7_MON_20261109", "S7_THU_20261112"}
    assert all(r["scenario_metadata"]["expiry_is_authoritative"] is False for r in rows)
    assert all(r["tick"]["bid_price"] > 0 and r["tick"]["ask_price"] > r["tick"]["bid_price"] for r in rows)
    assert float(manifest["max_bid_ask_spread_ratio"]) <= 0.20
    for group in manifest["groups"]:
        legs = {r["scenario_metadata"]["leg_id"] for r in rows if r["scenario_metadata"]["group_id"] == group}
        assert legs == {"put", "call"}

def test_strategy8_monthly_pair_has_dte_scenarios_and_valid_quotes():
    manifest, rows = load_manifest("strategy8_monthly")
    assert manifest["validation_only"] and not manifest["runtime_eligible"]
    assert {r["scenario_metadata"]["regime"] for r in rows} == {"NORMAL", "HIGH_VOL"}
    assert {r["scenario_metadata"]["dte_trading_days"] for r in rows} == {10, 12}
    assert all(r["tick"]["expiry"] == "20261119" for r in rows)
    assert all(r["tick"]["bid_price"] > 0 and r["tick"]["ask_price"] > r["tick"]["bid_price"] for r in rows)
    assert float(manifest["max_bid_ask_spread_ratio"]) <= 0.20

def test_validation_profiles_are_isolated_and_keep_risk_audit():
    p = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert p["validation_only"] and not p["runtime_eligible"]
    assert p["allow_live_orders"] is False and p["allow_kis_api"] is False
    assert p["risk_checks_enabled"] is True
    assert p["operational_config_mutated"] is False
    assert set(p["audit_fields_required"]) >= {"computed_gross_premium_krw","computed_max_loss_krw","operational_reference_overage_krw","validation_budget_overage_krw"}
    for profile in p["profiles"].values():
        assert profile["max_gross_premium_outlay_krw"] >= profile["max_loss_krw"]
        assert profile["max_gross_premium_outlay_krw"] > profile["operational_reference_limit_krw"]
