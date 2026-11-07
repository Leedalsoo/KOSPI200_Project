from __future__ import annotations
import hashlib, json
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE_DIR=ROOT/"data/derived_scenario/q25_strategy7_8_v2/strategy7_weekly"
SOURCE_DATASET=SOURCE_DIR/"20261103.jsonl"
SOURCE_MANIFEST=SOURCE_DIR/"manifest.json"
SOURCE_PROFILE=ROOT/"config/validation_only/q25_s05_1_s7_v2/risk_profile.json"
OUT_DIR=ROOT/"data/derived_scenario/q25_s05_3_s7_concurrent"
OUT_DATASET=OUT_DIR/"20261103.jsonl"
OUT_MANIFEST=OUT_DIR/"manifest.json"
OUT_PROFILE_DIR=ROOT/"config/validation_only/q25_s05_3_s7_concurrent"
OUT_PROFILE=OUT_PROFILE_DIR/"risk_profile.json"
REPORT=ROOT/"reports/synth/Q25_A5_S05_3_S7_CONCURRENT_DATASET_20261107.json"
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    sm=json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    sp=json.loads(SOURCE_PROFILE.read_text(encoding="utf-8"))
    sh=digest(SOURCE_DATASET)
    if sh!=sm["dataset_sha256"] or sp["dataset_sha256"]!=sh: raise SystemExit("BLOCKED_SOURCE_HASH")
    rows=[json.loads(x) for x in SOURCE_DATASET.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(rows)!=216: raise SystemExit(f"BLOCKED_SOURCE_ROWS:{len(rows)}")
    rows.sort(key=lambda r:(str(r["tick"]["timestamp"]),str(r["scenario_metadata"]["group_id"]),0 if str(r["scenario_metadata"]["leg_id"]).upper()=="PUT" else 1,int(r["tick"]["seq_id"])))
    ts=defaultdict(list)
    for r in rows:
        t=r["tick"]; m=r["scenario_metadata"]
        if r.get("provenance")!="DERIVED_SCENARIO" or r.get("synthetic") is not True or m.get("validation_only") is not True or m.get("runtime_eligible") is not False: raise SystemExit("BLOCKED_PROVENANCE")
        if t.get("instrument_identity_status")!="BLOCKED_IDENTITY_OWNER_UNRESOLVED": raise SystemExit("BLOCKED_IDENTITY_STATUS")
        ts[str(t["timestamp"])].append((str(m["group_id"]),str(m["leg_id"]).upper()))
    expected={("S7_MON_20261109","CALL"),("S7_MON_20261109","PUT"),("S7_THU_20261112","CALL"),("S7_THU_20261112","PUT")}
    if len(ts)!=54 or any(len(v)!=4 or set(v)!=expected for v in ts.values()): raise SystemExit("BLOCKED_TIMESTAMP_COVERAGE")
    if [str(r["tick"]["timestamp"]) for r in rows]!=sorted(str(r["tick"]["timestamp"]) for r in rows): raise SystemExit("BLOCKED_CHRONOLOGY")
    if len({int(r["tick"]["seq_id"]) for r in rows})!=len(rows): raise SystemExit("BLOCKED_SEQ_DUPLICATE")
    group_expiries = {}
    for row in rows:
        group_id = str(row["scenario_metadata"]["group_id"])
        expiry = str(row["tick"]["expiry"]).replace("-", "")[:8]
        if group_id in group_expiries and group_expiries[group_id] != expiry:
            raise SystemExit("BLOCKED_GROUP_EXPIRY_CONFLICT")
        group_expiries[group_id] = expiry
    if set(group_expiries) != {"S7_MON_20261109", "S7_THU_20261112"}:
        raise SystemExit("BLOCKED_GROUP_EXPIRY_COVERAGE")
    OUT_DIR.mkdir(parents=True,exist_ok=True); OUT_PROFILE_DIR.mkdir(parents=True,exist_ok=True)
    OUT_DATASET.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows),encoding="utf-8")
    dh=digest(OUT_DATASET); m=dict(sm)
    m.update({"dataset_path":str(OUT_DATASET.relative_to(ROOT)).replace("\\","/"),"output_path":str(OUT_DATASET.relative_to(ROOT)).replace("\\","/"),"dataset_sha256":dh,"output_sha256":dh,"output_bytes":OUT_DATASET.stat().st_size,"rows":len(rows),"runtime_event_order":"CHRONOLOGICAL_TIMESTAMP_THEN_GROUP_ID_THEN_LEG_ID","runtime_event_order_authority":"VALIDATION_ONLY_DERIVED_SCENARIO","concurrent_groups_per_timestamp":2,"strategy7_group_expiry_by_id":group_expiries,"contract_identity_authority":"SYNTHETIC_ONLY","expiry_is_authoritative":False,"identity_source_status":"BLOCKED_IDENTITY_OWNER_UNRESOLVED","runtime_eligible":False,"production_runtime_eligible":False,"validation_only":True})
    OUT_MANIFEST.write_text(json.dumps(m,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); mh=digest(OUT_MANIFEST)
    p=dict(sp); p.update({"dataset_path":str(OUT_DATASET.relative_to(ROOT)).replace("\\","/"),"dataset_manifest":str(OUT_MANIFEST.relative_to(ROOT)).replace("\\","/"),"dataset_sha256":dh,"manifest_sha256":mh,"scenario_id":m["scenario_id"],"contract_identity_authority":"SYNTHETIC_ONLY","identity_source_status":"BLOCKED_IDENTITY_OWNER_UNRESOLVED","expiry_is_authoritative":False,"runtime_eligible":False,"production_runtime_eligible":False,"allow_kis_api":False,"allow_live_orders":False,"allow_real_account":False,"operational_config_mutated":False})
    OUT_PROFILE.write_text(json.dumps(p,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); ph=digest(OUT_PROFILE)
    (OUT_PROFILE_DIR/"risk_profile.json.sha256").write_text(ph+"  risk_profile.json\n",encoding="ascii")
    report={"report_id":"Q25_A5_S05_3_S7_CONCURRENT_DATASET_20261107","verdict":"DATASET_READY_VALIDATION_ONLY","source_dataset_sha256":sh,"dataset_path":str(OUT_DATASET.relative_to(ROOT)).replace("\\","/"),"dataset_sha256":dh,"manifest_path":str(OUT_MANIFEST.relative_to(ROOT)).replace("\\","/"),"manifest_sha256":mh,"risk_profile_path":str(OUT_PROFILE.relative_to(ROOT)).replace("\\","/"),"risk_profile_sha256":ph,"rows":len(rows),"unique_timestamps":len(ts),"rows_per_timestamp":4,"groups_per_timestamp":2,"group_leg_coverage":"MON_CALL_PUT_AND_THU_CALL_PUT_AT_EACH_TIMESTAMP","chronological_order":True,"original_dataset_modified":False,"operational_risk_config_modified":False,"kis_api_called":False,"live_orders_or_real_account_used":False,"runtime_eligible":False,"production_runtime_eligible":False}
    REPORT.parent.mkdir(parents=True,exist_ok=True); REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
