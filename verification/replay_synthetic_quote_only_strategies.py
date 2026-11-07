from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.composition.automated_virtual_trading_loop import AutomatedVirtualTradingLoop
from application.strategy_hub.hub import StrategyHub
from core.strategy.contracts import StrategyContext, StrategyInput, UnavailableStrategyPayload
from core.strategy.standard_registry import (
    STANDARD_STRATEGY_KEYS,
    build_standard_strategy_registry,
)
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick


SYNTHETIC_PATH = ROOT / "data" / "synthetic_market_data" / "20261020" / "synthetic_quote_repairs_20261020.jsonl"
MANIFEST_PATH = SYNTHETIC_PATH.with_suffix(".manifest.json")
STRATEGY_MANIFEST = ROOT / "config" / "strategies" / "strategy-manifest.v1.json"
OUTPUT_PATH = ROOT / "verification" / "evidence" / "quote_only_strategy_replay_20261021_v2.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_tick(row: dict[str, Any], sequence: int) -> ReferenceCanonicalMarketTick:
    observation = row["observation"]
    contract = observation.get("contract") or {}
    quote = observation.get("quote") or {}
    bid, ask = quote.get("bid"), quote.get("ask")
    if bid is None or ask is None or float(bid) <= 0 or float(ask) <= 0 or float(ask) < float(bid):
        raise ValueError(f"SYNTHETIC_QUOTE_INVALID:{observation.get('observation_id')}")
    if quote.get("last") is not None or quote.get("volume") is not None:
        raise ValueError(f"SYNTHETIC_TRADE_FIELDS_MUST_REMAIN_NULL:{observation.get('observation_id')}")
    timestamp = observation.get("observed_at") or observation.get("collected_at")
    if not timestamp:
        raise ValueError(f"SYNTHETIC_TIMESTAMP_MISSING:{observation.get('observation_id')}")
    return ReferenceCanonicalMarketTick(
        timestamp=timestamp,
        underlying_price=(
            float(observation["underlying_price"])
            if observation.get("underlying_price") is not None else None
        ),
        underlying_symbol=str(observation.get("underlying_symbol") or ""),
        underlying_observed_hour=str(observation.get("underlying_observed_hour") or ""),
        underlying_source=str(observation.get("underlying_source") or ""),
        strike_price=float(contract["strike"]),
        option_type=str(contract["option_type"]),
        contract_multiplier=(
            float(contract["contract_multiplier"])
            if contract.get("contract_multiplier") is not None else None
        ),
        bid_price=float(bid),
        ask_price=float(ask),
        last_price=None,
        volume=None,
        seq_id=sequence,
        expiry=str(contract.get("expiry") or ""),
        symbol=str(contract.get("symbol") or contract.get("instrument_id") or ""),
        option_source="SYNTHETIC",
        instrument_id=str(contract.get("instrument_id") or ""),
        implied_volatility=(float((observation.get("analytics") or {})["implied_volatility"])
                            if (observation.get("analytics") or {}).get("implied_volatility") is not None else None),
        delta=(float((observation.get("analytics") or {})["delta"])
               if (observation.get("analytics") or {}).get("delta") is not None else None),
        gamma=(float((observation.get("analytics") or {})["gamma"])
               if (observation.get("analytics") or {}).get("gamma") is not None else None),
        theta=(float((observation.get("analytics") or {})["theta"])
               if (observation.get("analytics") or {}).get("theta") is not None else None),
        vega=(float((observation.get("analytics") or {})["vega"])
              if (observation.get("analytics") or {}).get("vega") is not None else None),
    )


def run() -> dict[str, Any]:
    if OUTPUT_PATH.exists():
        raise FileExistsError(f"REFUSE_OVERWRITE_REPLAY_EVIDENCE:{OUTPUT_PATH}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("source_type") != "SYNTHETIC" or manifest.get("runtime_eligible") is not False:
        raise ValueError("SYNTHETIC_MANIFEST_GUARD_FAILED")
    if sha256(SYNTHETIC_PATH) != manifest.get("output_sha256"):
        raise ValueError("SYNTHETIC_DATA_HASH_MISMATCH")

    rows = [
        json.loads(line)
        for line in SYNTHETIC_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 155:
        raise ValueError(f"EXPECTED_155_SYNTHETIC_ROWS_GOT:{len(rows)}")

    ticks = [load_tick(row, index) for index, row in enumerate(rows, start=1)]
    strategy_reports: list[dict[str, Any]] = []
    for strategy_id, version in STANDARD_STRATEGY_KEYS:
        registry = build_standard_strategy_registry(STRATEGY_MANIFEST)
        definition = registry.definition_for(strategy_id, version)
        if definition is None:
            raise ValueError(f"STRATEGY_DEFINITION_MISSING:{strategy_id}:{version}")
        required_sources = tuple(definition.required_sources)
        hub = StrategyHub(registry, ((strategy_id, version),))

        def context_builder(_tick, state, *, sid=strategy_id, sources=required_sources):
            return {
                sid: StrategyContext(
                    market_state=state,
                    strategy_id=sid,
                    input=StrategyInput(
                        payload=UnavailableStrategyPayload(
                            strategy_id=sid,
                            required_sources=sources,
                            reason="SYNTHETIC_QUOTE_ONLY_REPLAY_HAS_NO_AUTHORITATIVE_RUNTIME_INPUTS",
                        ),
                        data_status={source: "UNAVAILABLE" for source in sources},
                    ),
                )
            }

        loop = AutomatedVirtualTradingLoop.__new__(AutomatedVirtualTradingLoop)
        loop._quote_only_events = []
        loop.context_builder = context_builder
        loop.strategy_hub = hub
        for tick in ticks:
            loop.on_quote_only_tick(tick)

        events = list(loop.quote_only_events)
        strategy_failures = [
            failure
            for event in events
            for result in (event.get("strategy_results") or {}).values()
            for failure in result.get("failures", [])
        ]
        strategy_signals = sum(
            int(result.get("signals", 0))
            for event in events
            for result in (event.get("strategy_results") or {}).values()
        )
        report = {
            "strategy_id": strategy_id,
            "code_version": version,
            "synthetic_rows": len(ticks),
            "quote_only_events": len(events),
            "evaluated_no_execution": sum(event.get("status") == "EVALUATED_NO_EXECUTION" for event in events),
            "blocked_missing_underlying": sum(event.get("reason") == "AUTHORITATIVE_UNDERLYING_PRICE_UNAVAILABLE" for event in events),
            "strategy_failures": len(strategy_failures),
            "signals": strategy_signals,
            "order_routing_invoked": False,
            "verdict": "PASS_OFFLINE_FAIL_CLOSED_BOUNDARY" if strategy_signals == 0 and all(
                event.get("order_routing") == "NOT_INVOKED" for event in events
            ) else "FAIL",
            "limitations": [
                "Synthetic quote-only input-boundary test, not a strategy profitability or REAL_VTS performance test.",
                "Authoritative strategy runtime inputs are deliberately unavailable in this isolated replay; strategy logic is not scored.",
                "No trade price or volume is inferred from quote prices or quantities.",
            ],
        }
        strategy_reports.append(report)

    payload = {
        "schema_version": "synthetic-quote-only-strategy-replay-v1",
        "created_at_kst": datetime.now().astimezone().isoformat(),
        "source_type": "SYNTHETIC",
        "runtime_eligible": False,
        "validation_only": True,
        "synthetic_input_path": str(SYNTHETIC_PATH.relative_to(ROOT)),
        "synthetic_input_sha256": sha256(SYNTHETIC_PATH),
        "synthetic_manifest_sha256": sha256(MANIFEST_PATH),
        "rows_replayed": len(ticks),
        "strategy_count": len(strategy_reports),
        "order_routing_invoked": False,
        "kis_api_calls": 0,
        "strategies": strategy_reports,
        "overall_verdict": "PASS_OFFLINE_FAIL_CLOSED_BOUNDARY" if all(
            item["verdict"] == "PASS_OFFLINE_FAIL_CLOSED_BOUNDARY" for item in strategy_reports
        ) else "FAIL",
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["evidence_path"] = str(OUTPUT_PATH.relative_to(ROOT))
    payload["evidence_sha256"] = sha256(OUTPUT_PATH)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


if __name__ == "__main__":
    run()