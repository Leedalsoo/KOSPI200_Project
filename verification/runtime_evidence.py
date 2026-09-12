"""Runtime Evidence Probe — 권위적 KIS Live Runtime Composition 연결성 프로브.

테스트용 가짜/합성 데이터(synthetic capital, mock transport, 임의 계좌 등)를 사용하지 않고,
저장소의 실제 authoritative production composition entry point
(`application.composition.live_runtime_authoritative_composition.create_authoritative_kis_live_runtime_composition`)
을 호출하여 구성된 실제 객체들의 type, module, state를 관찰·검증합니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.composition.live_runtime_authoritative_composition import (
    create_authoritative_kis_live_runtime_composition,
)


def probe_production_runtime() -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "status": "STARTING",
        "probe": "Project200 Production Runtime Probe (Authoritative KIS Live)",
        "components": {},
    }

    try:
        # 1. Authoritative KIS Live Production Composition 기동
        coordinator = create_authoritative_kis_live_runtime_composition()

        controller = coordinator._controller
        bootstrap = coordinator._bootstrap
        bundle = controller.bundle if hasattr(controller, "bundle") else None

        # 2. 컴포넌트 실제 객체 속성 수집
        evidence["components"] = {
            "LiveRuntimeLifecycleCoordinator": {
                "module": type(coordinator).__module__,
                "type": type(coordinator).__qualname__,
            },
            "RuntimeController": {
                "module": type(controller).__module__,
                "type": type(controller).__qualname__,
            },
            "LiveRuntimeBootstrap": {
                "module": type(bootstrap).__module__,
                "type": type(bootstrap).__qualname__,
            },
            "Execution": {
                "module": type(bootstrap.execution).__module__,
                "type": type(bootstrap.execution).__qualname__,
            },
            "OrderRouter": {
                "module": type(bootstrap.order_router).__module__,
                "type": type(bootstrap.order_router).__qualname__,
            },
        }
        if bundle is not None:
            evidence["components"]["ActiveBundle"] = {
                "module": type(bundle).__module__,
                "type": type(bundle).__qualname__,
                "market": type(bundle.market).__qualname__,
                "broker": type(bundle.broker).__qualname__,
                "position": type(bundle.position).__qualname__,
            }

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
