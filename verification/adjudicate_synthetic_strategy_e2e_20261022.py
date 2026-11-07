import json, hashlib
from pathlib import Path
from datetime import datetime
src=Path('verification/evidence/synthetic_strategy_e2e_20261022.json')
out=Path('verification/evidence/synthetic_strategy_e2e_20261022_adjudication.json')
if out.exists(): raise FileExistsError('REFUSE_OVERWRITE_ADJUDICATION')
sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
d=json.loads(src.read_text(encoding='utf-8'))
d['source_report_path']=str(src)
d['source_report_sha256']=sha(src)
d['created_at_adjudication']=datetime.now().astimezone().isoformat()
for item in d['strategies']:
    item['verdict']='BLOCKED_REQUIRED_INPUTS_UNAVAILABLE' if item['unavailable'] else 'BLOCKED_NO_SIGNAL_OR_EXECUTION_LIFECYCLE'
d['integrated']['verdict']='BLOCKED_REQUIRED_INPUTS_UNAVAILABLE_AND_NO_EXECUTION_LIFECYCLE'
d['overall_verdict']='BLOCKED'
d['verdict_correction']='The initial PASS_SYNTHETIC_RUNTIME_PATH label only reflected zero runtime exceptions; it did not establish strategy E2E PASS. All 9 runs had zero signals/orders/fills; integrated run reported 610 unavailable strategy-input events. Adjudicated E2E status is BLOCKED.'
out.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':d['overall_verdict'],'path':str(out),'sha256':sha(out),'source_report_sha256':d['source_report_sha256'],'signals':d['integrated']['signals'],'filled':d['integrated']['filled'],'unavailable':d['integrated']['unavailable']},ensure_ascii=False))
