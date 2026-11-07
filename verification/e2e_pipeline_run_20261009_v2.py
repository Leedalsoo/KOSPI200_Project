import argparse, hashlib, json, os, re, sys, threading, time, traceback
from collections import Counter
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, time as dtime
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

def dump(path, data):
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

def audit_dataset(dataset):
    manifest=json.loads((dataset/"manifest.json").read_text(encoding="utf-8"))
    master_path=ROOT/manifest["option_master_path"]
    master_raw=master_path.read_bytes()
    master_hash=hashlib.sha256(master_raw).hexdigest()
    if master_hash != manifest["option_master_sha256"]: raise ValueError("OPTION_MASTER_HASH_MISMATCH")
    master=json.loads(master_raw.decode("utf-8-sig"))
    by_code={str(x.get("ISU_CD","")).strip():x for x in master["OutBlock_1"] if str(x.get("ISU_CD","")).strip()}
    month_re=re.compile(r"(?:^|\s)(?:C|P)\s+(20\d{4})\s+([0-9][0-9,]*(?:\.[0-9]+)?)")
    week_re=re.compile(r"(?:^|\s)(?:C|P)\s+(\d{4}W\d)\s+([0-9][0-9,]*(?:\.[0-9]+)?)")
    total=0; seq=0; previous=None; first=None; last=None; classes=Counter(); bars=Counter(); daily={}
    for day in manifest["days"]:
        file=dataset/day["file"]
        if not file.is_file(): raise ValueError(f"DAY_FILE_MISSING:{day['date']}")
        day_count=0; day_bars=Counter()
        for line_no,line in enumerate(file.read_text(encoding="utf-8").splitlines(),1):
            if not line.strip(): continue
            rec=json.loads(line); tick=rec["tick"]; stamp=datetime.fromisoformat(tick["timestamp"])
            if rec.get("schema") != manifest["schema"] or rec.get("provenance") != "DERIVED_SCENARIO": raise ValueError(f"SCHEMA_PROVENANCE:{day['date']}:{line_no}")
            if stamp.date().isoformat()!=day["date"] or stamp.time()<dtime(8,45): raise ValueError(f"SESSION_START_DATE:{tick['timestamp']}")
            close=dtime(15,20) if day["session_type"]=="MONTHLY_LAST_TRADING_DAY" else dtime(15,45)
            offset=stamp.hour*60+stamp.minute-(8*60+45)
            if stamp.time()>=close or offset<0 or offset%5 or stamp.second or stamp.microsecond: raise ValueError(f"SESSION_5M_RULE:{tick['timestamp']}")
            if int(tick["seq_id"])!=seq+1: raise ValueError(f"SEQUENCE:{seq}:{tick['seq_id']}")
            seq+=1
            if previous and stamp<previous: raise ValueError(f"TIMESTAMP_ORDER:{previous}:{stamp}")
            previous=stamp; first=first or stamp; last=stamp
            code=str(tick["instrument_id"]); row=by_code.get(code)
            if row is None: raise ValueError(f"UNKNOWN_OPTION_MASTER_CODE:{code}")
            name=str(row.get("ISU_NM","")); match=week_re.search(name) or month_re.search(name)
            if match is None or Decimal(match.group(2).replace(",","")) != Decimal(str(tick["strike_price"])): raise ValueError(f"MASTER_STRIKE:{code}")
            if str(row.get("RGHT_TP_NM","")).upper()!=str(tick["option_type"]).upper(): raise ValueError(f"MASTER_TYPE:{code}")
            expiry=str(tick["expiry"]); month=str(tick["contract_month"])
            if not re.fullmatch(r"\d{8}",expiry) or month!=expiry[:6]: raise ValueError(f"EXACT_EXPIRY:{code}:{expiry}:{month}")
            if tick["contract_class"]=="monthly": expected=str(manifest["monthly_expiries"].get(month,"")).replace("-","")
            elif tick["contract_class"]=="weekly" and week_re.search(name):
                series=week_re.search(name).group(1); product=str(row.get("PROD_NM","")).strip()
                expected=next((str(v).replace("-","") for k,v in manifest.get("weekly_series_expiries",{}).items() if k==f"{product}:{series}"),"")
            else: raise ValueError(f"CONTRACT_CLASS:{code}")
            if expected!=expiry: raise ValueError(f"MASTER_EXPIRY:{code}:{expiry}:{expected}")
            if float(tick["contract_multiplier"])!=250000: raise ValueError(f"MULTIPLIER:{code}")
            bid=Decimal(str(tick["bid_price"])); ask=Decimal(str(tick["ask_price"]))
            if bid<=0 or ask<=bid: raise ValueError(f"BID_ASK:{code}")
            tte=int((datetime.strptime(expiry,"%Y%m%d").replace(hour=15,minute=20)-stamp).total_seconds())
            if int(tick["time_to_expiry_seconds"])!=tte or float(tick["time_value"]) < -1e-8: raise ValueError(f"TIME_VALUE_TTE:{code}")
            day_count+=1; total+=1; classes[str(tick["contract_class"])]+=1; day_bars[tick["timestamp"]]+=1
        if day_count!=int(day["events"]): raise ValueError(f"DAY_EVENT_COUNT:{day['date']}:{day_count}:{day['events']}")
        if any(count not in (10,14) for count in day_bars.values()): raise ValueError(f"BAR_SHAPE:{day['date']}")
        daily[day["date"]]={"events":day_count,"bars":len(day_bars)}; bars.update(day_bars.values())
    if total!=int(manifest["events"]) or seq!=total: raise ValueError(f"TOTAL_EVENT_COUNT:{total}:{seq}:{manifest['events']}")
    return {"status":"PASS","dataset":dataset.name,"manifest_sha256":hashlib.sha256((dataset/"manifest.json").read_bytes()).hexdigest(),
      "option_master_sha256":master_hash,"trading_days":len(daily),"events":total,"bars":sum(x["bars"] for x in daily.values()),
      "first_timestamp":first.isoformat() if first else None,"last_timestamp":last.isoformat() if last else None,
      "contract_class_counts":dict(classes),"bar_event_distribution":dict(bars),"monthly_rollovers":manifest["monthly_rollovers"],
      "weekly_rollovers":manifest["weekly_rollovers"],"market_rule_limitations":manifest.get("market_rule_limitations",[])}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--dataset",required=True); parser.add_argument("--port",type=int,default=18085)
    parser.add_argument("--report",required=True); parser.add_argument("--progress",required=True)
    args=parser.parse_args(); dataset=Path(args.dataset).resolve(); store=dataset/"control_tower_replay.jsonl"
    report=Path(args.report).resolve(); progress=Path(args.progress).resolve()
    output={"harness":Path(__file__).name,"dataset":str(dataset),"dataset_store":str(store),"initial_capital":10_000_000_000.0,
      "status":"RUNNING","started_at":datetime.now().astimezone().isoformat()}
    try: audit=audit_dataset(dataset); output["independent_data_audit"]=audit
    except Exception as exc:
      output.update(status="FAIL",stage="data_audit",error=str(exc),traceback=traceback.format_exc()); dump(report,output); return 2
    dump(progress,{"stage":"runtime_replay","events":0,"target":audit["events"]})
    import environments.high_speed.virtual_runtime_replay as replay_mod
    from environments.high_speed.replay_runner import HighSpeedReplayRunner
    captured={}; holder={"runner":None}
    old_bootstrap=replay_mod.create_virtual_runtime_bootstrap
    old_attach=replay_mod.attach_standard_automated_loop
    old_replay=HighSpeedReplayRunner.run
    def capture_bootstrap(*args,**kwargs):
      boot=old_bootstrap(*args,**kwargs); captured["bootstrap"]=boot
      if holder["runner"] is not None and getattr(boot,"run_context",None) is not None: holder["runner"].run_id=boot.run_context.run_id
      return boot
    def capture_attach(*args,**kwargs):
      loop=old_attach(*args,**kwargs); captured["loop"]=loop; return loop
    def capture_replay(self,*,start=None,end=None,speed=float("inf"),on_event=None,max_events=None):
      seen=0
      def observe(tick):
        nonlocal seen
        on_event(tick); seen+=1
        if seen%2000==0: dump(progress,{"stage":"runtime_replay","events":seen,"target":audit["events"],"timestamp":tick.timestamp})
      report_obj=old_replay(self,start=start,end=end,speed=speed,on_event=observe,max_events=max_events)
      dump(progress,{"stage":"runtime_replay_complete","events":seen,"target":audit["events"],"last_timestamp":report_obj.last_timestamp})
      return report_obj
    replay_mod.create_virtual_runtime_bootstrap=capture_bootstrap
    replay_mod.attach_standard_automated_loop=capture_attach
    HighSpeedReplayRunner.run=capture_replay
    replay=None
    try:
      runner=replay_mod.HighSpeedVirtualRuntimeReplayRunner(dataset,run_id=f"E2E-{datetime.now().strftime('%Y%m%d%H%M%S')}",initial_capital=10_000_000_000.0)
      holder["runner"]=runner
      replay=runner.run()
      output["replay"]=asdict(replay)
      output["replay"]["strategy_status"]=[asdict(s) for s in replay.strategy_status]
      output["replay"]["strategy_signal_counts"]=dict(replay.strategy_signal_counts)
      output["replay"]["execution_ids"]=list(replay.execution_ids)
      output["status"]="REPLAY_COMPLETED"
    except Exception as exc:
      output.update(status="FAIL",stage="runtime_replay",runtime_replay_error=str(exc),runtime_replay_traceback=traceback.format_exc())
    finally:
      replay_mod.create_virtual_runtime_bootstrap=old_bootstrap
      replay_mod.attach_standard_automated_loop=old_attach
      HighSpeedReplayRunner.run=old_replay
    boot=captured.get("bootstrap")
    if boot is None:
      output["control_tower"]={"status":"BLOCKED","reason":"BOOTSTRAP_NOT_CAPTURED"}; dump(report,output); return 3
    try:
      active=getattr(getattr(boot,"run_hub",None),"active",None)
      if active is not None:
        active.context=replace(active.context,historical_source="DERIVED_SCENARIO",historical_store_path=str(store))
      vssf=boot.bundle.execution._authoritative_execute.__self__.vssf_runtime
      broker=boot.bundle.broker_api
      def convert(x): return asdict(x) if is_dataclass(x) else x
      group_ids=list(broker.get_group_ids())
      account=vssf.account
      groups={}
      for gid in group_ids:
        try: groups[gid]=[convert(x) for x in broker.get_group_reports(gid)]
        except Exception as exc: groups[gid]={"error":str(exc)}
      output["virtual_broker_position_pnl"]={"account_snapshot":convert(broker.get_account_snapshot()),
        "position_snapshot":convert(broker.get_position_snapshot()),"pnl_snapshot":convert(broker.get_pnl_state()),
        "margin_snapshot":convert(broker.get_margin_state()),"open_position_symbols":list(account.positions.keys()),
        "open_position_count":len(account.positions),"account_realized_pnl":float(account.realized_pnl),
        "account_unrealized_pnl":float(account.unrealized_pnl),"group_ids":group_ids,"group_reports":groups}
      if replay is not None:
        output["pipeline_counts"]={"events":replay.events,"signals":replay.signals,"approved":replay.approved,"routed":replay.routed,
          "filled":replay.filled,"rejected":replay.rejected,"execution_ids":len(replay.execution_ids),
          "strategies_reported":len(replay.strategy_status),"strategies_with_reaction_signals":sum(bool(s.reaction_signals) for s in replay.strategy_status),
          "strategies_with_execution_signals":sum(bool(s.execution_signals) for s in replay.strategy_status),
          "strategies_with_runtime_failures":sum(bool(s.runtime_failures) for s in replay.strategy_status),
          "strategies_with_unavailable":sum(bool(s.unavailable) for s in replay.strategy_status)}
      import interfaces.control_tower.server as ct
      ct.ControlTowerRequestHandler.tower=boot.control_tower_hub
      ct.ControlTowerRequestHandler.adapter=boot.ui_adapter
      server=ThreadingHTTPServer(("127.0.0.1",args.port),ct.ControlTowerRequestHandler); server.daemon_threads=True
      threading.Thread(target=server.serve_forever,name="e2e-v2-control-tower",daemon=True).start()
      base=f"http://127.0.0.1:{args.port}"; api={}
      for endpoint in ("/api/status","/api/strategies","/api/run","/api/scenarios"):
        deadline=time.time()+30; last_error=None
        while time.time()<deadline:
          try:
            with urlopen(base+endpoint,timeout=3) as response: api[endpoint]={"http_status":response.status,"body":json.loads(response.read().decode("utf-8"))}
            break
          except Exception as exc: last_error=str(exc); time.sleep(.25)
        else: raise RuntimeError(f"CONTROL_TOWER_API_NOT_READY:{endpoint}:{last_error}")
      run=api["/api/run"]["body"]; strategy_rows=api["/api/strategies"]["body"].get("strategies",[])
      checks={"active":run.get("active") is True,"run_id_matches":bool(replay and run.get("run_id")==replay.run_id),
        "dataset_path_matches":run.get("historical_store_path")==str(store),
        "last_tick_matches":bool(replay and (run.get("last_replay_tick") or {}).get("timestamp")==audit["last_timestamp"]),
        "strategy_count":len(strategy_rows),"account_present":isinstance(run.get("account"),dict),
        "position_present":isinstance(run.get("position"),dict),"pnl_present":isinstance(run.get("pnl"),dict),
        "execution_report_count":len(run.get("execution_reports",[]))}
      checks["status"]="PASS" if all([checks["active"],checks["run_id_matches"],checks["dataset_path_matches"],checks["last_tick_matches"],
        checks["strategy_count"]==9,checks["account_present"],checks["position_present"],checks["pnl_present"]]) else "FAIL"
      output["control_tower"]={"base_url":base,"same_bootstrap_as_replay":True,"same_run_context":True,"api":api,
        "checks":checks,"browser_dom_smoke":"PENDING_PLAYWRIGHT","server_pid":os.getpid()}
      if replay is not None and checks["status"]=="PASS" and replay.events==audit["events"] and replay.filled>0:
        output["status"]="PASS_WITH_LIMITATION" if audit["market_rule_limitations"] or output["pipeline_counts"]["strategies_with_unavailable"] else "PASS"
      else: output["status"]="FAIL"
      output["finished_at"]=datetime.now().astimezone().isoformat(); dump(report,output)
      dump(progress,{"stage":"control_tower_ready","events":output.get("pipeline_counts",{}).get("events",0),"target":audit["events"],"url":base,"report":str(report)})
      print(json.dumps({"status":output["status"],"url":base,"report":str(report),"pipeline_counts":output.get("pipeline_counts"),"checks":checks},ensure_ascii=False),flush=True)
      while True: time.sleep(1)
    except Exception as exc:
      output.update(status="FAIL",stage="control_tower",control_tower_error=str(exc),control_tower_traceback=traceback.format_exc())
      dump(report,output); dump(progress,{"stage":"control_tower_failed","error":str(exc),"report":str(report)}); return 4

if __name__=="__main__": raise SystemExit(main())
