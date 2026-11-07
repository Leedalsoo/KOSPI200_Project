from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
import time
import traceback
from collections import Counter
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, time as clock_time
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

ROOT = Path.cwd()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def independent_preflight(dataset: Path) -> dict:
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    master_path = ROOT / manifest["option_master_path"]
    master_bytes = master_path.read_bytes()
    master_hash = hashlib.sha256(master_bytes).hexdigest()
    if master_hash != manifest["option_master_sha256"]:
        raise RuntimeError("PREFLIGHT_OPTION_MASTER_HASH_MISMATCH")
    master = json.loads(master_bytes.decode("utf-8-sig"))
    rows = master.get("OutBlock_1")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("PREFLIGHT_OPTION_MASTER_ROWS_MISSING")
    by_code = {str(row.get("ISU_CD", "")).strip(): row for row in rows if str(row.get("ISU_CD", "")).strip()}
    weekly_pattern = re.compile(r"(?:^|\s)(?:C|P)\s+(\d{4}W\d)\s+([0-9][0-9,]*(?:\.[0-9]+)?)")
    monthly_pattern = re.compile(r"(?:^|\s)(?:C|P)\s+(20\d{4})\s+([0-9][0-9,]*(?:\.[0-9]+)?)")
    events = 0
    previous_seq = 0
    previous_ts = None
    day_counts = {}
    bar_sizes = Counter()
    contract_classes = Counter()
    expiry_pairs = set()
    first_tick = None
    last_tick = None
    for day_meta in manifest["days"]:
        day = day_meta["date"]
        path = dataset / day_meta["file"]
        if not path.is_file():
            raise RuntimeError(f"PREFLIGHT_DAY_FILE_MISSING:{day}")
        local_count = 0
        local_bars = Counter()
        with path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("schema") != manifest["schema"] or record.get("provenance") != "DERIVED_SCENARIO":
                    raise RuntimeError(f"PREFLIGHT_SCHEMA_PROVENANCE:{day}:{line_no}")
                tick = record["tick"]
                ts = datetime.fromisoformat(tick["timestamp"])
                if ts.date().isoformat() != day:
                    raise RuntimeError(f"PREFLIGHT_DATE_MISMATCH:{day}:{tick['timestamp']}")
                if ts.time() < clock_time(8, 45):
                    raise RuntimeError(f"PREFLIGHT_BEFORE_SESSION:{tick['timestamp']}")
                close = clock_time(15, 20) if day_meta["session_type"] == "MONTHLY_LAST_TRADING_DAY" else clock_time(15, 45)
                if ts.time() >= close:
                    raise RuntimeError(f"PREFLIGHT_AFTER_SESSION:{tick['timestamp']}:{close}")
                minute_offset = (ts.hour * 60 + ts.minute) - (8 * 60 + 45)
                if minute_offset < 0 or minute_offset % 5 != 0 or ts.second or ts.microsecond:
                    raise RuntimeError(f"PREFLIGHT_5M_ALIGNMENT:{tick['timestamp']}")
                if int(tick["seq_id"]) != previous_seq + 1:
                    raise RuntimeError(f"PREFLIGHT_SEQUENCE_GAP:{previous_seq}:{tick['seq_id']}")
                previous_seq = int(tick["seq_id"])
                if previous_ts is not None and ts < previous_ts:
                    raise RuntimeError(f"PREFLIGHT_TIMESTAMP_ORDER:{previous_ts}:{ts}")
                previous_ts = ts
                code = str(tick["instrument_id"])
                row = by_code.get(code)
                if row is None:
                    raise RuntimeError(f"PREFLIGHT_UNKNOWN_MASTER_CODE:{code}")
                if str(row.get("RGHT_TP_NM", "")).upper() != str(tick["option_type"]).upper():
                    raise RuntimeError(f"PREFLIGHT_OPTION_TYPE_MISMATCH:{code}")
                identity_name = str(row.get("ISU_NM", ""))
                identity_match = weekly_pattern.search(identity_name) or monthly_pattern.search(identity_name)
                if identity_match is None or Decimal(identity_match.group(2).replace(",", "")) != Decimal(str(tick["strike_price"])):
                    raise RuntimeError(f"PREFLIGHT_STRIKE_MISMATCH:{code}:{identity_name}")
                expiry = str(tick["expiry"])
                if not re.fullmatch(r"\d{8}", expiry):
                    raise RuntimeError(f"PREFLIGHT_EXPIRY_NOT_EXACT:{code}:{expiry}")
                month = str(tick["contract_month"])
                if month != expiry[:6]:
                    raise RuntimeError(f"PREFLIGHT_MONTH_EXPIRY_MISMATCH:{code}:{month}:{expiry}")
                if tick["contract_class"] == "monthly":
                    expected_expiry = str(manifest["monthly_expiries"].get(month, "")).replace("-", "")
                    if expected_expiry != expiry:
                        raise RuntimeError(f"PREFLIGHT_MONTHLY_EXPIRY_MISMATCH:{code}:{expiry}:{expected_expiry}")
                elif tick["contract_class"] == "weekly":
                    match = weekly_pattern.search(str(row.get("ISU_NM", "")))
                    if not match:
                        raise RuntimeError(f"PREFLIGHT_WEEKLY_SERIES_MISSING:{code}")
                    series = match.group(1)
                    expected_expiry = ""
                    product = str(row.get("PROD_NM", "")).strip()
                    for key, value in manifest.get("weekly_series_expiries", {}).items():
                        if key == f"{product}:{series}":
                            expected_expiry = str(value).replace("-", "")
                            break
                    if expected_expiry != expiry:
                        raise RuntimeError(f"PREFLIGHT_WEEKLY_EXPIRY_MISMATCH:{code}:{expiry}:{expected_expiry}")
                else:
                    raise RuntimeError(f"PREFLIGHT_CONTRACT_CLASS_INVALID:{code}")
                if float(tick["contract_multiplier"]) != 250000.0:
                    raise RuntimeError(f"PREFLIGHT_MULTIPLIER_INVALID:{code}")
                bid, ask = float(tick["bid_price"]), float(tick["ask_price"])
                if bid <= 0 or ask <= bid:
                    raise RuntimeError(f"PREFLIGHT_BID_ASK_INVALID:{code}:{bid}:{ask}")
                premium_tick = Decimal("0.05") if Decimal(str(bid)) >= Decimal("10") else Decimal("0.01")
                if Decimal(str(bid)) % premium_tick != 0 or Decimal(str(ask)) % (Decimal("0.05") if Decimal(str(ask)) >= Decimal("10") else Decimal("0.01")) != 0:
                    raise RuntimeError(f"PREFLIGHT_PRICE_TICK_INVALID:{code}")
                expiry_dt = datetime.strptime(expiry, "%Y%m%d").replace(hour=15, minute=20)
                seconds = int((expiry_dt - ts).total_seconds())
                if int(tick["time_to_expiry_seconds"]) != seconds:
                    raise RuntimeError(f"PREFLIGHT_TTE_INVALID:{code}:{tick['time_to_expiry_seconds']}:{seconds}")
                if float(tick["time_value"]) < -1e-8:
                    raise RuntimeError(f"PREFLIGHT_NEGATIVE_TIME_VALUE:{code}")
                local_count += 1
                local_bars[tick["timestamp"]] += 1
                contract_classes[str(tick["contract_class"])] += 1
                expiry_pairs.add((month, expiry, str(tick["contract_class"])))
                events += 1
                if first_tick is None:
                    first_tick = tick
                last_tick = tick
        expected = int(day_meta["events"])
        if local_count != expected:
            raise RuntimeError(f"PREFLIGHT_DAY_EVENT_COUNT:{day}:{local_count}:{expected}")
        bad_bars = {ts: count for ts, count in local_bars.items() if count not in (10, 14)}
        if bad_bars:
            raise RuntimeError(f"PREFLIGHT_BAR_SHAPE:{day}:{list(bad_bars.items())[:3]}")
        day_counts[day] = {"events": local_count, "bars": len(local_bars)}
        bar_sizes.update(local_bars.values())
    if events != int(manifest["events"]):
        raise RuntimeError(f"PREFLIGHT_TOTAL_EVENT_COUNT:{events}:{manifest['events']}")
    if previous_seq != events:
        raise RuntimeError(f"PREFLIGHT_FINAL_SEQUENCE:{previous_seq}:{events}")
    return {
        "status": "PASS",
        "dataset": dataset.name,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "option_master_sha256": master_hash,
        "trading_days": len(day_counts),
        "events": events,
        "bars": sum(x["bars"] for x in day_counts.values()),
        "first_timestamp": first_tick["timestamp"] if first_tick else None,
        "last_timestamp": last_tick["timestamp"] if last_tick else None,
        "contract_class_counts": dict(contract_classes),
        "exact_contract_expiry_pairs": len(expiry_pairs),
        "bar_events_distribution": dict(bar_sizes),
        "monthly_rollovers": manifest["monthly_rollovers"],
        "weekly_rollovers": manifest["weekly_rollovers"],
        "market_rule_limitations": manifest.get("market_rule_limitations", []),
        "daily_counts": day_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--port", type=int, default=18083)
    parser.add_argument("--report", required=True)
    parser.add_argument("--progress", required=True)
    args = parser.parse_args()
    dataset = Path(args.dataset).resolve()
    report_path = Path(args.report).resolve()
    progress_path = Path(args.progress).resolve()
    store_path = dataset / "control_tower_replay.jsonl"
    result = {
        "test_harness": Path(__file__).name,
        "dataset": str(dataset),
        "dataset_store": str(store_path),
        "run_started_at": datetime.now().astimezone().isoformat(),
        "status": "RUNNING",
    }
    write_json(progress_path, {"phase": "independent_preflight", "events_seen": 0})
    try:
        preflight = independent_preflight(dataset)
        result["independent_preflight"] = preflight
        write_json(progress_path, {"phase": "runtime_replay", "events_seen": 0, "target_events": preflight["events"]})
    except Exception as exc:
        result.update(status="FAIL", phase="independent_preflight", error=str(exc), traceback=traceback.format_exc())
        write_json(report_path, result)
        return 2

    from environments import high_speed as _unused_package  # noqa: F401
    import environments.high_speed.virtual_runtime_replay as replay_module
    from environments.high_speed.replay_runner import HighSpeedReplayRunner

    captured = {}
    runner_holder = {"runner": None}
    original_bootstrap = replay_module.create_virtual_runtime_bootstrap
    original_attach = replay_module.attach_standard_automated_loop
    original_replay = HighSpeedReplayRunner.run

    def capture_bootstrap(*pargs, **kwargs):
        bootstrap = original_bootstrap(*pargs, **kwargs)
        captured["bootstrap"] = bootstrap
        runner = runner_holder["runner"]
        context = getattr(bootstrap, "run_context", None)
        if runner is not None and context is not None:
            runner.run_id = context.run_id
        return bootstrap

    def capture_loop(*pargs, **kwargs):
        loop = original_attach(*pargs, **kwargs)
        captured["loop"] = loop
        return loop

    def capture_progress(self, *, start=None, end=None, speed=float("inf"), on_event=None, max_events=None):
        count = 0
        def observed(tick):
            nonlocal count
            on_event(tick)
            count += 1
            if count % 2000 == 0:
                write_json(progress_path, {"phase": "runtime_replay", "events_seen": count, "target_events": preflight["events"], "last_timestamp": tick.timestamp})
        replay_report = original_replay(self, start=start, end=end, speed=speed, on_event=observed, max_events=max_events)
        write_json(progress_path, {"phase": "runtime_replay_complete", "events_seen": count, "target_events": preflight["events"], "last_timestamp": replay_report.last_timestamp})
        return replay_report

    replay_module.create_virtual_runtime_bootstrap = capture_bootstrap
    replay_module.attach_standard_automated_loop = capture_loop
    HighSpeedReplayRunner.run = capture_progress
    replay = None
    try:
        runner = replay_module.HighSpeedVirtualRuntimeReplayRunner(dataset, run_id=f"E2E-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        runner_holder["runner"] = runner
        replay = runner.run()
        result["replay"] = asdict(replay)
        result["replay"]["strategy_status"] = [asdict(x) for x in replay.strategy_status]
        result["replay"]["strategy_signal_counts"] = dict(replay.strategy_signal_counts)
        result["replay"]["execution_ids"] = list(replay.execution_ids)
        result["status"] = "REPLAY_COMPLETED"
    except Exception as exc:
        result.update(status="FAIL", phase="runtime_replay", error=str(exc), traceback=traceback.format_exc())
    finally:
        replay_module.create_virtual_runtime_bootstrap = original_bootstrap
        replay_module.attach_standard_automated_loop = original_attach
        HighSpeedReplayRunner.run = original_replay

    bootstrap = captured.get("bootstrap")
    loop = captured.get("loop")
    if bootstrap is None:
        result["status"] = "FAIL"
        result["control_tower"] = {"status": "BLOCKED", "reason": "BOOTSTRAP_NOT_CAPTURED"}
        write_json(report_path, result)
        return 3

    try:
        context = getattr(bootstrap, "run_context", None)
        active = getattr(getattr(bootstrap, "run_hub", None), "active", None)
        if context is not None:
            context = replace(context, historical_source="DERIVED_SCENARIO", historical_store_path=str(store_path))
            bootstrap.run_context = context
            if active is not None:
                active.context = context
        vssf = bootstrap.bundle.execution._authoritative_execute.__self__.vssf_runtime
        broker_api = bootstrap.bundle.broker_api
        account = vssf.account
        positions = getattr(account, "positions", {})
        try:
            group_ids = list(broker_api.get_group_ids())
        except Exception:
            group_ids = []
        try:
            account_snapshot = broker_api.get_account_snapshot()
            position_snapshot = broker_api.get_position_snapshot()
            pnl_snapshot = broker_api.get_pnl_state()
            margin_snapshot = broker_api.get_margin_state()
            def convert(value):
                return asdict(value) if is_dataclass(value) else value
            broker_evidence = {
                "account_snapshot": convert(account_snapshot),
                "position_snapshot": convert(position_snapshot),
                "pnl_snapshot": convert(pnl_snapshot),
                "margin_snapshot": convert(margin_snapshot),
                "position_symbols": list(getattr(account, "positions", {}).keys()),
                "position_count": len(positions),
                "account_realized_pnl": float(getattr(account, "realized_pnl", 0.0)),
                "account_unrealized_pnl": float(getattr(account, "unrealized_pnl", 0.0)),
                "group_ids": group_ids,
            }
            group_reports = {}
            for group_id in group_ids:
                try:
                    group_reports[group_id] = [convert(x) for x in broker_api.get_group_reports(group_id)]
                except Exception as exc:
                    group_reports[group_id] = {"error": str(exc)}
            broker_evidence["group_reports"] = group_reports
            result["virtual_broker_position_pnl"] = broker_evidence
        except Exception as exc:
            result["virtual_broker_position_pnl"] = {"status": "UNAVAILABLE", "error": str(exc), "traceback": traceback.format_exc()}

        if replay is not None:
            result["pipeline_counts"] = {
                "events": replay.events,
                "signals": replay.signals,
                "approved": replay.approved,
                "routed": replay.routed,
                "filled": replay.filled,
                "rejected": replay.rejected,
                "execution_ids": len(replay.execution_ids),
                "strategies_reported": len(replay.strategy_status),
                "strategies_with_reaction_signals": sum(1 for x in replay.strategy_status if x.reaction_signals),
                "strategies_with_execution_signals": sum(1 for x in replay.strategy_status if x.execution_signals),
                "strategies_with_runtime_failures": sum(1 for x in replay.strategy_status if x.runtime_failures),
                "strategies_with_unavailable": sum(1 for x in replay.strategy_status if x.unavailable),
            }

        import interfaces.control_tower.server as ct_server
        ct_server.ControlTowerRequestHandler.tower = bootstrap.control_tower_hub
        ct_server.ControlTowerRequestHandler.adapter = bootstrap.ui_adapter
        server = ThreadingHTTPServer(("127.0.0.1", args.port), ct_server.ControlTowerRequestHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, name="Project200-E2E-ControlTower", daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{args.port}"
        api = {}
        for endpoint in ("/api/status", "/api/strategies", "/api/run", "/api/scenarios"):
            deadline = time.time() + 30
            last_error = None
            while time.time() < deadline:
                try:
                    with urlopen(base_url + endpoint, timeout=3) as response:
                        api[endpoint] = {"http_status": response.status, "body": json.loads(response.read().decode("utf-8"))}
                    break
                except Exception as exc:
                    last_error = str(exc)
                    time.sleep(0.25)
            else:
                raise RuntimeError(f"CONTROL_TOWER_API_NOT_READY:{endpoint}:{last_error}")
        run_body = api["/api/run"]["body"]
        strategy_rows = api["/api/strategies"]["body"].get("strategies", [])
        last_tick = run_body.get("last_replay_tick") or {}
        expected_last = result.get("replay", {}).get("strategy_status")
        api_checks = {
            "api_run_active": run_body.get("active") is True,
            "api_run_id_matches_replay": bool(replay and run_body.get("run_id") == replay.run_id),
            "api_store_matches_dataset": run_body.get("historical_store_path") == str(store_path),
            "api_last_tick_matches_replay": bool(replay and last_tick.get("timestamp") == result["independent_preflight"]["last_timestamp"]),
            "api_strategy_count": len(strategy_rows),
            "api_strategy_ids": [x.get("strategy_id") for x in strategy_rows],
            "api_account_present": isinstance(run_body.get("account"), dict),
            "api_position_present": isinstance(run_body.get("position"), dict),
            "api_pnl_present": isinstance(run_body.get("pnl"), dict),
            "api_execution_reports_count": len(run_body.get("execution_reports", [])),
        }
        api_checks["status"] = "PASS" if (
            api_checks["api_run_active"]
            and api_checks["api_store_matches_dataset"]
            and api_checks["api_last_tick_matches_replay"]
            and api_checks["api_strategy_count"] == 9
            and api_checks["api_account_present"]
            and api_checks["api_position_present"]
            and api_checks["api_pnl_present"]
        ) else "FAIL"
        result["control_tower"] = {
            "base_url": base_url,
            "api": api,
            "checks": api_checks,
            "server_pid": os.getpid(),
            "same_bootstrap_as_replay": True,
            "same_run_context": True,
            "browser_dom_smoke": "PENDING_PLAYWRIGHT",
        }
        result["server_ready"] = True
        result["run_completed_at"] = datetime.now().astimezone().isoformat()
        write_json(report_path, result)
        write_json(progress_path, {"phase": "control_tower_ready", "events_seen": result.get("pipeline_counts", {}).get("events", 0), "target_events": preflight["events"], "url": base_url, "report": str(report_path)})
        print(json.dumps({"status": result["status"], "report": str(report_path), "url": base_url, "checks": api_checks, "pipeline_counts": result.get("pipeline_counts")}, ensure_ascii=False), flush=True)
        while True:
            time.sleep(1)
    except Exception as exc:
        result.update(status="FAIL", phase="control_tower", control_tower_error=str(exc), control_tower_traceback=traceback.format_exc())
        write_json(report_path, result)
        write_json(progress_path, {"phase": "control_tower_failed", "error": str(exc), "report": str(report_path)})
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
