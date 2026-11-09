from dataclasses import replace
from decimal import Decimal
import json
import pytest
from contracts.types import ExecutionReport
from core.oms.multi_leg_plan import build_trap_plan
from core.strategy.track2_entry_sequence import TRACK2_ENTRY_SEQUENCE,Track2EntrySequenceError,evaluate_track2_entry_progress,validate_track2_entry_plan
from core.risk.track2_validation_profile import Track2ValidationProfileError,load_track2_validation_profile

def plan():
 return build_trap_plan(group_id="s2-validation-group",strategy_id="track2_asymmetric_trap",purpose="ASYMMETRIC_TRAP_WIDE",short_put=Decimal("490"),short_call=Decimal("510"),long_put=Decimal("495"),long_call=Decimal("505"),quantity=1)

def report(leg_id,status,filled,remaining):
 return ExecutionReport(client_order_id="order-"+leg_id,broker_order_id="broker-"+leg_id,execution_id="exec-"+leg_id if filled else None,status=status,filled_quantity=filled,remaining_quantity=remaining,execution_price=Decimal("1") if filled else None,execution_timestamp=None,group_id="s2-validation-group",leg_id=leg_id)

def test_track2_plan_uses_inner_buys_before_outer_sells():
 p=plan(); assert tuple((x.leg_id,x.side,x.option_type) for x in p.legs)==TRACK2_ENTRY_SEQUENCE; validate_track2_entry_plan(p)

def test_track2_sequence_rejects_legacy_short_first_order():
 p=plan()
 with pytest.raises(Track2EntrySequenceError,match="SEQUENCE_MISMATCH"): validate_track2_entry_plan(replace(p,legs=tuple(reversed(p.legs))))

def test_track2_partial_fill_blocks_progress_without_repair_or_flatten_choice():
 x=evaluate_track2_entry_progress(plan(),[report("inner_put","PARTIALLY_FILLED",1,0)])
 assert (x.status,x.next_leg_id,x.reason)==("BLOCKED",None,"LEG_NOT_TERMINAL_OR_PARTIAL")

def test_track2_second_leg_ready_only_after_first_leg_fully_filled():
 x=evaluate_track2_entry_progress(plan(),[report("inner_put","FILLED",1,0)])
 assert (x.status,x.next_leg_id)==("READY","inner_call")

def test_track2_reject_does_not_advance():
 x=evaluate_track2_entry_progress(plan(),[report("inner_put","REJECTED",0,1)])
 assert x.status=="BLOCKED" and x.next_leg_id is None

def test_track2_validation_profile_is_non_executable():
 p=load_track2_validation_profile()
 assert not p.execution_enabled and not p.order_submission_enabled and not p.numeric_limits_resolved
 assert set(p.policy_dependencies)=={"S2-U16","S2-U17","S2-U18","S2-U19","S2-U20","S2-U21"}
 with pytest.raises(Track2ValidationProfileError,match="CANNOT_AUTHORIZE_EXECUTION"): p.require_execution()

def test_track2_validation_profile_rejects_numeric_limit(tmp_path):
 raw=json.loads(DEFAULT_PROFILE.read_text(encoding="utf-8"))
 raw["risk_limits"]["max_margin_utilization_ratio"]="0.50"
 path=tmp_path/"risk_profile.json"; path.write_text(json.dumps(raw),encoding="utf-8")
 with pytest.raises(Track2ValidationProfileError,match="LIMITS_MUST_REMAIN_NULL"): load_track2_validation_profile(path)

from core.risk.track2_validation_profile import DEFAULT_TRACK2_VALIDATION_PROFILE as DEFAULT_PROFILE

def test_track2_later_leg_evidence_without_prior_fill_blocks_out_of_sequence():
    x = evaluate_track2_entry_progress(
        plan(), [report("inner_call", "FILLED", 1, 0)]
    )
    assert x.status == "BLOCKED"
    assert x.next_leg_id is None
    assert x.reason == "OUT_OF_SEQUENCE_LEG_EVIDENCE"


def test_track2_validation_profile_rejects_live_or_real_vts_enablement(tmp_path):
    raw = json.loads(DEFAULT_PROFILE.read_text(encoding="utf-8"))
    raw["real_vts_api_enabled"] = True
    path = tmp_path / "risk_profile.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(Track2ValidationProfileError, match="MUST_REMAIN_DISABLED"):
        load_track2_validation_profile(path)
