import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / "config/validation_only/q25_s6_v1/risk_profile.json"
target = root / "config/validation_only/q25_s6_a4_matrix_v2/risk_profile.json"
if target.exists() or target.with_suffix(target.suffix + ".sha256").exists():
    raise SystemExit("REFUSE_OVERWRITE_A4_RISK_PROFILE_V2")
payload = json.loads(source.read_text(encoding="utf-8"))
manifests = list(payload["profiles"]["track6_daily_tail_insurance"]["dataset_manifests"])
new_manifest = "reports/synth/Q25_A4_S6_SYN_EVT_MANIFEST_20261106_v2.json"
if new_manifest not in manifests:
    manifests.append(new_manifest)
payload["profiles"]["track6_daily_tail_insurance"]["dataset_manifests"] = manifests
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
digest = hashlib.sha256(target.read_bytes()).hexdigest()
target.with_suffix(target.suffix + ".sha256").write_text(f"{digest}  {target.name}\n", encoding="ascii")
print(json.dumps({"risk_profile": str(target.relative_to(root)), "sha256": digest, "bom": target.read_bytes().startswith(b"\xef\xbb\xbf")}, ensure_ascii=False))
