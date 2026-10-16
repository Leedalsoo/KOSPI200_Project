from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

MAX_KIS_WEBSOCKET_SUBSCRIPTIONS = 41
OPTION_TRADE_TR = "H0IOCNT0"
OPTION_BOOK_TR = "H0IOASP0"
FUTURES_TRADE_TR = "H0IFCNT0"
FUTURES_BOOK_TR = "H0IFASP0"
INDEX_TR = "H0UPCNT0"
KOSPI200_INDEX_SYMBOL = "2001"
_OPTION_SERIES = {"MONTHLY", "MONDAY_WEEKLY", "THURSDAY_WEEKLY"}
_MINI_FUTURES_ENABLE_STRATEGIES = {"S3", "S4", "STRATEGY_3", "STRATEGY_4"}


class SubscriptionPlanError(ValueError):
    pass


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    instrument_type: str
    product_series: str | None = None
    option_type: str | None = None
    strike: str | None = None
    expiry_yyyymmdd: str | None = None
    identity_valid: bool = True
    expiry_provenance_valid: bool = True
    master_age_hours: float = 0.0

    @classmethod
    def from_value(cls, symbol: str, value: Any) -> "ContractSpec":
        if isinstance(value, cls):
            if value.symbol != symbol:
                raise SubscriptionPlanError("CONTRACT_SYMBOL_KEY_MISMATCH")
            return value
        if not isinstance(value, Mapping):
            raise SubscriptionPlanError(f"CONTRACT_SPEC_INVALID:{symbol}")
        return cls(
            symbol=symbol,
            instrument_type=str(value.get("instrument_type", value.get("kind", "UNKNOWN"))).upper(),
            product_series=(str(value["product_series"]).upper() if value.get("product_series") else None),
            option_type=(str(value["option_type"]).upper() if value.get("option_type") else None),
            strike=(str(value["strike"]) if value.get("strike") is not None else None),
            expiry_yyyymmdd=(str(value["expiry_yyyymmdd"]) if value.get("expiry_yyyymmdd") else None),
            identity_valid=value.get("identity_valid") is True,
            expiry_provenance_valid=value.get("expiry_provenance_valid") is True,
            master_age_hours=float(value.get("master_age_hours", 999999.0)),
        )

    def subscriptions(self) -> tuple[tuple[str, str], ...]:
        if self.instrument_type == "OPTION":
            return ((OPTION_TRADE_TR, self.symbol), (OPTION_BOOK_TR, self.symbol))
        if self.instrument_type in {"MINI_FUTURE", "STANDARD_FUTURE"}:
            return ((FUTURES_TRADE_TR, self.symbol), (FUTURES_BOOK_TR, self.symbol))
        if self.instrument_type == "INDEX":
            return ((INDEX_TR, self.symbol),)
        return ()


def _valid_exact_date(value: str | None) -> bool:
    if not value or len(value) != 8 or not value.isdigit():
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _contract_blockers(contract: ContractSpec, *, now: datetime) -> list[str]:
    reasons: list[str] = []
    if not contract.identity_valid:
        reasons.append("IDENTITY_NOT_VALIDATED")
    if contract.instrument_type != "INDEX" and (
        contract.master_age_hours < 0 or contract.master_age_hours > 24
    ):
        reasons.append("MASTER_SNAPSHOT_STALE_OR_CLOCK_INVALID")
    if contract.instrument_type == "OPTION":
        if contract.product_series not in _OPTION_SERIES:
            reasons.append("OPTION_PRODUCT_SERIES_UNKNOWN")
        if contract.option_type not in {"CALL", "PUT"}:
            reasons.append("OPTION_SIDE_UNKNOWN")
        if not _valid_exact_date(contract.expiry_yyyymmdd):
            reasons.append("EXACT_EXPIRY_MISSING_OR_INVALID")
        if not contract.expiry_provenance_valid:
            reasons.append("EXACT_EXPIRY_PROVENANCE_MISSING")
        if _valid_exact_date(contract.expiry_yyyymmdd):
            expiry = datetime.strptime(contract.expiry_yyyymmdd, "%Y%m%d").date()
            if expiry < now.date():
                reasons.append("CONTRACT_EXPIRED")
    elif contract.instrument_type not in {"MINI_FUTURE", "STANDARD_FUTURE", "INDEX"}:
        reasons.append("INSTRUMENT_TYPE_UNKNOWN")
    return reasons


def build_subscription_plan(
    *,
    now: datetime,
    trading_day_approved: bool,
    active_strategies: Sequence[str],
    strategy_required_symbols: Mapping[str, Sequence[str]],
    contracts: Mapping[str, Any],
    held_position_symbols: Sequence[str] = (),
    open_order_symbols: Sequence[str] = (),
    mini_futures_symbols: Sequence[str] = (),
    subscription_limit: int = MAX_KIS_WEBSOCKET_SUBSCRIPTIONS,
    index_symbol: str = KOSPI200_INDEX_SYMBOL,
) -> dict[str, Any]:
    """Pure planner. It computes a plan only; it never connects to a collector."""
    if now.tzinfo is None:
        raise SubscriptionPlanError("PLANNER_CLOCK_MUST_BE_TIMEZONE_AWARE")
    if not isinstance(subscription_limit, int) or not 1 <= subscription_limit <= MAX_KIS_WEBSOCKET_SUBSCRIPTIONS:
        raise SubscriptionPlanError("SUBSCRIPTION_LIMIT_MUST_BE_1_TO_41")

    normalized: dict[str, ContractSpec] = {}
    for symbol, value in contracts.items():
        normalized[str(symbol)] = ContractSpec.from_value(str(symbol), value)

    selected: list[tuple[str, str]] = []
    selected_set: set[tuple[str, str]] = set()
    blocked_critical: list[dict[str, str]] = []
    strategy_status: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, str]] = []

    def add_pair(pair: tuple[str, str]) -> None:
        if pair not in selected_set:
            selected.append(pair)
            selected_set.add(pair)

    # Positions and outstanding orders are first priority. Unknown contracts are
    # not guessed; the affected item is reported as critical/unresolved.
    critical_symbols = list(dict.fromkeys([*held_position_symbols, *open_order_symbols]))
    for symbol in critical_symbols:
        contract = normalized.get(symbol)
        if contract is None:
            blocked_critical.append({"symbol": symbol, "reason": "CONTRACT_IDENTITY_NOT_FOUND"})
            continue
        pairs = contract.subscriptions()
        if not pairs:
            blocked_critical.append({"symbol": symbol, "reason": "INSTRUMENT_TYPE_UNKNOWN"})
            continue
        if len(selected_set | set(pairs)) > subscription_limit:
            blocked_critical.append({"symbol": symbol, "reason": "CRITICAL_POSITION_ORDER_EXCEEDS_SUBSCRIPTION_LIMIT"})
            continue
        for pair in pairs:
            add_pair(pair)
        blockers = _contract_blockers(contract, now=now)
        if blockers:
            blocked_critical.append({"symbol": symbol, "reason": ",".join(blockers)})

    # The index feed is always prioritized after held/open contracts.
    index_pair = (INDEX_TR, index_symbol)
    if index_pair not in selected_set:
        if len(selected_set) < subscription_limit:
            add_pair(index_pair)
        else:
            excluded.append({"tr_id": INDEX_TR, "symbol": index_symbol, "reason": "SUBSCRIPTION_LIMIT_AFTER_CRITICAL"})
    index_available = index_pair in selected_set

    active = list(dict.fromkeys(str(item).upper() for item in active_strategies))
    for strategy in active:
        required = list(dict.fromkeys(str(item) for item in strategy_required_symbols.get(strategy, ())))
        if not required:
            strategy_status[strategy] = {
                "status": "BLOCKED",
                "reasons": ["STRATEGY_REQUIRED_SYMBOLS_UNDEFINED"],
                "required_symbols": [],
                "planned_symbols": [],
            }
            continue
        if not trading_day_approved:
            strategy_status[strategy] = {
                "status": "BLOCKED",
                "reasons": ["TRADING_DAY_NOT_APPROVED"],
                "required_symbols": required,
                "planned_symbols": [],
            }
            continue

        candidate_pairs: list[tuple[str, str]] = []
        reasons_by_symbol: dict[str, list[str]] = {}
        for symbol in required:
            contract = normalized.get(symbol)
            if contract is None:
                reasons_by_symbol[symbol] = ["CONTRACT_IDENTITY_NOT_FOUND"]
                continue
            if contract.instrument_type == "MINI_FUTURE" and strategy not in _MINI_FUTURES_ENABLE_STRATEGIES:
                reasons_by_symbol[symbol] = ["MINI_FUTURES_ONLY_ALLOWED_FOR_ENABLED_S3_S4"]
                continue
            if contract.instrument_type == "STANDARD_FUTURE":
                reasons_by_symbol[symbol] = ["STANDARD_FUTURES_NOT_APPROVED_BY_STRATEGY_DESIGN"]
                continue
            blockers = _contract_blockers(contract, now=now)
            if blockers:
                reasons_by_symbol[symbol] = blockers
                continue
            pairs = contract.subscriptions()
            if not pairs:
                reasons_by_symbol[symbol] = ["INSTRUMENT_TYPE_UNKNOWN"]
                continue
            candidate_pairs.extend(pairs)

        if reasons_by_symbol:
            strategy_status[strategy] = {
                "status": "BLOCKED",
                "reasons": sorted({reason for values in reasons_by_symbol.values() for reason in values}),
                "blocked_symbols": reasons_by_symbol,
                "required_symbols": required,
                "planned_symbols": [],
            }
            continue

        additions = [pair for pair in dict.fromkeys(candidate_pairs) if pair not in selected_set]
        if len(selected_set) + len(additions) > subscription_limit:
            strategy_status[strategy] = {
                "status": "BLOCKED",
                "reasons": ["SUBSCRIPTION_CAPACITY_EXCEEDED"],
                "required_symbols": required,
                "planned_symbols": [],
                "candidate_registration_count": len(set(candidate_pairs)),
                "available_registration_count": max(0, subscription_limit - len(selected_set)),
            }
            for tr_id, symbol in additions:
                excluded.append({"tr_id": tr_id, "symbol": symbol, "reason": f"CAPACITY_EXCEEDED:{strategy}"})
            continue

        for pair in additions:
            add_pair(pair)
        strategy_status[strategy] = {
            "status": "PLANNED",
            "reasons": [],
            "required_symbols": required,
            "planned_symbols": required,
        }

    # S3/S4 future subscriptions are opt-in only. They are included only when
    # the corresponding strategy is active and the symbols are explicit.
    enabled_s3_s4 = any(item in _MINI_FUTURES_ENABLE_STRATEGIES for item in active)
    for symbol in dict.fromkeys(mini_futures_symbols):
        contract = normalized.get(symbol)
        if not enabled_s3_s4:
            excluded.append({"tr_id": FUTURES_TRADE_TR, "symbol": symbol, "reason": "S3_S4_NOT_ENABLED"})
            excluded.append({"tr_id": FUTURES_BOOK_TR, "symbol": symbol, "reason": "S3_S4_NOT_ENABLED"})
            continue
        if not trading_day_approved:
            excluded.append({"tr_id": FUTURES_TRADE_TR, "symbol": symbol, "reason": "TRADING_DAY_NOT_APPROVED"})
            excluded.append({"tr_id": FUTURES_BOOK_TR, "symbol": symbol, "reason": "TRADING_DAY_NOT_APPROVED"})
            continue
        if contract is None or contract.instrument_type != "MINI_FUTURE":
            excluded.append({"tr_id": FUTURES_TRADE_TR, "symbol": symbol, "reason": "MINI_FUTURE_IDENTITY_NOT_VALIDATED"})
            excluded.append({"tr_id": FUTURES_BOOK_TR, "symbol": symbol, "reason": "MINI_FUTURE_IDENTITY_NOT_VALIDATED"})
            continue
        blockers = _contract_blockers(contract, now=now)
        if blockers:
            excluded.extend({"tr_id": tr, "symbol": symbol, "reason": ",".join(blockers)} for tr in contract.subscriptions())
            continue
        pairs = contract.subscriptions()
        additions = [pair for pair in pairs if pair not in selected_set]
        if len(selected_set) + len(additions) > subscription_limit:
            excluded.extend({"tr_id": tr, "symbol": sym, "reason": "SUBSCRIPTION_CAPACITY_EXCEEDED:MINI_FUTURES"} for tr, sym in additions)
            continue
        for pair in additions:
            add_pair(pair)

    return {
        "schema_version": "kis-subscription-plan-v1",
        "generated_at": now.isoformat(),
        "mode": "DRY_RUN_PLAN_ONLY",
        "trading_day_approved": bool(trading_day_approved),
        "subscription_limit": subscription_limit,
        "subscription_count": len(selected),
        "within_limit": len(selected) <= subscription_limit,
        "subscriptions": [{"tr_id": tr_id, "symbol": symbol} for tr_id, symbol in selected],
        "held_or_open_order_blockers": blocked_critical,
        "strategy_status": strategy_status,
        "excluded_subscriptions": excluded,
        "index_subscription_planned": index_available,
        "quote_freshness": {
            "max_quote_age_seconds": None,
            "status": "UNSET",
            "note": "Planning channels does not validate market-data freshness.",
        },
        "rotation": {
            "apply_to_collector": False,
            "minimum_hold_seconds": None,
            "atm_hysteresis_points": None,
            "automatic_rotation_enabled": False,
            "status": "BLOCKED_THRESHOLDS_UNSET",
        },
        "safety": {
            "collector_touched": False,
            "websocket_opened": False,
            "unsubscribe_ack_required_before_subscribe": True,
            "order_api_called": False,
        },
    }


def build_rotation_plan(
    *,
    active_subscriptions: Sequence[tuple[str, str]],
    desired_subscriptions: Sequence[tuple[str, str]],
    subscription_limit: int = MAX_KIS_WEBSOCKET_SUBSCRIPTIONS,
    minimum_hold_seconds: int | None = None,
    atm_hysteresis_points: str | None = None,
) -> dict[str, Any]:
    """Describe a safe rotation sequence; no WebSocket operation is performed."""
    if not 1 <= subscription_limit <= MAX_KIS_WEBSOCKET_SUBSCRIPTIONS:
        raise SubscriptionPlanError("SUBSCRIPTION_LIMIT_MUST_BE_1_TO_41")
    active = list(dict.fromkeys((str(tr), str(sym)) for tr, sym in active_subscriptions))
    desired = list(dict.fromkeys((str(tr), str(sym)) for tr, sym in desired_subscriptions))
    if len(active) > subscription_limit or len(desired) > subscription_limit:
        raise SubscriptionPlanError("KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED")
    removals = [pair for pair in active if pair not in set(desired)]
    additions = [pair for pair in desired if pair not in set(active)]
    thresholds_set = (
        isinstance(minimum_hold_seconds, int)
        and minimum_hold_seconds > 0
        and atm_hysteresis_points is not None
        and str(atm_hysteresis_points).strip() != ""
    )
    return {
        "mode": "DRY_RUN_PLAN_ONLY",
        "active_count": len(active),
        "desired_count": len(desired),
        "subscription_limit": subscription_limit,
        "peak_requested_count": max(len(active), len(desired)),
        "within_limit": max(len(active), len(desired)) <= subscription_limit,
        "removals": [{"tr_id": tr, "symbol": sym} for tr, sym in removals],
        "additions": [{"tr_id": tr, "symbol": sym} for tr, sym in additions],
        "steps": (
            [
                {"step": 1, "action": "UNSUBSCRIBE", "items": [{"tr_id": tr, "symbol": sym} for tr, sym in removals]},
                {"step": 2, "action": "WAIT_FOR_UNSUBSCRIBE_ACK", "required": True},
                {"step": 3, "action": "SUBSCRIBE", "items": [{"tr_id": tr, "symbol": sym} for tr, sym in additions]},
            ]
            if thresholds_set and (removals or additions)
            else []
        ),
        "automatic_rotation_enabled": thresholds_set,
        "rotation_status": "PLAN_ONLY_THRESHOLDS_SET" if thresholds_set else "BLOCKED_THRESHOLDS_UNSET",
        "collector_apply": False,
    }
