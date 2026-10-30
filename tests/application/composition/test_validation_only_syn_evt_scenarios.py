"""A1-2 tests for validation-only SYN-EVT catalogue."""
from __future__ import annotations
import ast
from dataclasses import replace
from pathlib import Path
import pytest
from environments.high_speed.validation_only_syn_evt_scenarios import (
    DEFAULT_STRATEGY_ORDER, GENERATOR_VERSION, IDENTITY_SOURCE_STATUS, PROVENANCE,
    SOURCE_STATUS, SynEvtScenario, produce_syn_evt_scenarios, validate_syn_evt_catalog)

ROOT=Path(__file__).resolve().parents[3]
PRODUCER=ROOT/"environments"/"high_speed"/"validation_only_syn_evt_scenarios.py"
CASES={"missing_quote","delayed_stale_quote","duplicate_event","zero_invalid_quote","orderbook_gap",
"wide_spread","insufficient_depth","underlying_gap","volatility_1_3x","whipsaw_reversal_1",
"whipsaw_reversal_2","trend_then_reversal","crash_rebound","d4_transition","expiry_cutoff",
"data_quality_recovery","identity_conflict","unknown_multiplier","limit_wait_cancel_no_price_reach",
"limit_price_reached_insufficient_volume","one_order_at_a_time","synthetic_input_rejected_real_vts_live"}

def test_catalogue_is_complete_deterministic_seeded_and_provenance_marked():
    a=produce_syn_evt_scenarios(seed=20261029)
    assert a==produce_syn_evt_scenarios(seed=20261029)
    assert a!=produce_syn_evt_scenarios(seed=20261030)
    assert len(a)==len(CASES) and {x.scenario_id for x in a}==CASES
    assert [x.sequence for x in a]==list(range(1,len(a)+1))
    assert len({x.event_id for x in a})==len(a)
    assert len({x.config_hash for x in a})==1 and len(a[0].config_hash)==64
    assert all(x.generator_version==GENERATOR_VERSION and x.seed==20261029 for x in a)
    assert all(x.synthetic and x.provenance==PROVENANCE and x.source_status==SOURCE_STATUS for x in a)
    assert all(x.validation_only and not x.production_runtime_eligible for x in a)
    assert all(x.identity_source_status==IDENTITY_SOURCE_STATUS and x.expected_invariant for x in a)

def test_every_catalogue_case_has_structural_validation_evidence():
    cases=produce_syn_evt_scenarios(seed=20261029); evidence=validate_syn_evt_catalog(cases)
    assert len(evidence)==len(CASES) and {x.scenario_id for x in evidence}==CASES
    assert all(x.status=="PASS" and x.checks and not x.reasons for x in evidence)

def test_only_approved_strategy_scope_including_no_strategy_3_or_4():
    cases=produce_syn_evt_scenarios(seed=20261029)
    assert DEFAULT_STRATEGY_ORDER==(6,7,8,1,9,5,2)
    assert {s for x in cases for s in x.strategy_ids}==set(DEFAULT_STRATEGY_ORDER)
    assert all(3 not in x.strategy_ids and 4 not in x.strategy_ids for x in cases)

@pytest.mark.parametrize("seed",[None,"20261029",True,2026.1029])
def test_seed_must_be_explicit_integer(seed):
    with pytest.raises(TypeError,match="SEED_MUST_BE_INTEGER"):
        produce_syn_evt_scenarios(seed=seed)

def test_validator_fails_closed_on_provenance_or_identity_mutation():
    case=produce_syn_evt_scenarios(seed=20261029)[0]
    bad_provenance=replace(case,provenance="REAL_VTS")
    bad_identity=replace(case,production_runtime_eligible=True)
    assert validate_syn_evt_catalog((bad_provenance,))[0].status=="FAIL"
    assert "SYNTHETIC_PROVENANCE_REQUIRED" in validate_syn_evt_catalog((bad_provenance,))[0].reasons
    assert validate_syn_evt_catalog((bad_identity,))[0].status=="FAIL"
    assert "IDENTITY_OR_RUNTIME_BOUNDARY_VIOLATION" in validate_syn_evt_catalog((bad_identity,))[0].reasons

def test_catalogue_module_is_not_imported_by_production_source():
    tree=ast.parse(PRODUCER.read_text(encoding="utf-8")); imports=set()
    for n in ast.walk(tree):
        if isinstance(n,ast.Import): imports.update(a.name for a in n.names)
        elif isinstance(n,ast.ImportFrom) and n.module: imports.add(n.module)
    assert not any(x.startswith(("application","core","infrastructure","interfaces")) for x in imports)
    roots=[ROOT/x for x in ("application","contracts","core","environments","infrastructure","interfaces")]
    target="environments.high_speed.validation_only_syn_evt_scenarios"; offenders=[]
    for root in roots:
        for path in root.rglob("*.py"):
            if path==PRODUCER or "__pycache__" in path.parts: continue
            try: t=ast.parse(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError,SyntaxError): continue
            for n in ast.walk(t):
                if isinstance(n,ast.Import) and any(a.name==target for a in n.names): offenders.append(f"{path.relative_to(ROOT)}:{n.lineno}")
                elif isinstance(n,ast.ImportFrom) and n.module==target: offenders.append(f"{path.relative_to(ROOT)}:{n.lineno}")
    assert offenders==[],f"validation-only catalogue connected to production: {offenders}"
