import json,hashlib
from pathlib import Path
from datetime import datetime
src=Path('verification/evidence/synthetic_integrated_e2e_780_20261022.json')
out=Path('verification/evidence/synthetic_integrated_e2e_20261022_adjudication.json')
if out.exists(): raise FileExistsError('REFUSE_OVERWRITE_INTEGRATED_ADJUDICATION')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
d=json.loads(src.read_text(encoding='utf-8'))
d['source_report_path']=str(src)
d['source_report_sha256']=sha(src)
d['adjudicated_at']=datetime.now().astimezone().isoformat()
d['scope']='offline synthetic integrated Virtual Runtime replay; 781 events from existing 1y synthetic scenario dataset'
d['verdict']='BLOCKED'
d['adjudication_reason']='Zero signals, approvals, routed orders, fills, and execution IDs; 2332 strategy-input unavailability counts; no strategy execution lifecycle evidence. Zero runtime exceptions alone is not E2E PASS.'
d['limitation']='This synthetic scenario replay is not REAL_VTS or production evidence. Missing required inputs and unset strategy risk/config gates remain fail-closed.'
out.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'verdict':d['verdict'],'events':d['events'],'signals':d['signals'],'filled':d['filled'],'unavailable':d['unavailable'],'source_sha256':d['source_report_sha256'],'adjudication_path':str(out),'adjudication_sha256':sha(out)},ensure_ascii=False))
