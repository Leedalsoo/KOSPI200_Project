from copy import deepcopy
import pytest
from application.composition.validation_only_cross_source_alignment_auditor import ValidationOnlyCrossSourceAlignmentAuditor
GOOD="a"*64
def group(ts="2026-10-12T09:00:45+09:00"):
 return {"group_id":"20261012:090045","trading_date":"20261012","timestamp":ts,"option_rows":[{"symbol":"B01611A14","timestamp":ts,"source_observed_at":ts,"collected_at":"2026-10-12T00:00:46+00:00","identity":{"expiry":"20261112","strike":"1040.00","option_type":"CALL"}}],"underlying":{"source":"KIS:H0UPCNT0","source_event_time":ts}}
def rest(ts="2026-10-12T09:00:30+09:00"):
 return {"trading_date":"20261012","symbol":"B01611A14","request_symbol":"B01611A14","response_symbol":"B01611A14","source_event_time":ts,"collected_at":"2026-10-12T00:01:00+00:00","payload_sha256":"c"*64,"identity":{"expiry":"20261112","strike":"1040.00","option_type":"CALL"}}
def audit(gs,rs):
 return ValidationOnlyCrossSourceAlignmentAuditor(validation_only=True).audit(timestamp_groups=gs,rest_observations=rs,as_of="2026-11-18T17:59:00+09:00",accepted_manifest_sha256=GOOD,rest_source_manifest_sha256="b"*64)
def test_exact_and_nearest_prior_are_distinguished():
 g1=group();g2=group("2026-10-12T09:00:46+09:00");r=audit([g1,g2],[rest("2026-10-12T09:00:45+09:00")])
 assert r["option_to_rest_alignment"]["REST_EXACT"]==1 and r["option_to_rest_alignment"]["REST_NEAREST_PRIOR"]==1
 assert r["gate_release_permitted"] is False and r["authority_claimed"] is False and r["mutation_applied"] is False
def test_future_rest_is_never_used_as_prior_anchor():
 r=audit([group()],[rest("2026-10-12T09:01:00+09:00")])
 assert r["option_to_rest_alignment"]["REST_FUTURE_ONLY"]==1 and r["option_to_rest_alignment"].get("REST_NEAREST_PRIOR",0)==0
def test_missing_symbol_and_zero_source_time_are_separate():
 a=audit([group()],[]);x=rest();x["source_event_time"]=None;b=audit([group()],[x])
 assert a["option_to_rest_alignment"]["NO_REST_SYMBOL"]==1 and b["option_to_rest_alignment"]["NO_VALID_REST_SOURCE_TIME"]==1
def test_rest_identity_mismatch_is_not_used():
 x=rest();x["response_symbol"]="C01611A14";r=audit([group()],[x])
 assert r["rest_source_inventory"]["identity_mismatches"] and r["option_to_rest_alignment"]["NO_REST_SYMBOL"]==1
def test_contract_identity_mismatch_is_reported():
 x=rest();x["identity"]["strike"]="1045.00";r=audit([group()],[x])
 assert r["identity_mismatches"][0]["mismatches"]["strike"]["accepted"]=="1040.00"
def test_underlying_exact_prior_median_and_synthetic_are_distinguished():
 a=group();b=group("2026-10-12T09:00:46+09:00");b["underlying"]={"source":"KIS:H0UPCNT0:GROUP_MEDIAN","source_event_time":"2026-10-12T09:00:45+09:00"}
 c=group("2026-10-12T09:00:47+09:00");c["underlying"]={"source":"SYNTHETIC:KRX_SHOCK_V4_NEAREST_SPOT","source_event_time":"2026-10-12T09:00:45+09:00"}
 r=audit([a,b,c],[])
 assert r["underlying_alignment"]["KIS_EXACT_TIMESTAMP"]==1 and r["underlying_alignment"]["KIS_GROUP_MEDIAN_DERIVED"]==1 and r["underlying_alignment"]["SYNTHETIC_DERIVED_ANCHOR"]==1
def test_option_event_time_mismatch_is_reported():
 a=group();a["option_rows"][0]["source_observed_at"]="2026-10-12T09:00:44+09:00";r=audit([a],[])
 assert any(x.startswith("OPTION_EVENT_TIME_MISMATCH") for x in r["issues"])
def test_report_hash_is_deterministic_and_inputs_are_read_only():
 gs=[group()];before=deepcopy(gs);a=audit(gs,[rest()]);b=audit(gs,[rest()])
 assert a["report_sha256"]==b["report_sha256"] and gs==before
def test_validation_only_opt_in_is_required():
 with pytest.raises(ValueError,match="CROSS_SOURCE_ALIGNMENT_VALIDATION_ONLY_OPT_IN_REQUIRED"):ValidationOnlyCrossSourceAlignmentAuditor()
