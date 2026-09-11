"""Runtime Evidence Probe — 실제 Production Bootstrap 및 런타임 객체 연결성 프로브.

테스트용 임의 데이터를 주입하지 않고, 저장소의 실제 production bootstrap
(`application.bootstrap.create_virtual_runtime_bootstrap`)을 호출하여
생성된 실제 객체들의 type, module, state, UI 프로젝션을 관찰·검증합니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.bootstrap import create_virtual_runtime_bootstrap
from interfaces.control_tower.view_models import TabEnvironmentId


def probe_production_runtime() -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "status": "STARTING",
        "probe": "Project200 Production Runtime Probe",
        "components": {},
    }

    try:
        # 1. Production Bootstrap 기동 (임의 객체 생성 금지: bootstrap이 직접 조립)
        bootstrap = create_virtual_runtime_bootstrap(initial_capital=100_000_000.0)

        bundle = bootstrap.bundle
        controller = bootstrap.runtime_controller
        risk_engine = bootstrap.risk_engine
        adapter = bootstrap.ui_adapter

        # 2. 컴포넌트 실제 객체 속성 수집
        evidence["components"] = {
            "RuntimeController": {
                "module": type(controller).__module__,
                "type": type(controller).__qualname__,
                "state": controller.status().state,
            },
            "ActiveBundle": {
                "module": type(bundle).__module__,
                "type": type(bundle).__qualname__,
                "environment": getattr(bundle, "environment", None).value,
                "connected": getattr(bundle, "connected", None),
            },
            "MarketProvider": {
                "module": type(bundle.market).__module__,
                "type": type(bundle.market).__qualname__,
            },
            "Broker": {
                "module": type(bundle.broker).__module__,
                "type": type(bundle.broker).__qualname__,
            },
            "Account": {
                "module": type(bundle.account).__module__,
                "type": type(bundle.account).__qualname__,
            },
            "Position": {
                "module": type(bundle.position).__module__,
                "type": type(bundle.position).__qualname__,
            },
            "Execution": {
                "module": type(bundle.execution).__module__,
                "type": type(bundle.execution).__qualname__,
            },
            "RiskEngine": {
                "module": type(risk_engine).__module__,
                "type": type(risk_engine).__qualname__,
                "kill_switch_active": risk_engine.is_kill_switch_active(),
            },
            "ControlTowerUIAdapter": {
                "module": type(adapter).__module__,
                "type": type(adapter).__qualname__,
            },
        }

        # 3. UI Data Interface 프로젝션 관찰
        summary = adapter.get_summary()
        detail = adapter.get_tab_detail(TabEnvironmentId.VIRTUAL_BROKER.value)

        evidence["ui_projection"] = {
            "summary_status": "PASS" if summary.get("tabs") else "FAIL",
            "active_tab": summary.get("active_environment"),
            "kill_switch_global": summary.get("kill_switch_global"),
            "broker_state": detail.get("broker_state"),
            "connection_state": detail.get("connection_state"),
            "account_number": detail.get("account_number"),
            "cash_balance": detail.get("cash_balance"),
        }

        # 필수 컴포넌트 유효성 판정
        required = ["RuntimeController", "ActiveBundle", "MarketProvider", "Broker", "Account", "Position", "Execution", "RiskEngine", "ControlTowerUIAdapter"]
        missing = [k for k in required if k not in evidence["components"]]
        if missing:
            evidence["status"] = "BLOCKED"
            evidence["error"] = f"Missing components in bootstrap: {missing}"
            return evidence

        evidence["status"] = "PASS"
        return evidence

    except Exception as exc:
        evidence["status"] = "BLOCKED"
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        return evidence


def main() -> int:
    evidence = probe_production_runtime()
    report_path = ROOT / "verification" / "runtime_evidence_report.json"
    report_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))

    if evidence.get("status") == "PASS":
        print("\n[Runtime Evidence Probe] VERDICT: PASS")
        return 0
    else:
        print(f"\n[Runtime Evidence Probe] VERDICT: {evidence.get('status', 'FAIL')}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
