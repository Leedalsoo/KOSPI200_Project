import json,hashlib
from pathlib import Path
from collections import Counter
from datetime import date
R=Path(__file__).resolve().parents[1]; O=R/"reports/synth"; O.mkdir(exist_ok=True)
P=R/"docs/strategy_specifications/04_strategy_1_to_9_scenario_test_plan_s2_delta_v0.2.md"
S=R/"docs/strategy_specifications/strategy_2_asymmetric_trap_spec_v0.4.md"; G=O/"Q25_A5_S24_S2_SPEC_GAP_MATRIX_20261109.md"; B=R/"docs/CURRENT_BASELINE.md"; A=R/"AGENTS.md"
U={"S2-U16":["S2-V03-E03","S2-V03-E04","S2-V03-E05","S2-V03-E06","S2-V03-E07"],"S2-U17":["S2-V03-B01","S2-V03-B08"],"S2-U18":["S2-V03-P01","S2-V03-P02","S2-V03-P03","S2-V03-P04","S2-V03-P05"],"S2-U19":["S2-V03-R01","S2-V03-T04"],"S2-U20":["S2-V03-E09"],"S2-U21":["S2-V03-B10","S2-V03-B11"]}
PM={s:u for u,ss in U.items() for s in ss}
I={"S2-V03-B04","S2-V03-B05","S2-V03-B07","S2-V03-B08","S2-V03-R01","S2-V03-P01","S2-V03-X01","S2-V03-X02","S2-V03-X04","S2-V03-T01","S2-V03-T02","S2-V03-T04"}
D={"S2-V03-B06","S2-V03-E01","S2-V03-E07","S2-V03-E08","S2-V03-B10","S2-V03-X03"}
rows=[]
for line in P.read_text(encoding="utf-8").splitlines():
 if not line.startswith("| S2-V03-"): continue
 c=[v.strip() for v in line.strip().strip("|").split("|")]
 sid,cl,tr,ex,ev,src=c[:6]; pol=PM.get(sid)
 cls="BLOCKED_SPEC" if pol or sid not in I|D else ("BLOCKED_INPUT" if sid in I else "DESIGNED")
 rows.append({"scenario_id":sid,"class":cl,"trigger":tr,"expected_behavior_draft":ex,"evidence":ev,"classification":cls,"status":cls,"policy_blocker":pol,"source_status":src,"market_data":"NOT_GENERATED","execution":"NOT_RUN"})
assert rows and len({x["scenario_id"] for x in rows})==len(rows)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sources={str(p.relative_to(R)).replace("\\","/"):sha(p) for p in [P,S,G,B,A]}
counts=dict(sorted(Counter(x["status"] for x in rows).items()))
obj={"catalog_id":"Q25_A5_S25_S2_SCENARIO_CATALOG_20261109","stage":"S25","created_at":date.today().isoformat(),"verdict":"PSB_PASS_SCENARIO_CATALOG_GENERATION_ONLY","specification_state":"DRAFT_UNVERIFIED_UNAPPROVED","scenario_count":len(rows),"status_counts":counts,"execution_enabled":False,"market_data_generated":False,"orders_allowed":False,"kis_api_allowed":False,"scenarios":rows,"unresolved_policy_register":{k:{"status":"UNRESOLVED_PROVISIONAL","scenario_ids":v} for k,v in U.items()},"source_sha256":sources,"limitations":["Catalog generation only; not strategy approval or Runtime validation.","No synthetic prices, contract identities, fees, quantities, or market events fabricated.","S2-U16 through S2-U21 remain unresolved and provisional.","No pytest, Runtime, Replay, KIS, REAL_VTS, Live, account, or order API executed."]}
jp=O/"Q25_A5_S25_S2_SCENARIO_CATALOG_20261109.json"; jp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
mp=O/"Q25_A5_S25_S2_SCENARIO_CATALOG_20261109.manifest.json"; mp.write_text(json.dumps({"catalog_id":obj["catalog_id"],"catalog_file":jp.name,"catalog_sha256":sha(jp),"scenario_count":len(rows),"status_counts":counts,"source_sha256":sources,"execution_enabled":False,"market_data_generated":False,"orders_allowed":False,"kis_api_allowed":False},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
lines=["기준: Current Baseline v2 @E865A11E5B12862294DA0DC2386870381AC91E0A5490A6D87BEDA52A7F7CF95D, 사용한 SSOT 항목 ID: CB2-01, CB2-02, CB2-03, CB2-04, CB2-05, CB2-06, CB2-09","","# Q25 A5 S25 — Strategy 2 시나리오 설계·생성 (2026-11-09)","", "판정: PSB_PASS_SCENARIO_CATALOG_GENERATION_ONLY",f"시나리오: {len(rows)}개 — "+", ".join(k+" "+str(v) for k,v in counts.items()),"범위: 시나리오 카탈로그·manifest 생성만. 실행 가능한 정책·테스트·시장 데이터 생성 아님.","S2 명세는 DRAFT_UNVERIFIED_UNAPPROVED; 신규 진입 및 Runtime 실행은 fail-closed 유지.","","## 산출물",jp.name,mp.name,"Catalog SHA-256: "+sha(jp),"Manifest SHA-256: "+sha(mp),"","## 미결 정책"]
for k,v in U.items(): lines.append(k+": UNRESOLVED_PROVISIONAL — "+", ".join(v))
lines += ["","## 검증 및 제한","원본 S2 plan 시나리오 행 전수 수집, 고유 ID, JSON 재파싱, 실행/시장 데이터 미생성 플래그 확인.","Draft 수치 경계는 원문 보존만 하며 승인 파라미터로 승격하지 않음.","pytest, Runtime/Replay, KIS/REAL_VTS/Live/실계좌/주문 API 미실행.","원본 raw data 및 기존 dataset/manifest 변경 없음.","","## 입력 SHA-256"]
for k,v in sources.items(): lines.append(k+": "+v)
rp=O/"Q25_A5_S25_S2_SCENARIO_CATALOG_20261109.md"; rp.write_text("\n".join(lines)+"\n",encoding="utf-8")
q=json.loads(jp.read_text(encoding="utf-8")); assert len(q["scenarios"])==len(rows) and all(x["execution"]=="NOT_RUN" and x["market_data"]=="NOT_GENERATED" for x in q["scenarios"])
print(json.dumps({"count":len(rows),"counts":counts,"catalog_sha256":sha(jp),"manifest_sha256":sha(mp),"report_sha256":sha(rp),"source_sha256":sources,"verification":"PASS"},ensure_ascii=False,indent=2))
