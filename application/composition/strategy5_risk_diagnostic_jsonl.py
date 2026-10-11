"""Best-effort append-only diagnostic evidence for Strategy 5 Risk preflight.

This writer is observational only: callers must isolate failures from Risk/order flow.
"""
from __future__ import annotations

import json
import re
from hashlib import sha256
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


def _decimal(value: Any) -> str | None:
    if value is None:
        return None
    return str(value if isinstance(value, Decimal) else Decimal(str(value)))


def _safe_run_id(run_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(run_id)).strip("._")
    if not value or value in {".", ".."}:
        raise ValueError("STRATEGY5_RISK_DIAGNOSTIC_RUN_ID_INVALID")
    digest = sha256(str(run_id).encode("utf-8")).hexdigest()[:10]
    return f"{value[:100]}-{digest}"


class Strategy5RiskDiagnosticJsonl:
    """One append-only JSONL file per run; never participates in Risk decisions."""

    def __init__(self, root: str | Path = "verification/results/strategy5_risk_diagnostics") -> None:
        self.root = Path(root)

    def append_preflight(self, *, run_id: str, strategy_id: str, group_id: str,
                         evaluations: list[dict[str, Any]], total_required_margin: Any,
                         total_balance: Any, used_margin: Any, free_margin: Any,
                         max_margin_utilization_ratio: Any, group_margin_ratio: Any,
                         aggregate_rejection: str | None, leg_rejected: bool) -> Path:
        safe_run_id = _safe_run_id(run_id)
        path = self.root / f"{safe_run_id}.jsonl"
        record = {
            "schema_version": "strategy5-risk-diagnostic.v1",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": "GROUP_RISK_PREFLIGHT",
            "provenance": {"run_id": run_id, "strategy_id": strategy_id, "group_id": group_id},
            "legs": evaluations,
            "aggregate": {
                "total_required_margin": _decimal(total_required_margin),
                "total_balance": _decimal(total_balance),
                "used_margin": _decimal(used_margin),
                "free_margin": _decimal(free_margin),
                "max_margin_utilization_ratio": _decimal(max_margin_utilization_ratio),
                "computed_group_margin_ratio": _decimal(group_margin_ratio),
                "aggregate_rejection": aggregate_rejection,
                "leg_risk_rejected": bool(leg_rejected),
                "decision": "DENY" if leg_rejected or aggregate_rejection else "ALLOW",
            },
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line)
            stream.flush()
        return path
