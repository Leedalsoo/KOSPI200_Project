"""Application read model for the Control Tower Option Program view.

The builder projects observable Runtime/Strategy/Broker state into a UI-neutral
read model. It does not execute strategy logic or create orders.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


class OptionProgramReadModel:
    """Build the authoritative, read-only Option Program projection."""

    def __init__(self, *, runtime_controller: Any, runtime_hub: Any, strategy_hub: Any, bundle: Any, context: Any) -> None:
        self._runtime_controller = runtime_controller
        self._runtime_hub = runtime_hub
        self._strategy_hub = strategy_hub
        self._bundle = bundle
        self._context = context

    @staticmethod
    def _asdict(value: Any) -> Any:
        return asdict(value) if is_dataclass(value) else value

    def _strategy_rows(self) -> list[dict[str, Any]]:
        statuses = {
            item.strategy_id: item
            for item in getattr(self._runtime_hub, "last_strategy_status", ())
        }
        rows: list[dict[str, Any]] = []
        for key in tuple(getattr(self._strategy_hub, "strategy_keys", ())):
            strategy_id, version = (
                (key[0], key[1]) if isinstance(key, tuple)
                else (key.strategy_id, key.version)
            )
            status = statuses.get(strategy_id)
            status_dict = self._asdict(status) if status is not None else {}
            runtime_failures = int(status_dict.get("runtime_failures", 0) or 0)
            unavailable = int(status_dict.get("unavailable", 0) or 0)
            signals = int(status_dict.get("reaction_signals", 0) or 0)
            approved = int(status_dict.get("approved", 0) or 0)
            routed = int(status_dict.get("routed", 0) or 0)
            filled = int(status_dict.get("filled_quantity", 0) or 0)
            if runtime_failures:
                observation_state = "RUNTIME_BLOCKED"
            elif unavailable:
                observation_state = "INPUT_UNAVAILABLE"
            elif filled:
                observation_state = "EXECUTION_OBSERVED"
            elif routed or approved:
                observation_state = "DECISION_OR_ROUTING_OBSERVED"
            elif signals:
                observation_state = "SIGNAL_OBSERVED"
            else:
                observation_state = "NO_SIGNAL_OBSERVED"
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "version": version,
                    "enabled": bool(self._strategy_hub.is_enabled(strategy_id, version)),
                    "status": status_dict if status is not None else None,
                    "observation_state": observation_state,
                    "source_status": "REAL_VTS_SOURCE_SELECTED" if (getattr(self._context, "historical_source", None) or "").startswith("kis_vts") else "SOURCE_UNSPECIFIED",
                    "runtime_input_status": "BLOCKED" if (runtime_failures or unavailable) else "AVAILABLE",
                    "signal_status": "SIGNAL_OBSERVED" if signals else "NO_SIGNAL_OBSERVED",
                    "full_e2e_status": "NOT_CLAIMED",
                    "verification_scope": "RUN_OBSERVATION_ONLY",
                }
            )
        return rows

    def _strategy_graphs(self, broker_api: Any, option_master: Any) -> list[dict[str, Any]]:
        """Project authoritative executed BUY/SELL leg values for UI-only composition graphs.

        This deliberately exposes trade-side/value identity only. It does not calculate
        payoff, PnL, BEP, or any synthetic price curve.
        """
        if broker_api is None:
            return []

        try:
            group_ids = tuple(broker_api.get_group_ids())
            position_snapshot = broker_api.get_position_snapshot()
            positions = getattr(position_snapshot, "positions", {}) if position_snapshot is not None else {}
        except Exception:
            return []

        grouped: dict[str, list[dict[str, Any]]] = {}
        pnl_by_strategy: dict[str, list[float]] = {}
        for group_id in group_ids:
            try:
                snap = broker_api.get_group_position_snapshot(group_id)
            except Exception:
                continue
            strategy_id = str(getattr(snap, "strategy_id", "") or "")
            if not strategy_id:
                continue
            rows = grouped.setdefault(strategy_id, [])
            realized = getattr(snap, "realized_pnl", None)
            unrealized = getattr(snap, "unrealized_pnl", None)
            if realized is not None or unrealized is not None:
                current = pnl_by_strategy.setdefault(strategy_id, [0.0, 0.0])
                if realized is not None:
                    current[0] += float(realized)
                if unrealized is not None:
                    current[1] += float(unrealized)
            for leg in getattr(snap, "legs", ()):
                instrument_id = str(getattr(leg, "instrument_id", "") or "")
                pos = positions.get(instrument_id) if hasattr(positions, "get") else None
                side = str(getattr(pos, "side", "") or "").upper() if pos is not None else ""
                if side not in {"BUY", "SELL"}:
                    side = "UNKNOWN"
                trade_price = getattr(leg, "avg_price", None)
                if trade_price is None and pos is not None:
                    trade_price = getattr(pos, "avg_price", None)

                identity = None
                if option_master is not None and hasattr(option_master, "get_contract_identity") and instrument_id:
                    try:
                        identity = option_master.get_contract_identity(instrument_id)
                    except Exception:
                        identity = None

                rows.append({
                    "group_id": str(getattr(leg, "group_id", group_id)),
                    "leg_id": str(getattr(leg, "leg_id", "")),
                    "instrument_id": instrument_id,
                    "side": side,
                    "quantity": int(getattr(leg, "quantity", 0) or 0),
                    "trade_price": float(trade_price) if trade_price is not None else None,
                    "asset_type": "OPTION" if identity is not None else "UNKNOWN",
                    "expiry": getattr(identity, "expiry", None) if identity is not None else None,
                    "option_type": getattr(identity, "option_type", None) if identity is not None else None,
                    "strike": float(identity.strike) if identity is not None and getattr(identity, "strike", None) is not None else None,
                    "identity_source": getattr(identity, "identity_source", None) if identity is not None else getattr(leg, "identity_source", None),
                })

        rows: list[dict[str, Any]] = []
        for strategy_id, legs in sorted(grouped.items()):
            rows.append({
                "strategy_id": strategy_id,
                "legs": legs,
                "data_status": "AVAILABLE" if legs else "UNAVAILABLE",
                "realized_pnl": (pnl_by_strategy.get(strategy_id) or [None, None])[0],
                "unrealized_pnl": (pnl_by_strategy.get(strategy_id) or [None, None])[1],
                "net_pnl": (
                    sum(pnl_by_strategy[strategy_id])
                    if strategy_id in pnl_by_strategy else None
                ),
            })
        return rows

    def build(self) -> dict[str, Any]:
        runtime_status = self._runtime_controller.status()
        runtime_state = getattr(runtime_status, "state", "STOPPED")
        tick = getattr(self._bundle.market, "last_tick", None)
        result = getattr(self._runtime_hub, "last_result", None)

        market_input = None
        if tick is not None:
            market_input = {
                "timestamp": tick.timestamp,
                "seq_id": tick.seq_id,
                "symbol": tick.symbol,
                "expiry": tick.expiry,
                "strike": tick.strike_price,
                "option_type": tick.option_type,
                "bid": tick.bid_price,
                "ask": tick.ask_price,
                "last": tick.last_price,
                "underlying_price": tick.underlying_price,
                "volume": tick.volume,
            }

        last_result = self._asdict(result) if result is not None else None
        account = position = margin = pnl = None
        execution_reports: list[Any] = []
        broker_api = getattr(self._bundle, "broker_api", None)
        if broker_api is not None:
            readers = (
                ("account", "get_account_snapshot"),
                ("position", "get_position_snapshot"),
                ("margin", "get_margin_state"),
                ("pnl", "get_pnl_state"),
            )
            for name, method_name in readers:
                try:
                    value = getattr(broker_api, method_name)()
                    if name == "account" and hasattr(value, "balances"):
                        account = {
                            "as_of": value.as_of.isoformat() if value.as_of else None,
                            "balances": {key: str(val) for key, val in value.balances.items()},
                            "freshness": str(value.freshness),
                        }
                    elif name == "account":
                        account = self._asdict(value)
                    elif name == "position":
                        position = self._asdict(value)
                    elif name == "margin":
                        margin = self._asdict(value)
                    elif name == "pnl":
                        pnl = self._asdict(value)
                except Exception as exc:
                    error_value = {"status": "UNAVAILABLE", "reason": str(exc)}
                    if name == "account":
                        account = error_value
                    elif name == "position":
                        position = error_value
                    elif name == "margin":
                        margin = error_value
                    elif name == "pnl":
                        pnl = error_value
            try:
                group_ids = broker_api.get_group_ids()
                if group_ids:
                    execution_reports = [
                        self._asdict(item)
                        for item in broker_api.get_group_reports(next(iter(group_ids), ""))
                    ]
            except Exception:
                execution_reports = []

        status_rows = [
            self._asdict(item)
            for item in getattr(self._runtime_hub, "last_strategy_status", ())
        ]
        strategy_graphs = self._strategy_graphs(
            broker_api,
            getattr(self._bundle, "option_master", None),
        )

        unavailable: list[str] = []
        if market_input is None:
            unavailable.append("market_input")
        if result is None:
            unavailable.append("signal_decision_risk_order_execution")
        if result is not None:
            unavailable.extend(
                [
                    "per_strategy_signal_detail",
                    "decision_reason_detail",
                    "risk_reason_detail",
                    "order_command_detail",
                ]
            )
        if not status_rows:
            unavailable.append("strategy_runtime_status")

        return {
            "tab_id": "option_program",
            "tab_name": "Option Program",
            "run_id": getattr(self._context, "run_id", None),
            "runtime_state": runtime_state,
            "environment": getattr(self._context, "environment", None),
            "scenario": getattr(self._context, "scenario", None),
            "historical_source": getattr(self._context, "historical_source", None),
            "historical_store_path": getattr(self._context, "historical_store_path", None),
            "verification": {
                "scope": "RUN_OBSERVATION_ONLY",
                "full_e2e_status": "NOT_CLAIMED",
                "source": getattr(self._context, "historical_source", None) or "UNSPECIFIED",
                "reason": "UI observes the current runtime; missing authoritative inputs or absent REAL_VTS signals remain visible and are not promoted to E2E PASS.",
            },
            "market_input": market_input,
            "strategies": self._strategy_rows(),
            "strategy_graphs": strategy_graphs,
            "last_result": last_result,
            "strategy_status": status_rows,
            "account": account,
            "position": position,
            "margin": margin,
            "pnl": pnl,
            "execution_reports": execution_reports,
            "flow": {
                "market_input": "AVAILABLE" if market_input is not None else "UNAVAILABLE",
                "strategy": "AVAILABLE" if self._strategy_rows() else "UNAVAILABLE",
                "signal": None if result is None else getattr(result, "signals", 0),
                "decision_approved": None if result is None else getattr(result, "approved", 0),
                "risk_or_router_rejected": None if result is None else getattr(result, "rejected", 0),
                "order_routed": None if result is None else getattr(result, "routed", 0),
                "execution_filled": None if result is None else getattr(result, "filled", 0),
                "position_pnl": "AVAILABLE" if position is not None and pnl is not None else "UNAVAILABLE",
            },
            "unavailable_sections": unavailable,
            "audit_logs": [],
        }
