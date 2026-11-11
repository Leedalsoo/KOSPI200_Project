from __future__ import annotations

from decimal import Decimal

from contracts.types import ExecutionLeg, MultiLegExecutionPlan
from environments.high_speed.validation_only_s15b_observed_option_adapter import (
    S15BObservedOptionMarketAdapter,
    S15BObservedOptionMarketError,
)


class S15BOptionProposalResolver:
    """Validation-only resolver for one manifest-bound Strategy 1 OPTION proposal."""

    def __init__(self, market_adapter: S15BObservedOptionMarketAdapter) -> None:
        self.market_adapter = market_adapter

    def resolve(
        self,
        proposal,
        *,
        scenario_contract_key: str,
        group_id: str,
    ) -> MultiLegExecutionPlan:
        if not group_id.strip():
            raise S15BObservedOptionMarketError("S15B_OPTION_GROUP_ID_REQUIRED")
        expected = self.market_adapter.expected_proposal
        actual = {
            "asset_type": str(getattr(proposal, "asset_type", "")).upper(),
            "side": str(getattr(proposal, "side", "")).upper(),
            "option_type": str(getattr(proposal, "option_type", "")).upper(),
            "strike": Decimal(str(getattr(proposal, "strike", "0"))),
            "quantity": int(getattr(proposal, "proposed_quantity", 0)),
            "tag_id": str(getattr(proposal, "tag_id", "")),
        }
        normalized_expected = {
            "asset_type": str(expected["asset_type"]).upper(),
            "side": str(expected["side"]).upper(),
            "option_type": str(expected["option_type"]).upper(),
            "strike": Decimal(str(expected["strike"])),
            "quantity": int(expected["quantity"]),
            "tag_id": str(expected["tag_id"]),
        }
        if actual != normalized_expected:
            raise S15BObservedOptionMarketError("S15B_OPTION_PROPOSAL_SCENARIO_MISMATCH")
        if str(getattr(proposal, "track_id", "")) != "TRACK1_TAIL_DEFENSE":
            raise S15BObservedOptionMarketError("S15B_OPTION_PROPOSAL_STRATEGY_MISMATCH")
        if getattr(proposal, "requested_price", None) is not None:
            raise S15BObservedOptionMarketError("S15B_OPTION_PROPOSAL_PRICE_MUST_REMAIN_UNSET")

        mapping = self.market_adapter.contract_mapping(scenario_contract_key)
        identity = self.market_adapter.identity(scenario_contract_key)
        quote = self.market_adapter.quote(scenario_contract_key)
        freshness = self.market_adapter.freshness(scenario_contract_key)
        book = self.market_adapter.order_book(scenario_contract_key)
        if (identity.symbol != mapping["symbol"] or identity.option_type != mapping["option_type"]
                or identity.strike != Decimal(mapping["strike"]) or identity.expiry != mapping["expiry"]):
            raise S15BObservedOptionMarketError("S15B_OPTION_RESOLVED_IDENTITY_MISMATCH")
        if identity.contract_multiplier is None or identity.contract_multiplier <= 0:
            raise S15BObservedOptionMarketError("S15B_OPTION_VALIDATION_MULTIPLIER_UNAVAILABLE")
        if quote.bid is None or quote.ask is None or quote.last is None or quote.bid <= 0 or quote.ask <= quote.bid:
            raise S15BObservedOptionMarketError("S15B_OPTION_VALIDATION_QUOTE_INVALID")
        if freshness.status.value != "FRESH":
            raise S15BObservedOptionMarketError(f"S15B_OPTION_VALIDATION_FRESHNESS_BLOCKED:{freshness.status.value}")
        if not self.market_adapter.get_order_book(identity.symbol) or book.symbol != identity.symbol:
            raise S15BObservedOptionMarketError("S15B_OPTION_VALIDATION_ORDERBOOK_UNAVAILABLE")

        manifest = self.market_adapter.manifest
        return MultiLegExecutionPlan(
            group_id=group_id,
            strategy_id="TRACK1_TAIL_DEFENSE",
            purpose="S15B_VALIDATION_ONLY_SHORT_ACCUMULATION",
            legs=(ExecutionLeg(
                leg_id=str(getattr(proposal, "tag_id")),
                side=str(getattr(proposal, "side")).upper(),
                quantity=int(getattr(proposal, "proposed_quantity")),
                option_type=str(getattr(proposal, "option_type")).upper(),
                strike=Decimal(str(getattr(proposal, "strike"))),
                requested_price=None,
                position_role="NONE",
                instrument_identity=identity,
            ),),
            strategy_code_version=str(manifest["signal_observation"]["strategy_code_version"]),
            strategy_config_version=str(manifest["dataset_id"]),
            strategy_config_hash=self.market_adapter.manifest_sha256,
        )
