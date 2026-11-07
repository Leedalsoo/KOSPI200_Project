import argparse, hashlib, json, os, re, threading, time, traceback
from collections import Counter
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, time as clock_time
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT = Path.cwd()
import sys
sys.path.insert(0, str(ROOT))

def save(path, obj):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

def independent_data_audit(dataset):
    m = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    source = ROOT / m["option_master_path"]
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != m["option_master_sha256"]:
        raise ValueError("OPTION_MASTER_SHA256_MISMATCH")
    master = json.loads(raw.decode("utf-8-sig"))
    rows = master["OutBlock_1"]
    by_code = {str(r.get("ISU_CD", "")).strip(): r for r in rows if str(r.get("ISU_CD", "")).strip()}
    monthly_re = re.compile(r"(?:^|\s)(?:C|P)\s+(20\d{4})\s+([0-9][0-9,]*(?:\.[0-9]+)?)")
    weekly_re = re.compile(r"(?:^|\s)(?:C|P)\s+(\d{4}W\d)\s+([0-9][0-9,]*(?:\.[0-9]+)?)")
    n = 0; seq = 0; prev = None; first_ts = None; last_ts = None; bars = Counter(); classes = Counter(); day_events = {}
    for d in m["days"]:
        p = dataset / d["file"]
        if not p.is_file(): raise ValueError(f"MISSING_DAY_FILE:{d['date']}")
        local_n = 0; local_bars = Counter()
        for line_no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip(): continue
            rec = json.loads(line); t = rec["tick"]; ts = datetime.fromisoformat(t["timestamp"])
            if rec.get("schema") != m["schema"] or rec.get("provenance") != "DERIVED_SCENARIO":
                raise ValueError(f"SCHEMA_OR_PROVENANCE:{d['date']}:{line_no}")
            if ts.date().isoformat() != d["date"] or ts.time() < clock_time(8,45):
                raise ValueError(f"SESSION_DATE_OPEN:{t['timestamp']}")
            close = clock_time(15,20) if d["session_type"] == "MONTHLY_LAST_TRADING_DAY" else clock_time(15,45)
            if ts.time() >= close or ((ts.hour*60+ts.minute)-(8*60+45)) % 5 or ts.second or ts.microsecond:
                raise ValueError(f"SESSION_CLOSE_OR_5M_ALIGNMENT:{t['timestamp']}")
            if int(t["seq_id"]) != seq + 1: raise ValueError(f"SEQUENCE_GAP:{seq}:{t['seq_id']}")
            seq += 1
            if prev is not None and ts < prev: raise ValueError(f"TIMESTAMP_ORDER:{prev}:{ts}")
            prev = ts; first_ts = first_ts or ts; last_ts = ts
            code = str(t["instrument_id"]); r = by_code.get(code)
            if r is None: raise ValueError(f"OPTION_CODE_NOT_IN_MASTER:{code}")
            name = str(r.get("ISU_NM", "")); im = weekly_re.search(name) or monthly_re.search(name)
            if im is None or Decimal(im.group(2).replace(",", "")) != Decimal(str(t["strike_price"])):
                raise ValueError(f"MASTER_STRIKE_MISMATCH:{code}:{name}")
            if str(r.get("RGHT_TP_NM", "")).upper() != str(t["option_type"]).upper():
                raise ValueError(f"MASTER_OPTION_TYPE_MISMATCH:{code}")
            expiry = str(t["expiry"]); month = str(t["contract_month"])
            if not re.fullmatch(r"\d{8}", expiry) or month != expiry[:6]:
                raise ValueError(f"NONCANONICAL_EXPIRY_MONTH:{code}:{expiry}:{month}")
            if t["contract_class"] == "monthly":
                expected = str(m["monthly_expiries"].get(month, "")).replace("-", "")
            elif t["contract_class"] == "weekly" and weekly_re.search(name):
                series = weekly_re.search(name).group(1)
                expected = next((str(v).replace("-", "") for k,v in m.get("weekly_series_expiries",{}).items()
                                 if k == f"{str(r.get('PROD_NM','')).strip()}:{series}"), "")
            else:
                raise ValueError(f"CONTRACT_CLASS_INVALID:{code}:{t['contract_class']}")
            if expected != expiry: raise ValueError(f"MASTER_EXPIRY_MISMATCH:{code}:{expiry}:{expected}")
            if float(t["contract_multiplier"]) != 250000: raise ValueError(f"MULTIPLIER_INVALID:{code}")
            bid, ask = Decimal(str(t["bid_price"])), Decimal(str(t["ask_price"]))
            if bid <= 0 or ask <= bid: raise ValueError(f"BID_ASK_INVALID:{code}")
            expiry_dt = datetime.strptime(expiry, "%Y%m%d").replace(hour=15, minute=20)
            if int(t["time_to_expiry_seconds"]) != int((expiry_dt-ts).total_seconds()):
                raise ValueError(f"TIME_TO_EXPIRY_INVALID:{code}")
            if float(t["time_value"]) < -1e-8: raise ValueError(f"NEGATIVE_TIME_VALUE:{code}")
            local_n += 1; n += 1; local_bars[t["timestamp"]] += 1; classes[t["contract_class"]] += 1
        if local_n != int(d["events"]): raise ValueError(f"DAY_EVENT_COUNT:{d['date']}:{local_n}:{d['events']}")
        if any(v not in (10,14) for v in local_bars.values()): raise ValueError(f"BAR_SHAPE_INVALID:{d['date']}")
        day_events[d["date"]] = {"events":local_n, "bars":len(local_bars)}
        bars.update(local_bars.values())
    if n != int(m["events"]) or seq != n: raise ValueError(f"TOTAL_EVENT_COUNT:{n}:{seq}:{m['events']}")
    return {"status":"PASS","dataset":dataset.name,"manifest_sha256":hashlib.sha256((dataset/"manifest.json").read_bytes()).hexdigest(),
            "option_master_sha256":digest,"trading_days":len(day_events),"events":n,"bars":sum(x["bars"] for x in day_events.values()),
            "first_timestamp":first_ts.isoformat() if first_ts else None,"last_timestamp":last_ts.isoformat() if last_ts else None,"last_trading_day":m["days"][-1]["date"],
            "contract_class_counts":dict(classes),"bar_event_distribution":dict(bars),
            "monthly_rollovers":m["monthly_rollovers"],"weekly_rollovers":m["weekly_rollovers"],
            "market_rule_limitations":m.get("market_rule_limitations",[])}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--dataset",required=True); ap.add_argument("--port",type=int,default=18084)
    ap.add_argument("--report",required=True); ap.add_argument("--progress",required=True)
    a=ap.parse_args(); dataset=Path(a.dataset).resolve(); store=dataset/"control_tower_replay.jsonl"
    report=Path(a.report).resolve(); progress=Path(a.progress).resolve()
    out={"harness":Path(__file__).name,"dataset":str(dataset),"dataset_store":str(store),"initial_capital":10_000_000_000.0,"status":"RUNNING",
         "started_at":datetime.now().astimezone().isoformat()}
    try:
        audit=independent_data_audit(dataset); out["independent_data_audit"]=audit
    except Exception as e:
        out.update(status="FAIL",stage="independent_data_audit",error=str(e),traceback=traceback.format_exc())
        save(report,out); return 2
    save(progress,{"stage":"runtime_replay","events":0,"target":audit["events"]})
    import environments.high_speed.virtual_runtime_replay as replay_mod
    from environments.high_speed.replay_runner import HighSpeedReplayRunner
    captured={}; runner_ref={"runner":None}
    orig_bootstrap=replay_mod.create_virtual_runtime_bootstrap
    orig_attach=replay_mod.attach_standard_automated_loop
    orig_replay=HighSpeedReplayRunner.run
    def bootstrap_capture(*args,**kwargs):
        b=orig_bootstrap(*args,**kwargs); captured["bootstrap"]=b
        rr=runner_ref["runner"]
        if rr is not None and getattr(b,"run_context",None) is not None: rr.run_id=b.run_context.run_id
        return b
    def attach_capture(*args,**kwargs):
        x=orig_attach(*args,**kwargs); captured["loop"]=x; return x
    def replay_capture(self,*,start=None,end=None,speed=float("inf"),on_event=None,max_events=None):
        seen=0
        def event(t):
            nonlocal seen
            on_event(t); seen+=1
            if seen%2000==0: save(progress,{"stage":"runtime_replay","events":seen,"target":audit["events"],"timestamp":t.timestamp})
        rep=orig_replay(self,start=start,end=end,speed=speed,on_event=event,max_events=max_events)
        save(progress,{"stage":"runtime_replay_complete","events":seen,"target":audit["events"],"last_timestamp":rep.last_timestamp})
        return rep
    replay_mod.create_virtual_runtime_bootstrap=bootstrap_capture
    replay_mod.attach_standard_automated_loop=attach_capture
    HighSpeedReplayRunner.run=replay_capture
    rep=None
    try:
        runner=replay_mod.HighSpeedVirtualRuntimeReplayRunner(dataset,run_id=f"E2E-{datetime.now().strftime('%Y%m%d%H%M%S')}",initial_capital=10_000_000_000.0)
        runner_ref["runner"]=runner
        rep=runner.run()
        out["replay"]=asdict(rep); out["replay"]["strategy_status"]=[asdict(s) for s in rep.strategy_status]
        out["replay"]["strategy_signal_counts"]=dict(rep.strategy_signal_counts); out["replay"]["execution_ids"]=list(rep.execution_ids)
        out["status"]="REPLAY_COMPLETED"
    except Exception as e:
        out.update(status="FAIL",stage="runtime_replay",runtime_replay_error=str(e),runtime_replay_traceback=traceback.format_exc())
    finally:
        replay_mod.create_virtual_runtime_bootstrap=orig_bootstrap
        replay_mod.attach_standard_automated_loop=orig_attach
        HighSpeedReplayRunner.run=orig_replay
    b=captured.get("bootstrap")
    if b is None:
        out["control_tower"]={"status":"BLOCKED","reason":"RUNTIME_BOOTSTRAP_NOT_CAPTURED"}; save(report,out); return 3
    try:
        ctx=getattr(b,"run_context",None); active=getattr(getattr(b,"run_hub",None),"active",None)
        if ctx is not None:
            ctx=replace(ctx,historical_source="DERIVED_SCENARIO",historical_store_path=str(store))
            if active is not None: active.context=ctx
        vssf=b.bundle.execution._authoritative_execute.__self__.vssf_runtime
        broker=b.bundle.broker_api; acct=vssf.account
        def cv(x): return asdict(x) if is_dataclass(x) else x
        groups=list(broker.get_group_ids())
        position_pnl={"account_snapshot":cv(broker.get_account_snapshot()),"position_snapshot":cv(broker.get_position_snapshot()),
          "pnl_snapshot":cv(broker.get_pnl_state()),"margin_snapshot":cv(broker.get_margin_state()),
          "open_position_symbols":list(getattr(acct,"positions",{}).keys()),"open_position_count":len(getattr(acct,"positions",{})),
          "account_realized_pnl":float(getattr(acct,"realized_pnl",0)),"account_unrealized_pnl":float(getattr(acct,"unrealized_pnl",0)),
          "group_ids":groups,"group_reports":{}}
        for gid in groups:
            try: position_pnl["group_reports"][gid]=[cv(x) for x in broker.get_group_reports(gid)]
            except Exception as e: position_pnl["group_reports"][gid]={"error":str(e)}
        out["virtual_broker_position_pnl"]=position_pnl
        if rep is not None:
            out["pipeline_counts"]={"events":rep.events,"signals":rep.signals,"approved":rep.approved,"routed":rep.routed,
             "filled":rep.filled,"rejected":rep.rejected,"execution_ids":len(rep.execution_ids),
             "strategies_reported":len(rep.strategy_status),"strategies_with_reaction_signals":sum(bool(x.reaction_signals) for x in rep.strategy_status),
             "strategies_with_execution_signals":sum(bool(x.execution_signals) for x in rep.strategy_status),
             "strategies_with_runtime_failures":sum(bool(x.runtime_failures) for x in rep.strategy_status),
             "strategies_with_unavailable":sum(bool(x.unavailable) for x in rep.strategy_status)}
        import interfaces.control_tower.server as ct
        ct.ControlTowerRequestHandler.tower=b.control_tower_hub
        ct.ControlTowerRequestHandler.adapter=b.ui_adapter
        server=ThreadingHTTPServer(("127.0.0.1",a.port),ct.ControlTowerRequestHandler); server.daemon_threads=True
        threading.Thread(target=server.serve_forever,name="fresh-e2e-control-tower",daemon=True).start()
        base=f"http://127.0.0.1:{a.port}"; api={}
        for endpoint in ("/api/status","/api/strategies","/api/run","/api/scenarios"):
            deadline=time.time()+30; last=None
            while time.time()<deadline:
                try:
                    with urlopen(base+endpoint,timeout=3) as r: api[endpoint]={"http_status":r.status,"body":json.loads(r.read().decode("utf-8"))}
                    break
                except Exception as e: last=str(e); time.sleep(.25)
            else: raise RuntimeError(f"CONTROL_TOWER_API_NOT_READY:{endpoint}:{last}")
        run=api["/api/run"]["body"]; strategies=api["/api/strategies"]["body"].get("strategies",[])
        checks={"active":run.get("active") is True,"run_id_matches":bool(rep and run.get("run_id")==rep.run_id),
          "dataset_path_matches":run.get("historical_store_path")==str(store),
          "last_tick_matches":bool(rep and (run.get("last_replay_tick") or {}).get("timestamp")==out["independent_data_audit"]["last_timestamp"]),
          "strategy_count":len(strategies),"account_present":isinstance(run.get("account"),dict),
          "position_present":isinstance(run.get("position"),dict),"pnl_present":isinstance(run.get("pnl"),dict),
          "execution_report_count":len(run.get("execution_reports",[]))}
        checks["status"]="PASS" if all([checks["active"],checks["dataset_path_matches"],checks["last_tick_matches"],checks["strategy_count"]==9,
            checks["account_present"],checks["position_present"],checks["pnl_present"]]) else "FAIL"
        out["control_tower"]={"base_url":base,"same_bootstrap_as_replay":True,"same_run_context":True,"api":api,
           "checks":checks,"browser_dom_smoke":"PENDING_PLAYWRIGHT","server_pid":os.getpid()}
        out["finished_at"]=datetime.now().astimezone().isoformat(); save(report,out)
        save(progress,{"stage":"control_tower_ready","events":out.get("pipeline_counts",{}).get("events",0),"target":audit["events"],"url":base,"report":str(report)})
        print(json.dumps({"status":out["status"],"url":base,"report":str(report),"pipeline_counts":out.get("pipeline_counts"),"control_tower_checks":checks},ensure_ascii=False),flush=True)
        while True: time.sleep(1)
    except Exception as e:
        out.update(status="FAIL",stage="control_tower",control_tower_error=str(e),traceback=traceback.format_exc())
        save(report,out); save(progress,{"stage":"control_tower_failed","error":str(e),"report":str(report)}); return 4

if __name__=="__main__": raise SystemExit(main())
