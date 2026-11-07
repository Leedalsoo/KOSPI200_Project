import sys, threading, time, json
from pathlib import Path
sys.path.insert(0, r"C:\Users\white\Desktop\MovingProject\KOSPI200_Project")

from application.bootstrap import create_virtual_runtime_bootstrap
from application.run_hub.contracts import RunContext
from application.run_hub.virtual_session_factory import create_virtual_run_session
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from interfaces.control_tower import server as ct_server
from http.server import HTTPServer

ROOT=Path(r"C:\Users\white\Desktop\MovingProject\KOSPI200_Project")
DATA=ROOT/"verification/results/real_vts_3m_e2e_20261008/control_tower_canonical_probe.jsonl"
RUN_ID="REALVTS-3M-E2E-20261008-FINAL-SAME-RUN-PROBE"
PORT=8092

bootstrap=create_virtual_runtime_bootstrap()
ctx=RunContext(
    run_id=RUN_ID,
    environment="VIRTUAL",
    historical_source="kis_vts_rest",
    historical_store_path=str(DATA),
    strategy_keys=bootstrap.strategy_hub._keys,
    initial_capital=250_000_000.0,
)
session=create_virtual_run_session(ctx, bootstrap.bundle.option_master)

# Bind the existing HTTP handler to THIS exact session.
ct_server.ControlTowerRequestHandler.tower=session.control_tower_hub
ct_server.ControlTowerRequestHandler.adapter=session.ui_adapter
httpd=HTTPServer(("127.0.0.1",PORT), ct_server.ControlTowerRequestHandler)
threading.Thread(target=httpd.serve_forever,daemon=True).start()

store=HistoricalMarketStore(DATA)
ticks=store.load_ticks()
count=0
for tick in ticks:
    session.runtime_hub.on_tick(tick)
    count += 1
    if count >= 500:
        break

print(json.dumps({
    "run_id":RUN_ID,
    "port":PORT,
    "ticks_processed":count,
    "runtime_last_result":str(session.runtime_hub.last_result),
    "strategy_status_keys": str(session.runtime_hub.last_strategy_status),
}, ensure_ascii=False))
while True:
    time.sleep(1)






