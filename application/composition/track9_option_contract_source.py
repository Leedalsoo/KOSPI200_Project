from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from infrastructure.kis.kis_websocket_option_identity_resolver import (
    KISWebSocketOptionIdentityResolver,
    rows_from_snapshot,
)


@dataclass(frozen=True)
class Track9OptionCandidate:
    rank: int
    symbol: str
    expiry_yyyymmdd: str
    strike: Decimal
    option_type: str
    product_series: str
    instrument_family: str
    master_sha256: str
    expiry_evidence_sha256: str
    bid: Decimal | None
    ask: Decimal | None
    bid_quantity: Decimal | None
    ask_quantity: Decimal | None
    spread_ratio: Decimal | None
    quote_freshness_timestamp: datetime | None
    quote_age_seconds: float | None
    volume: Decimal | None
    quote_source: str | None
    blockers: tuple[str, ...]

    @property
    def two_sided_quote_valid(self) -> bool:
        return (
            self.bid is not None
            and self.ask is not None
            and self.bid > 0
            and self.ask > 0
            and self.ask >= self.bid
            and self.bid_quantity is not None
            and self.ask_quantity is not None
            and self.bid_quantity > 0
            and self.ask_quantity > 0
        )


@dataclass(frozen=True)
class Track9OptionSelection:
    status: str
    reason: str
    as_of: datetime
    underlying_price: Decimal
    expiry_yyyymmdd: str | None
    atm_strike: Decimal | None
    rank4: Track9OptionCandidate | None
    rank3: Track9OptionCandidate | None
    master_sha256: str | None
    s1_expiry_yyyymmdd: str | None
    s1_short_put_remaining: int
    s1_position_lot_ids: tuple[str, ...]
    blockers: tuple[str, ...]


class Track9OptionContractSource:
    """Resolve S9 PUT candidates from KIS master + exact KIS REST expiry evidence.

    This source only prepares input evidence. It never submits orders. Unknown
    freshness/liquidity/position-link policies remain blocking configuration.
    """

    def __init__(
        self,
        *,
        orderbook_source: Any,
        project_root: Path | None = None,
        max_quote_age_seconds: float | None = None,
        max_spread_ratio: Decimal | str | None = None,
        min_top_level_quantity: Decimal | int | None = None,
        min_volume: Decimal | int | None = None,
        s1_put_link_ratio: Decimal | str | None = None,
        third_strike_insufficient_action: str | None = None,
        s1_position_lot_store: Any | None = None,
        run_id: str | None = None,
        s1_strategy_id: str = "TRACK1_TAIL_DEFENSE",
        resolver_factory: Callable[..., KISWebSocketOptionIdentityResolver] | None = None,
        rows_loader: Callable[[Any], tuple[dict[str, object], ...]] | None = None,
    ) -> None:
        self.orderbook_source = orderbook_source
        self.s1_position_lot_store = s1_position_lot_store
        self.run_id = str(run_id or "").strip()
        self.s1_strategy_id = str(s1_strategy_id).strip()
        self.project_root = Path(project_root or Path.cwd())
        self.max_quote_age_seconds = (
            float(max_quote_age_seconds) if max_quote_age_seconds is not None else None
        )
        self.max_spread_ratio = (
            Decimal(str(max_spread_ratio)) if max_spread_ratio is not None else None
        )
        self.min_top_level_quantity = (
            Decimal(str(min_top_level_quantity))
            if min_top_level_quantity is not None
            else None
        )
        self.min_volume = Decimal(str(min_volume)) if min_volume is not None else None
        self.s1_put_link_ratio = (
            Decimal(str(s1_put_link_ratio)) if s1_put_link_ratio is not None else None
        )
        self.third_strike_insufficient_action = (
            str(third_strike_insufficient_action).strip()
            if third_strike_insufficient_action is not None
            else None
        )
        self._resolver_factory = resolver_factory or KISWebSocketOptionIdentityResolver.for_trading_date
        self._rows_loader = rows_loader or rows_from_snapshot
        self._date_cache: dict[date, tuple[Any, tuple[dict[str, object], ...], Any]] = {}

    def _resolver_for_date(self, market_date: date):
        cached = self._date_cache.get(market_date)
        if cached is not None:
            return cached
        resolver = self._resolver_factory(market_date, project_root=self.project_root)
        snapshot = resolver.target_snapshot
        rows = self._rows_loader(snapshot)
        cached = (snapshot, rows, resolver)
        self._date_cache[market_date] = cached
        return cached

    @staticmethod
    def _valid_book(book: Any, symbol: str) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        if book is None or str(getattr(book, "symbol", "")).strip() != symbol:
            raise ValueError("TRACK9_OPTION_ORDERBOOK_IDENTITY_MISMATCH")
        source = str(getattr(book, "source", "") or "")
        if "KIS" not in source.upper() or "SYNTHETIC" in source.upper():
            raise ValueError("TRACK9_OPTION_ORDERBOOK_SOURCE_NOT_AUTHORITATIVE")
        bids = tuple(getattr(book, "bid_levels", ()) or ())
        asks = tuple(getattr(book, "ask_levels", ()) or ())
        if not bids or not asks:
            raise ValueError("TRACK9_OPTION_TWO_SIDED_QUOTE_MISSING")
        try:
            bid = Decimal(str(bids[0].price))
            ask = Decimal(str(asks[0].price))
            bid_qty = Decimal(str(bids[0].quantity))
            ask_qty = Decimal(str(asks[0].quantity))
        except (AttributeError, InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("TRACK9_OPTION_QUOTE_FIELDS_INVALID") from exc
        if (
            not all(value.is_finite() for value in (bid, ask, bid_qty, ask_qty))
            or bid <= 0
            or ask <= 0
            or ask < bid
            or bid_qty <= 0
            or ask_qty <= 0
        ):
            raise ValueError("TRACK9_OPTION_TWO_SIDED_QUOTE_INVALID")
        return bid, ask, bid_qty, ask_qty

    def _candidate(
        self,
        *,
        row: dict[str, object],
        rank: int,
        expiry: str,
        master_sha256: str,
        expiry_evidence_sha256: str,
        as_of: datetime,
    ) -> Track9OptionCandidate:
        symbol = str(row.get("short_code") or "").strip()
        blockers: list[str] = []
        bid = ask = bid_qty = ask_qty = volume = None
        spread_ratio = None
        received_at = None
        age = None
        source_name = None

        get_book = getattr(self.orderbook_source, "get_order_book_with_timestamp", None)
        if not callable(get_book):
            book = None
            blockers.append("QUOTE_RECEIPT_TIMESTAMP_SOURCE_UNAVAILABLE")
        else:
            try:
                book, received_at = get_book(symbol, as_of=as_of)
            except (TypeError, ValueError, AttributeError):
                book, received_at = None, None
                blockers.append("QUOTE_SNAPSHOT_UNAVAILABLE")

        if book is None:
            if not blockers:
                blockers.append("TRACK9_OPTION_ORDERBOOK_UNAVAILABLE")
        else:
            source_name = str(getattr(book, "source", "") or "")
            try:
                bid, ask, bid_qty, ask_qty = self._valid_book(book, symbol)
            except ValueError as exc:
                blockers.append(str(exc))
            if bid is not None and ask is not None and bid > 0 and ask > 0:
                midpoint = (bid + ask) / Decimal("2")
                spread_ratio = (ask - bid) / midpoint if midpoint > 0 else None
                if self.max_spread_ratio is None:
                    blockers.append("TRACK9_QUOTE_SPREAD_THRESHOLD_UNSET")
                elif spread_ratio is None or spread_ratio > self.max_spread_ratio:
                    blockers.append("TRACK9_OPTION_SPREAD_ABOVE_MAXIMUM")
            if bid_qty is not None and ask_qty is not None:
                if self.min_top_level_quantity is None:
                    blockers.append("TRACK9_TOP_LEVEL_DEPTH_THRESHOLD_UNSET")
                elif min(bid_qty, ask_qty) < self.min_top_level_quantity:
                    blockers.append("TRACK9_OPTION_TOP_LEVEL_DEPTH_BELOW_MINIMUM")

        get_volume = getattr(self.orderbook_source, "get_volume_with_timestamp", None)
        if callable(get_volume):
            try:
                volume, volume_at = get_volume(symbol, as_of=as_of)
                if (
                    volume_at is None
                    or volume_at.tzinfo is None
                    or volume_at > as_of
                    or volume_at.astimezone(ZoneInfo("Asia/Seoul")).date()
                    != as_of.astimezone(ZoneInfo("Asia/Seoul")).date()
                ):
                    volume = None
            except (TypeError, ValueError, AttributeError):
                volume = None
        if volume is None:
            blockers.append("TRACK9_OPTION_AUTHORITATIVE_VOLUME_UNAVAILABLE")
        elif self.min_volume is None:
            blockers.append("TRACK9_MIN_VOLUME_UNSET")
        elif volume < self.min_volume:
            blockers.append("TRACK9_OPTION_VOLUME_BELOW_MINIMUM")

        if received_at is None:
            blockers.append("TRACK9_OPTION_QUOTE_RECEIPT_TIME_UNAVAILABLE")
        elif received_at.tzinfo is None or as_of.tzinfo is None:
            blockers.append("TRACK9_OPTION_QUOTE_TIMESTAMP_TIMEZONE_REQUIRED")
        else:
            age = (as_of - received_at).total_seconds()
            if age < 0:
                blockers.append("TRACK9_OPTION_QUOTE_TIMESTAMP_IN_FUTURE")
            elif self.max_quote_age_seconds is None:
                blockers.append("TRACK9_QUOTE_FRESHNESS_THRESHOLD_UNSET")
            elif age > self.max_quote_age_seconds:
                blockers.append("TRACK9_OPTION_QUOTE_STALE")

        if self.s1_put_link_ratio is None:
            blockers.append("TRACK9_S1_PUT_LINK_RATIO_UNSET")
        elif self.s1_put_link_ratio <= 0:
            blockers.append("TRACK9_S1_PUT_LINK_RATIO_INVALID")

        return Track9OptionCandidate(
            rank=rank,
            symbol=symbol,
            expiry_yyyymmdd=expiry,
            strike=Decimal(str(row["strike"])),
            option_type=str(row["option_type"]),
            product_series=str(row["product_series"]),
            instrument_family=str(row["instrument_family"]),
            master_sha256=master_sha256,
            expiry_evidence_sha256=expiry_evidence_sha256,
            bid=bid,
            ask=ask,
            bid_quantity=bid_qty,
            ask_quantity=ask_qty,
            spread_ratio=spread_ratio,
            quote_freshness_timestamp=received_at,
            quote_age_seconds=age,
            volume=Decimal(str(volume)) if volume is not None else None,
            quote_source=source_name,
            blockers=tuple(dict.fromkeys(blockers)),
        )

    def select(self, *, current_price: Decimal, as_of: datetime) -> Track9OptionSelection:
        price = Decimal(str(current_price))
        if not price.is_finite() or price <= 0:
            raise ValueError("TRACK9_AUTHORITATIVE_UNDERLYING_PRICE_REQUIRED")
        if as_of.tzinfo is None:
            raise ValueError("TRACK9_AS_OF_TIMEZONE_REQUIRED")

        market_date = as_of.astimezone(ZoneInfo("Asia/Seoul")).date()
        if self.s1_position_lot_store is None or not self.run_id or not self.s1_strategy_id:
            raise ValueError("TRACK9_S1_POSITION_SOURCE_UNAVAILABLE")
        open_lots = getattr(self.s1_position_lot_store, "open_lots", None)
        if not callable(open_lots):
            raise ValueError("TRACK9_S1_POSITION_LOT_READ_METHOD_UNAVAILABLE")
        s1_put_lots = []
        for lot in open_lots():
            identity = getattr(lot, "instrument_identity", None)
            if (
                str(getattr(lot, "run_id", "")) != self.run_id
                or str(getattr(lot, "strategy_id", "")) != self.s1_strategy_id
                or str(getattr(lot, "side", "")).upper() != "SELL"
                or int(getattr(lot, "remaining_quantity", 0) or 0) <= 0
            ):
                continue
            if identity is None:
                raise ValueError("TRACK9_S1_SHORT_PUT_IDENTITY_UNAVAILABLE")
            option_type = str(getattr(identity, "option_type", "")).upper()
            if not option_type:
                raise ValueError("TRACK9_S1_SHORT_PUT_IDENTITY_UNAVAILABLE")
            if option_type != "PUT":
                continue
            expiry_text = str(getattr(identity, "expiry", "") or "").replace("-", "")[:8]
            if len(expiry_text) != 8 or not expiry_text.isdigit():
                raise ValueError("TRACK9_S1_SHORT_PUT_EXPIRY_NOT_EXACT")
            s1_put_lots.append((lot, expiry_text))
        if not s1_put_lots:
            raise ValueError("TRACK9_S1_SHORT_PUT_POSITION_UNAVAILABLE")
        s1_expiries = {expiry_text for _, expiry_text in s1_put_lots}
        if len(s1_expiries) != 1:
            raise ValueError("TRACK9_S1_SHORT_PUT_EXPIRY_AMBIGUOUS")
        s1_expiry = next(iter(s1_expiries))
        s1_short_put_remaining = sum(
            int(getattr(lot, "remaining_quantity", 0) or 0)
            for lot, _ in s1_put_lots
        )
        s1_position_lot_ids = tuple(
            sorted(str(getattr(lot, "execution_id", "")) for lot, _ in s1_put_lots)
        )
        if s1_short_put_remaining <= 0:
            raise ValueError("TRACK9_S1_SHORT_PUT_REMAINING_QUANTITY_INVALID")

        snapshot, rows, resolver = self._resolver_for_date(market_date)
        master_sha256 = str(snapshot.archive_sha256)
        for lot, lot_expiry in s1_put_lots:
            lot_identity = getattr(lot, "instrument_identity", None)
            lot_symbol = str(
                getattr(lot_identity, "symbol", "")
                or getattr(lot_identity, "instrument_id", "")
            ).strip()
            lot_master_identity = resolver.get_contract_identity(lot_symbol)
            lot_expiry_evidence = resolver.get_expiry_record(lot_symbol)
            if lot_master_identity is None or lot_expiry_evidence is None:
                raise ValueError("TRACK9_S1_SHORT_PUT_KIS_IDENTITY_UNRESOLVED")
            if (
                str(lot_master_identity.expiry) != lot_expiry
                or str(lot_expiry_evidence.expiry_yyyymmdd) != lot_expiry
                or str(lot_expiry_evidence.target_master_sha256) != master_sha256
                or str(lot_master_identity.option_type).upper() != "PUT"
                or Decimal(str(lot_master_identity.strike))
                != Decimal(str(getattr(lot_identity, "strike", "NaN")))
            ):
                raise ValueError("TRACK9_S1_SHORT_PUT_KIS_IDENTITY_MISMATCH")
        resolved: list[tuple[dict[str, object], str, str]] = []
        for row in rows:
            if (
                row.get("option_type") != "PUT"
                or row.get("product_series") != "MONTHLY"
                or row.get("instrument_family") != "STANDARD"
                or row.get("strike") is None
            ):
                continue
            symbol = str(row.get("short_code") or "")
            identity = resolver.get_contract_identity(symbol)
            evidence = resolver.get_expiry_record(symbol)
            if identity is None or evidence is None:
                continue
            expiry = str(identity.expiry)
            if expiry != s1_expiry or expiry < market_date.strftime("%Y%m%d"):
                continue
            if (
                str(identity.option_type).upper() != "PUT"
                or Decimal(str(identity.strike)) != Decimal(str(row["strike"]))
                or str(evidence.expiry_yyyymmdd) != expiry
                or str(evidence.target_master_sha256) != master_sha256
            ):
                continue
            resolved.append((row, expiry, str(evidence.evidence_set_sha256)))

        if not resolved:
            raise ValueError("TRACK9_EXACT_KIS_MASTER_EXPIRY_EVIDENCE_UNAVAILABLE_FOR_S1_EXPIRY")

        expiry = s1_expiry
        series = [item for item in resolved if item[1] == expiry]
        by_strike = {Decimal(str(row["strike"])): (row, evidence_hash) for row, _, evidence_hash in series}
        strikes = sorted(by_strike)
        distances = sorted((abs(strike - price), strike) for strike in strikes)
        if not distances:
            raise ValueError("TRACK9_KIS_PUT_STRIKE_LADDER_UNAVAILABLE")
        if len(distances) > 1 and distances[0][0] == distances[1][0]:
            raise ValueError("TRACK9_ATM_STRIKE_AMBIGUOUS")
        atm = distances[0][1]
        otm_strikes = sorted((strike for strike in strikes if strike < atm), reverse=True)
        if len(otm_strikes) < 4:
            raise ValueError("TRACK9_FOURTH_AND_THIRD_OTM_PUT_REQUIRED")
        rank4_strike = otm_strikes[3]
        rank3_strike = otm_strikes[2]
        if atm - otm_strikes[0] != Decimal("2.5") or any(
            otm_strikes[index] - otm_strikes[index + 1] != Decimal("2.5")
            for index in range(3)
        ):
            raise ValueError("TRACK9_KIS_MASTER_STRIKE_LADDER_GAP")

        blockers: list[str] = []
        if self.min_volume is None:
            blockers.append("TRACK9_MIN_VOLUME_UNSET")
        elif self.min_volume <= 0:
            blockers.append("TRACK9_MIN_VOLUME_INVALID")
        if self.s1_put_link_ratio is None:
            blockers.append("TRACK9_S1_PUT_LINK_RATIO_UNSET")
        if self.max_quote_age_seconds is None:
            blockers.append("TRACK9_QUOTE_FRESHNESS_THRESHOLD_UNSET")
        elif self.max_quote_age_seconds <= 0:
            blockers.append("TRACK9_QUOTE_FRESHNESS_THRESHOLD_INVALID")
        if self.max_spread_ratio is None:
            blockers.append("TRACK9_QUOTE_SPREAD_THRESHOLD_UNSET")
        elif self.max_spread_ratio <= 0:
            blockers.append("TRACK9_QUOTE_SPREAD_THRESHOLD_INVALID")
        if self.min_top_level_quantity is None:
            blockers.append("TRACK9_TOP_LEVEL_DEPTH_THRESHOLD_UNSET")
        elif self.min_top_level_quantity <= 0:
            blockers.append("TRACK9_TOP_LEVEL_DEPTH_THRESHOLD_INVALID")
        if self.third_strike_insufficient_action is None:
            blockers.append("TRACK9_THIRD_STRIKE_INSUFFICIENT_ACTION_UNSET")
        elif self.third_strike_insufficient_action not in {
            "BLOCK_FOR_SESSION",
            "WAIT_AND_RECHECK",
        }:
            blockers.append("TRACK9_THIRD_STRIKE_INSUFFICIENT_ACTION_INVALID")
        elif self.third_strike_insufficient_action == "WAIT_AND_RECHECK":
            blockers.append("TRACK9_RECHECK_COUNT_INTERVAL_UNSET")

        def candidate_for(strike: Decimal, rank: int) -> Track9OptionCandidate:
            row, evidence_hash = by_strike[strike]
            candidate = self._candidate(
                row=row,
                rank=rank,
                expiry=expiry,
                master_sha256=master_sha256,
                expiry_evidence_sha256=evidence_hash,
                as_of=as_of,
            )
            blockers.extend(candidate.blockers)
            return candidate

        rank4 = candidate_for(rank4_strike, 4)
        rank3 = candidate_for(rank3_strike, 3)
        unique_blockers = tuple(dict.fromkeys(blockers))
        return Track9OptionSelection(
            status="INPUTS_VALID" if not unique_blockers else "BLOCKED",
            reason="TRACK9_INPUTS_VALID" if not unique_blockers else ";".join(unique_blockers),
            as_of=as_of,
            underlying_price=price,
            expiry_yyyymmdd=expiry,
            atm_strike=atm,
            rank4=rank4,
            rank3=rank3,
            master_sha256=master_sha256,
            s1_expiry_yyyymmdd=s1_expiry,
            s1_short_put_remaining=s1_short_put_remaining,
            s1_position_lot_ids=s1_position_lot_ids,
            blockers=unique_blockers,
        )
