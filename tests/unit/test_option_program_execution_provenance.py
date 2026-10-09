from types import SimpleNamespace

from application.option_program_read_model import OptionProgramReadModel


RUN_ID = "RUN-20261009-CHAIN"


class FakeBrokerApi:
    def __init__(self, snapshots, groups, reports):
        self.snapshots = snapshots
        self.groups = groups
        self.reports = reports

    def get_group_ids(self):
        return tuple(self.snapshots)

    def get_position_snapshot(self):
        return SimpleNamespace(positions={})

    def get_group_position_snapshot(self, group_id):
        return self.snapshots[group_id]

    def get_position_group(self, group_id):
        return self.groups[group_id]

    def get_group_reports(self, group_id):
        return tuple(self.reports[group_id])


def _leg(leg_id, instrument_id, side, execution_id):
    return SimpleNamespace(
        leg_id=leg_id, group_id="RUN-20261009-CHAIN-GROUP",
        instrument_id=instrument_id, quantity=1, contract_multiplier=250000,
        identity_source="OPTION_MASTER", avg_price=12.5, current_price=13.0,
        unrealized_pnl=125000.0, run_id=RUN_ID,
        client_order_id=f"{RUN_ID}-{leg_id}", execution_id=execution_id,
    )


def _report(leg_id, execution_id):
    return SimpleNamespace(
        leg_id=leg_id, group_id="RUN-20261009-CHAIN-GROUP",
        client_order_id=f"{RUN_ID}-{leg_id}", broker_order_id=f"BROKER-{execution_id}",
        execution_id=execution_id, status="FILLED", filled_quantity=1,
        execution_price=12.5, execution_timestamp=None,
    )


def _model(broker):
    model = object.__new__(OptionProgramReadModel)
    model._context = SimpleNamespace(run_id=RUN_ID, historical_source="kis_vts_rest")
    return model


def test_option_program_trade_pnl_exposes_same_run_execution_provenance_and_sides():
    put = _leg("put", "PUT-ID", "SELL", "EXEC-PUT")
    call = _leg("call", "CALL-ID", "BUY", "EXEC-CALL")
    group_snapshot = SimpleNamespace(
        group_id="RUN-20261009-CHAIN-GROUP", strategy_id="track9_event_overnight_insurance",
        complete=True, legs=(put, call), realized_pnl=0.0,
        unrealized_pnl=250000.0, total_pnl=250000.0,
    )
    group = SimpleNamespace(legs=(
        SimpleNamespace(leg_id="put", side="SELL"),
        SimpleNamespace(leg_id="call", side="BUY"),
    ))
    reports = [_report("put", "EXEC-PUT"), _report("call", "EXEC-CALL")]
    broker = FakeBrokerApi(
        {group_snapshot.group_id: group_snapshot},
        {group_snapshot.group_id: group},
        {group_snapshot.group_id: reports},
    )
    graph = _model(broker)._strategy_graphs(broker, option_master=None)
    assert len(graph) == 1
    assert {leg["leg_id"]: leg["side"] for leg in graph[0]["legs"]} == {
        "put": "SELL", "call": "BUY",
    }
    trade = graph[0]["trades"][0]
    assert trade["run_id"] == RUN_ID
    assert trade["provenance_status"] == "AVAILABLE"
    assert set(trade["execution_ids"]) == {"EXEC-PUT", "EXEC-CALL"}
    assert set(trade["report_execution_ids"]) == {"EXEC-PUT", "EXEC-CALL"}
    assert set(trade["client_order_ids"]) == {f"{RUN_ID}-put", f"{RUN_ID}-call"}
    assert trade["pnl_source"] == "AUTHORITATIVE_GROUP_POSITION_SNAPSHOT"


def test_option_program_trade_pnl_blocks_when_snapshot_run_id_differs():
    put = _leg("put", "PUT-ID", "SELL", "EXEC-PUT")
    put.run_id = "OLD-RUN"
    group_snapshot = SimpleNamespace(
        group_id="RUN-20261009-CHAIN-GROUP", strategy_id="track9_event_overnight_insurance",
        complete=False, legs=(put,), realized_pnl=0.0,
        unrealized_pnl=1.0, total_pnl=1.0,
    )
    group = SimpleNamespace(legs=(SimpleNamespace(leg_id="put", side="SELL"),))
    broker = FakeBrokerApi(
        {group_snapshot.group_id: group_snapshot},
        {group_snapshot.group_id: group},
        {group_snapshot.group_id: [_report("put", "EXEC-PUT")]},
    )
    graph = _model(broker)._strategy_graphs(broker, option_master=None)
    assert graph[0]["trades"][0]["provenance_status"] == "RUN_ID_MISMATCH"
