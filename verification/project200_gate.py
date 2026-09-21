from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "verification" / "project200_gate_report.json"

# 과거 No.414에서 확인된 대표적인 가짜 운영 데이터 패턴.
# 발견되면 해당 소스가 실제 runtime 값을 공급하는지 확인하기 전까지 BLOCK.
FORBIDDEN_LITERAL_PATTERNS = [
    r"45200",
    r"100000",
    r"1450000",
    r"VIRTUAL-8801-01",
    r"98\.45",
    r"12\.3",
    r"SYNTHETIC_HIGH_SPEED",
]

# 운영 UI 소스에서 임의 생성하면 안 되는 대표적인 패턴.
FORBIDDEN_OPERATIONAL_PATTERNS = [
    r"fake[_-]?(market|account|order|fill|position|pnl)",
    r"mock[_-]?(market|account|order|fill|position|pnl)",
    r"dummy[_-]?(market|account|order|fill|position|pnl)",
    r"generate[_-]?(fake|dummy)",
]

TARGET_ROOTS = [
    ROOT / "core",
    ROOT / "application",
    ROOT / "infrastructure",
    ROOT / "environments",
    ROOT / "interfaces",
]

EXCLUDED_SOURCE_PARTS = {"__pycache__"}


@dataclass
class Check:
    name: str
    status: str
    detail: str


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return p.returncode, p.stdout[-12000:]


def check_branch() -> Check:
    rc, out = run(["git", "branch", "--show-current"])
    branch = out.strip()
    return Check("branch_project200", "PASS" if rc == 0 and branch == "Project200" else "FAIL", f"branch={branch!r}")


def check_required_files() -> Check:
    missing = [str(p.relative_to(ROOT)) for p in [ROOT / "AGENTS.md"] if not p.exists()]
    return Check("required_files", "PASS" if not missing else "FAIL", f"missing={missing}")


def check_source_literals() -> Check:
    findings: list[str] = []
    operational_patterns = FORBIDDEN_OPERATIONAL_PATTERNS + [
        r"\bproposed_quantity\s*=\s*1\b",
        r"\bproposed_quantity\s*:\s*int\s*=\s*1\b",
        r"\b(?:contract_)?multiplier\s*=\s*250000\b",
        r"\b(?:contract_)?multiplier\s*:\s*(?:int|float)\s*=\s*250000\b",
    ]
    legacy_ui_patterns = FORBIDDEN_LITERAL_PATTERNS
    ui_roots = {ROOT / "interfaces"}
    patterns_by_root = [(root, operational_patterns) for root in TARGET_ROOTS]
    patterns_by_root.extend((root, legacy_ui_patterns) for root in ui_roots)
    for root, patterns in patterns_by_root:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in EXCLUDED_SOURCE_PARTS for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in patterns:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    findings.append(f"{path.relative_to(ROOT)} matches {pattern}")
    return Check("no_known_fake_operational_literals", "PASS" if not findings else "FAIL", "; ".join(findings) or "no findings")


def check_runtime_wiring_source() -> Check:
    adapter = ROOT / "interfaces" / "control_tower" / "ui_adapter.py"
    server = ROOT / "interfaces" / "control_tower" / "server.py"
    if not adapter.exists() or not server.exists():
        return Check("runtime_wiring_source", "FAIL", "required Control Tower source missing")

    a = adapter.read_text(encoding="utf-8", errors="replace")
    s = server.read_text(encoding="utf-8", errors="replace")
    required_adapter = ["runtime_controller", "risk_engine", "handle_command"]
    required_server = ["adapter.handle_command"]
    missing = [x for x in required_adapter if x not in a] + [x for x in required_server if x not in s]
    return Check("runtime_wiring_source", "PASS" if not missing else "FAIL", f"missing={missing}")


def check_test_suite() -> Check:
    test_dir = ROOT / "tests" / "control_tower"
    if not test_dir.exists():
        return Check("control_tower_tests", "FAIL", "tests/control_tower does not exist")
    rc, out = run([sys.executable, "-m", "pytest", "-q", str(test_dir)])
    return Check("control_tower_tests", "PASS" if rc == 0 else "FAIL", f"exit_code={rc}\n{out}")


def check_runtime_path_test() -> Check:
    candidates = [
        "tests/control_tower/test_runtime_ui_path.py",
        "tests/control_tower/test_runtime_bootstrap.py",
        "tests/control_tower/test_panic_halt_runtime.py",
    ]
    existing = [p for p in candidates if (ROOT / p).exists()]
    if not existing:
        return Check("runtime_path_tests_present", "FAIL", "no required runtime verification test found")
    rc, out = run([sys.executable, "-m", "pytest", "-q", *existing])
    return Check("runtime_path_tests", "PASS" if rc == 0 else "FAIL", f"files={existing}\nexit_code={rc}\n{out}")


def check_runtime_evidence() -> Check:
    probe_script = ROOT / "verification" / "runtime_evidence.py"
    if not probe_script.exists():
        return Check("runtime_evidence_probe", "FAIL", "verification/runtime_evidence.py does not exist")
    rc, out = run([sys.executable, str(probe_script)])
    try:
        decoder = json.JSONDecoder()
        evidence = None
        for index, char in enumerate(out):
            if char == "{":
                try:
                    candidate, _ = decoder.raw_decode(out[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict) and "status" in candidate:
                    evidence = candidate
                    break
        if evidence is not None and evidence.get("status") == "BLOCKED":
            status = "BLOCKED"
        else:
            status = "PASS" if rc == 0 else "FAIL"
    except (TypeError, ValueError):
        status = "PASS" if rc == 0 else "FAIL"
    return Check("runtime_evidence_probe", status, f"exit_code={rc}\n{out}")


def main() -> int:
    checks = [
        check_branch(),
        check_required_files(),
        check_source_literals(),
        check_runtime_wiring_source(),
        check_test_suite(),
        check_runtime_path_test(),
        check_runtime_evidence(),
    ]

    verdict = "PASS" if all(c.status == "PASS" for c in checks) else "FAIL"
    payload = {
        "verdict": verdict,
        "gate": "Project200 deterministic verification gate",
        "checks": [asdict(c) for c in checks],
    }
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
